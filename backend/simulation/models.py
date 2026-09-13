"""GramSentinel Intelligence Simulator — persistent data model (Phase 2).

Phase 1 audit (see GRAMSENTINEL_SIMULATION_PHASE1_AUDIT.md, §18-20) decided:
  - a dedicated `simulation` Django app, physically separate from every
    operational app (`community`, `alerts`, `assessments`);
  - the existing `core.Village` and the existing `User` model are reused —
    no SimulationVillage, no second account model;
  - every simulation model carries its own explicit `village` foreign key,
    never relying solely on a parent chain, so a permission check can always
    do a direct `simulation_object.village_id == officer.village_id`
    comparison without a join.

Phase 2 populates only `SimulationScenario`, `SimulationSession`,
`SimulationEvent` and `SimulationSourceSignal` (via the seed command). The
remaining four models — `SimulationAgentRun`, `SimulationSafetyCheck`,
`SimulationResult`, `SimulationInvestigation` — exist as schema only in this
phase, so later phases never need a disruptive redesign. Nothing in this
file executes an agent, calls an LLM, runs the Safety Engine, or writes to
any operational table (`CommunityReport`, `Alert`, `Investigation`, ...).

Data contract for each model, including which phase starts writing to it,
is documented on the model itself below (also summarised in the Phase 2
report).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from alerts.models import Alert
from core.constants import SourceKind


class SimulationVillageScoped(models.Model):
    """Shared base: every simulation model gets its own `village` FK.

    This is deliberate duplication, not an oversight — Phase 1 ADR §9
    requires every simulation row to carry an explicit village reference so
    that a future permission check is a same-row `village_id` comparison,
    never a multi-hop join through session -> scenario. `on_delete=PROTECT`
    matches the existing convention for operationally-significant village
    references (`alerts.Alert.village`, `community.CommunityReport.village`)
    — a village is never silently emptied of its simulation history by a
    cascade.
    """

    village = models.ForeignKey(
        "core.Village",
        on_delete=models.PROTECT,
    )

    class Meta:
        abstract = True


class SimulationScenario(SimulationVillageScoped):
    """A reusable, database-backed synthetic demonstration template.

    Created in Phase 2. Read (list + detail) in Phase 2 via the read-only
    API (§24-26). Selected, but never executed, by the Phase 2 frontend.
    Execution (creating a `SimulationSession` from one of these) begins in
    Phase 3.

    The database is the source of truth for scenario content — the frontend
    never hard-codes a scenario name/description/type.
    """

    class ScenarioType(models.TextChoices):
        EMERGING_SIGNAL = "EMERGING_SIGNAL", "Emerging Community Signal"
        STABLE_COMMUNITY = "STABLE_COMMUNITY", "Stable Community"
        WEAK_EVIDENCE = "WEAK_EVIDENCE", "False Positive / Weak Evidence"
        MISSING_DATA = "MISSING_DATA", "Missing Data"
        SOURCE_DISAGREEMENT = "SOURCE_DISAGREEMENT", "Source Disagreement"
        WHAT_IF = "WHAT_IF", "What-If Simulation"
        REPLAY = "REPLAY", "Signal Replay"
        LIVE_EMERGENCE = "LIVE_EMERGENCE", "Live Signal Emergence"

    name = models.CharField(max_length=160)
    scenario_type = models.CharField(max_length=32, choices=ScenarioType.choices)
    description = models.TextField(
        help_text="Plain-language description shown on the scenario card."
    )
    is_active = models.BooleanField(default=True)
    version = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["village__code", "scenario_type", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["village", "scenario_type", "version"],
                name="unique_simulation_scenario_version_per_village",
            ),
        ]
        indexes = [
            models.Index(fields=["village", "scenario_type"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} [{self.village.code}] v{self.version}"


class SimulationSession(SimulationVillageScoped):
    """One run of a scenario — schema-only in Phase 2.

    Created in Phase 2 ONLY by the seed command, as an unexecuted "template"
    container that holds a scenario's canonical synthetic weekly timeline
    (`SimulationEvent`/`SimulationSourceSignal` — see the relationship
    requirement in the Phase 2 task, §15). No API in this phase creates a
    session, and `status` for every Phase-2-seeded row is `NOT_STARTED`
    because nothing has ever executed against it.

    `health_officer` is nullable specifically for this reason: a
    seed-created template session belongs to no particular officer's run.
    Phase 3 introduces `POST /sessions/`, which will create a *new* session
    per officer-initiated run with `health_officer` set to the caller.

    `village` is intentionally denormalized here even though it is always
    reachable via `scenario.village` — Phase 1 ADR §11: fast, explicit,
    same-row authorization without a join.
    """

    class Status(models.TextChoices):
        NOT_STARTED = "NOT_STARTED", "Not started"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        COMPLETED = "COMPLETED", "Completed"

    scenario = models.ForeignKey(
        SimulationScenario, on_delete=models.CASCADE, related_name="sessions"
    )
    health_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="simulation_sessions",
        help_text="Null for a seed-created template session (Phase 2). Set "
        "to the initiating officer from Phase 3 onward.",
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.NOT_STARTED
    )
    replay_position = models.PositiveSmallIntegerField(
        default=0,
        help_text="Which week the replay/advance cursor is on. Unused until "
        "Phase 3/7.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["village"]),
            models.Index(fields=["status"]),
            models.Index(fields=["scenario"]),
        ]

    def __str__(self) -> str:
        return f"Session for {self.scenario.name} [{self.village.code}] ({self.status})"


def get_template_session(scenario: "SimulationScenario") -> "SimulationSession | None":
    """The seed-created, unexecuted session holding a scenario's canonical
    timeline (`health_officer=None`, Phase 2) — every real, officer-owned
    session reads its weeks from here. Lives at module level in `models.py`
    (the one layer every other simulation module can safely import from)
    rather than only as `simulation.services.SimulationEngine
    ._template_session` — Phase 6's `simulation/intelligence.py` and
    `simulation/safety/engine.py` both need this same lookup, and importing
    `SimulationEngine` from either would create
    `services -> safety -> intelligence -> services` and
    `services -> safety -> services` import cycles (`services.py` needs
    `SafetyEngine`, `SafetyEngine`/`intelligence.py` do not need anything
    else from `services.py`). `SimulationEngine._template_session` still
    exists and is still what `start()`/`advance()` call — it is now a thin
    wrapper around this function that adds the session-lifecycle-specific
    `SimulationSessionNotRunning` error, which only makes sense in that
    context.
    """

    return scenario.sessions.filter(health_officer__isnull=True).order_by("id").first()


class SimulationEvent(SimulationVillageScoped):
    """One synthetic reporting week within a session.

    Created and populated in Phase 2 by the seed command, for the three
    required scenarios (Emerging Signal, Stable Community, Missing Data).
    Read/processed starting Phase 3.

    `source_signals` JSON contract (documented per the Phase 2 task's §12
    instruction — Phase 3 must be able to read this without a schema
    rewrite):

        {
          "categories": {"FEVER": 8, "RESPIRATORY": 3, "HEADACHE": 2},
          "status_label": "SIGNAL_DETECTED"
        }

    - `categories`: reported-case counts for this week, keyed by an
      uppercase category/symptom label. Keys reuse the existing project's
      `SignalCategory` vocabulary where one exists (e.g. "FEVER",
      "RESPIRATORY"); a label with no real `SignalCategory` counterpart
      (e.g. "HEADACHE", used only as an illustrative worker-assessment
      symptom) is a simulation-only label and must not be presented as a
      real community-report category.
    - `status_label`: a plain-language narrative marker for this week
      (`NORMAL` / `STABLE` / `INCREASING` / `SIGNAL_DETECTED`, ...). This is
      seed-authored scenario narration only — it is NOT computed by any
      signal-analysis logic. Phase 3+ trend/anomaly computation is expected
      to derive its own verdict from `SimulationSourceSignal` rows rather
      than trust this label as ground truth.

    This JSON is a convenience, denormalized *summary* of the week. The
    authoritative, structurally distinction-preserving record of what was
    and was not reported — the "missing ≠ zero" requirement — lives in the
    child `SimulationSourceSignal` rows, never in this JSON blob alone.
    """

    session = models.ForeignKey(
        SimulationSession, on_delete=models.CASCADE, related_name="events"
    )
    week_number = models.PositiveSmallIntegerField()
    source_signals = models.JSONField(
        default=dict,
        blank=True,
        help_text="Denormalized weekly category summary — see model docstring "
        "for the JSON contract. Not the source of truth for missing-vs-zero; "
        "see SimulationSourceSignal for that.",
    )
    is_synthetic = models.BooleanField(
        default=True,
        help_text="Always True for a seeded scenario. Exists as a real field "
        "(not assumed) because a future Replay scenario (Phase 7) may carry "
        "genuine historical data through the same schema.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["session", "week_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "week_number"],
                name="unique_simulation_event_week_per_session",
            ),
        ]
        indexes = [
            models.Index(fields=["session", "week_number"]),
        ]

    def __str__(self) -> str:
        return f"{self.session} — week {self.week_number}"


class SimulationSourceSignal(SimulationVillageScoped):
    """One source's reported (or not-reported) value for one simulated week.

    Created and populated in Phase 2 by the seed command. This is the
    authoritative record for the "missing ≠ zero" invariant: `reported=True`
    with `value=0` (a genuine report of zero cases) is a structurally
    different row from `reported=False` (no report received at all, `value`
    left `None`). Nothing here ever silently substitutes zero for a missing
    report — mirrors `community.CommunitySignal.is_reported` /
    `alerts.AlertEvidence` exactly, under the field name the Phase 2 task
    specifies (`reported`, not `is_reported`).

    `source_type` reuses the existing `core.constants.SourceKind` choices
    (`CHW`, `PHC`, `PHARMACY`, `SCHOOL`, `WEATHER`, `LAB`,
    `RURALCARE_AGGREGATE`) — no new source vocabulary is invented. Every one
    of these is synthetic simulation input, regardless of whether the same
    source kind has a genuine, worker-originated counterpart in the
    operational system (CHW does; the rest do not — see the Phase 1 audit
    §7/§9 and the Phase 2 report's synthetic-source table).
    """

    event = models.ForeignKey(
        SimulationEvent,
        on_delete=models.CASCADE,
        # Not "source_signals" — that name is already `SimulationEvent`'s own
        # JSON summary field (see its docstring for the contract). This is
        # the per-source child ROW set, deliberately named differently.
        related_name="per_source_signals",
    )
    source_type = models.CharField(max_length=32, choices=SourceKind.choices)
    value = models.FloatField(
        null=True,
        blank=True,
        help_text="Null when reported=False. Never coerced to 0 for a "
        "missing report.",
    )
    reported = models.BooleanField(
        default=True,
        help_text="False means no report was received this week for this "
        "source — structurally distinct from a genuine 0.",
    )

    class Meta:
        ordering = ["event", "source_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "source_type"],
                name="unique_simulation_source_signal_per_event",
            ),
            models.CheckConstraint(
                check=(
                    models.Q(reported=True, value__isnull=False)
                    | models.Q(reported=False, value__isnull=True)
                ),
                name="simulation_source_signal_missing_is_not_zero",
            ),
        ]
        indexes = [
            models.Index(fields=["event", "source_type"]),
        ]

    def __str__(self) -> str:
        shown = "not reported" if not self.reported else self.value
        return f"{self.source_type} week {self.event.week_number} = {shown}"


class SimulationAgentRun(SimulationVillageScoped):
    """One simulated agent-pipeline stage invocation — created in Phase 2 as
    schema only, first populated in Phase 4 by
    `simulation.orchestrator.MultiAgentOrchestrator`.

    Field shape deliberately mirrors the operational `alerts.AgentRun`
    (`agent_name`, `status`, `input`/`output` as JSON, timing — including a
    stored `duration_ms`, not one computed at read time) so a future
    `AgentTrace`-style UI render call can accept either shape with minimal
    adaptation.

    `Status` was widened in Phase 4 from the original Phase 2 placeholder
    (`PENDING`/`OK`/`FAILED`) to the four values the Phase 4 pipeline
    actually produces (`WAITING`/`PROCESSING`/`COMPLETE`/`FAILED`). Safe to
    change without a data-migration concern: no row of this model existed
    before Phase 4 — Phase 2/3 never invoked any agent — so there was no
    live data using the old values.

    This output JSON shape is frozen after Phase 4: Phase 5 (Intelligence
    View) and Phase 6 (real Safety Engine) read it directly.
    """

    class Status(models.TextChoices):
        WAITING = "WAITING", "Waiting"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETE = "COMPLETE", "Complete"
        FAILED = "FAILED", "Failed"

    session = models.ForeignKey(
        SimulationSession, on_delete=models.CASCADE, related_name="agent_runs"
    )
    agent_name = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.WAITING
    )
    input = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
    duration_ms = models.FloatField(
        null=True,
        blank=True,
        help_text="Null for a stage that has not run (WAITING) or could not "
        "be timed.",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["session", "started_at"]
        indexes = [
            models.Index(fields=["session"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.agent_name} ({self.status}) — {self.session}"


class SafetyGateResult(models.TextChoices):
    """The simulation Safety Engine's own three-value gate vocabulary
    (Phase 6 task §6/§8) — deliberately NOT the operational
    `backend.safety.engine`'s PASS/DOWNGRADE/BLOCK verdict (see
    `simulation/safety/engine.py`'s module docstring for why the two are
    kept independent rather than unified). Shared by both
    `SimulationSafetyCheck.result` (one row per rule) and
    `SimulationResult.gate_result` (the aggregate), so the two can never
    drift into two different spellings of the same three values.
    """

    PASS = "PASS", "Pass"
    BLOCK = "BLOCK", "Block"
    INSUFFICIENT = "INSUFFICIENT", "Insufficient"


class EvidenceStrength(models.TextChoices):
    """WEAK / MODERATE / STRONG — Phase 5's preliminary evidence-strength
    vocabulary (`simulation.intelligence._evidence_strength`), reused as-is
    here so `SimulationResult.evidence_strength` can persist Phase 6's
    *finalized* (downgrade-only) value under the same three names Phase 5
    already computes on read. Never a percentage or "confidence" score.
    """

    WEAK = "WEAK", "Weak"
    MODERATE = "MODERATE", "Moderate"
    STRONG = "STRONG", "Strong"


class SimulationSafetyCheck(SimulationVillageScoped):
    """One deterministic Safety Engine rule result — created in Phase 2,
    first populated in Phase 6 by `simulation.safety.engine.SafetyEngine`.

    `rule_name`/`result`/`reason` mirror the shape of the operational
    `SafetyResult`'s per-rule `RuleResult` (`backend/safety/types.py`), as
    originally documented — no rename was needed to activate this model.
    `result` gained an explicit `choices=SafetyGateResult.choices` in
    Phase 6 (a safe, non-breaking addition: this field has held no data
    since Phase 2, so widening it from a bare CharField to one with
    choices changes no existing row).
    """

    session = models.ForeignKey(
        SimulationSession, on_delete=models.CASCADE, related_name="safety_checks"
    )
    rule_name = models.CharField(max_length=64, blank=True)
    result = models.CharField(
        max_length=16, choices=SafetyGateResult.choices, blank=True
    )
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["session", "created_at"]
        indexes = [
            models.Index(fields=["session"]),
        ]

    def __str__(self) -> str:
        return f"{self.rule_name or 'unset'} — {self.session}"


class SimulationResult(SimulationVillageScoped):
    """One session's finalized safety/evidence outcome for one advanced
    week — created in Phase 2 as `evidence_strength: FloatField`
    (documented as unused: "Nothing computes evidence_strength in this
    phase"), first populated in Phase 6.

    Phase 6 changes, both safe because no row of this model has ever held
    real data (confirmed by grep — Phase 2-5 never created one):
      - `evidence_strength` is now a `CharField` over `EvidenceStrength`
        (WEAK/MODERATE/STRONG) instead of a `FloatField` — the field was
        always going to need to hold Phase 5's categorical vocabulary, not
        an arbitrary float/percentage/"confidence" score, so this is a
        type *correction* rather than a redesign.
      - `gate_result` is a genuinely new field: no equivalent existed
        anywhere in the schema to hold the Safety Engine's PASS/BLOCK/
        INSUFFICIENT aggregate, so activating "use an existing field" was
        not possible for this value.

    `investigation_priority` still reuses the existing `Alert.Severity`
    choices (LOW/MODERATE/HIGH) rather than inventing a parallel scale.
    Unpopulated through Phase 6-8; Phase 9 (`simulation.services
    ._investigation_priority`) finally computes it — deterministically,
    from this same row's own `evidence_strength`/`gate_result`, at the
    exact moment `_persist_safety_evaluation` writes it — for the
    Investigation Notebook's Overview to read, never a new "confidence"
    score of its own.
    """

    session = models.ForeignKey(
        SimulationSession, on_delete=models.CASCADE, related_name="results"
    )
    evidence_strength = models.CharField(
        max_length=16, choices=EvidenceStrength.choices, blank=True, default=""
    )
    gate_result = models.CharField(
        max_length=16, choices=SafetyGateResult.choices, blank=True, default=""
    )
    investigation_priority = models.CharField(
        max_length=16, choices=Alert.Severity.choices, blank=True, default=""
    )
    is_what_if = models.BooleanField(
        default=False,
        help_text="True for a hypothetical (Phase 7 What-If) result rather "
        "than a straightforward scenario run.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["session", "-created_at"]
        indexes = [
            models.Index(fields=["session"]),
        ]

    def __str__(self) -> str:
        return (
            f"Result for {self.session} (gate={self.gate_result or '—'}, "
            f"evidence={self.evidence_strength or '—'})"
        )


class InvestigationStatus(models.TextChoices):
    """Phase 9 lifecycle for one `SimulationInvestigation` row — the exact
    same "TextChoices with a real, always-populated default" shape every
    other status field in this file already uses
    (`SimulationSession.Status`, `SimulationAgentRun.Status`).

    `NOT_STARTED` is never actually observed on a persisted row, by design:
    mirroring `SimulationSession` (a seed-created *template* session stays
    `NOT_STARTED` forever; a real, officer-created one starts at
    `IN_PROGRESS`), `SimulationInvestigationView`'s get-or-create only ever
    creates a row already at `IN_PROGRESS` — the row's mere existence IS
    the "officer opened this investigation" event. The choice still exists
    so the enum is a complete, self-documenting state machine.

    `READY_FOR_DECISION` is set automatically once every checklist item
    the session actually has is checked (`simulation.investigation
    .compute_progress`) — never claimed by the frontend. `DECISION_RECORDED`
    is set the moment `POST .../decision/` succeeds. `COMPLETED` is defined
    for schema completeness (task §25/§61) but no Phase 9 code path
    transitions into it automatically — recording a decision is already the
    terminal, human-owned action this phase requires.
    """

    NOT_STARTED = "NOT_STARTED", "Not started"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    READY_FOR_DECISION = "READY_FOR_DECISION", "Ready for decision"
    DECISION_RECORDED = "DECISION_RECORDED", "Decision recorded"
    COMPLETED = "COMPLETED", "Completed"


class InvestigationDecision(models.TextChoices):
    """Phase 9's own decision vocabulary — deliberately NOT a reuse of
    `Feedback.Outcome` (VALID_SIGNAL/FALSE_ALERT/RESOLVED), even though an
    earlier phase's docstring once said `decision` would reuse it: that
    vocabulary is for POST-HOC alert feedback (was this alert useful?),
    a different question from "what should the officer do next during an
    active investigation?" (task §20/§21). Safe to change here — no row of
    this model has ever held data (confirmed: `decision` has been
    schema-only since Phase 2), so this is the same "type/vocabulary
    correction before first use" already applied to
    `SimulationResult.evidence_strength`/`gate_result` in Phase 6. None of
    these is a medical or treatment recommendation — every option is a
    next *investigative* step, chosen by the officer, never generated
    autonomously (task §21: "the system must never silently select the
    officer's decision").
    """

    CONTINUE_MONITORING = "CONTINUE_MONITORING", "Continue monitoring"
    REQUEST_MORE_DATA = "REQUEST_MORE_DATA", "Request more data"
    VERIFY_WITH_PHC = "VERIFY_WITH_PHC", "Verify with PHC"
    CONDUCT_FIELD_VERIFICATION = "CONDUCT_FIELD_VERIFICATION", "Conduct field verification"
    REQUEST_LABORATORY_VERIFICATION = (
        "REQUEST_LABORATORY_VERIFICATION",
        "Request laboratory verification",
    )
    ESCALATE_FOR_HUMAN_REVIEW = "ESCALATE_FOR_HUMAN_REVIEW", "Escalate for human review"
    CLOSE_AS_INSUFFICIENT_EVIDENCE = (
        "CLOSE_AS_INSUFFICIENT_EVIDENCE",
        "Close as insufficient evidence",
    )


class SimulationInvestigation(SimulationVillageScoped):
    """One officer's investigation workspace for a session — created in
    Phase 2 as schema only, first populated (workflow implemented) in
    Phase 9. One row per session (get-or-create on first open, task §50:
    "do not add redundant models") — it represents the session's ONE
    ongoing investigation of its current signal, not a per-week record;
    "current week" is always read live from `session.replay_position`,
    exactly like `.../intelligence/` and `.../safety/` already do, never
    frozen onto this row.

    `checklist`/`observations`/`activity_history` are the "lightweight JSON
    field" the task explicitly sanctions (§26/§50) rather than three more
    models: `checklist` is `{item_key: bool}`, `observations` is a list of
    `{id, week, source, category, notes, created_at}` dicts (Phase 9's own
    "simulated field observation" concept — never an operational record),
    `activity_history` is a list of `{timestamp, event_type, actor}` dicts
    appended by the backend at key moments, never client-supplied wholesale
    (task §26/§41: auditable, server-derived).

    `decided_by` is deliberately its own FK, not assumed to be
    `session.health_officer`: this codebase's existing village-scope rule
    already allows any officer scoped to a village to act on that village's
    sessions (`officer_may_access_village`), so the officer who actually
    RECORDS a decision is derived from `request.user` at write time — never
    trusted from client input (task §41: "never allow the frontend to
    submit another officer ID").
    """

    session = models.ForeignKey(
        SimulationSession, on_delete=models.CASCADE, related_name="investigations"
    )
    status = models.CharField(
        max_length=24,
        choices=InvestigationStatus.choices,
        default=InvestigationStatus.NOT_STARTED,
    )
    officer_notes = models.TextField(blank=True, default="")
    checklist = models.JSONField(default=dict, blank=True)
    observations = models.JSONField(default=list, blank=True)
    activity_history = models.JSONField(default=list, blank=True)
    decision = models.CharField(
        max_length=32, choices=InvestigationDecision.choices, blank=True, default=""
    )
    decision_reason = models.TextField(blank=True, default="")
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="simulation_investigation_decisions",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    is_simulation = models.BooleanField(default=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["session", "-created_at"]
        indexes = [
            models.Index(fields=["session"]),
        ]
        constraints = [
            # One investigation per session (task §50: "do not add
            # redundant models" — this is the DB-level guarantee that
            # get-or-create semantics in the view can actually rely on,
            # rather than merely a convention nothing enforces).
            models.UniqueConstraint(fields=["session"], name="unique_simulation_investigation_per_session"),
        ]

    def __str__(self) -> str:
        return f"Investigation for {self.session} (decision={self.decision or 'pending'})"


class FeedbackUsefulness(models.TextChoices):
    """Phase 10's officer-experience vocabulary (task §5/§6: "feedback
    describes the OFFICER'S EXPERIENCE... does NOT automatically mean the
    signal was medically correct"). Deliberately its own choices, not a
    reuse of `InvestigationDecision` or the operational `alerts.Feedback
    .Outcome` — a different question again (how USEFUL was this, not what
    should happen next, not whether the alert was medically valid)."""

    VERY_USEFUL = "VERY_USEFUL", "Very useful"
    USEFUL = "USEFUL", "Useful"
    PARTIALLY_USEFUL = "PARTIALLY_USEFUL", "Partially useful"
    NOT_USEFUL = "NOT_USEFUL", "Not useful"


class FeedbackEvidenceSufficiency(models.TextChoices):
    SUFFICIENT = "SUFFICIENT", "Sufficient"
    PARTIALLY_SUFFICIENT = "PARTIALLY_SUFFICIENT", "Partially sufficient"
    INSUFFICIENT = "INSUFFICIENT", "Insufficient"


class FeedbackYesPartiallyNo(models.TextChoices):
    YES = "YES", "Yes"
    PARTIALLY = "PARTIALLY", "Partially"
    NO = "NO", "No"


class FeedbackYesNo(models.TextChoices):
    YES = "YES", "Yes"
    NO = "NO", "No"


class SimulationFeedback(SimulationVillageScoped):
    """Phase 10 — one officer-experience feedback record per investigation
    (task §7/§8). `investigation` is a plain `ForeignKey` with an explicit
    `UniqueConstraint` below, not `OneToOneField` — the same "declare as a
    FK, enforce uniqueness via a named constraint" shape
    `SimulationInvestigation.session` already established one phase ago,
    kept consistent here rather than introducing a second one-to-one idiom.
    `session` is denormalized from `investigation.session` (Phase 1 ADR:
    every simulation model carries its own explicit village/session
    reference for a same-row authorization check, never a join).

    This is an EVALUATION layer only — nothing here is read by
    `SafetyEngine`, `MultiAgentOrchestrator`, or `SimulationEngine`, and
    nothing in this model can change `SimulationResult.evidence_strength`/
    `gate_result` or `SimulationInvestigation.decision` (task §19/§20/§41-
    §43: feedback must never modify safety, evidence, or the officer's own
    decision — it is recorded and read back, nothing more).
    """

    investigation = models.ForeignKey(
        SimulationInvestigation, on_delete=models.CASCADE, related_name="feedback_entries"
    )
    session = models.ForeignKey(
        SimulationSession, on_delete=models.CASCADE, related_name="feedback_entries"
    )
    officer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="simulation_feedback_entries",
    )
    usefulness = models.CharField(
        max_length=24, choices=FeedbackUsefulness.choices, blank=True, default=""
    )
    evidence_sufficiency = models.CharField(
        max_length=24, choices=FeedbackEvidenceSufficiency.choices, blank=True, default=""
    )
    recommendation_helpful = models.CharField(
        max_length=16, choices=FeedbackYesPartiallyNo.choices, blank=True, default=""
    )
    additional_verification_required = models.CharField(
        max_length=8, choices=FeedbackYesNo.choices, blank=True, default=""
    )
    comment = models.TextField(blank=True, default="")
    is_simulation = models.BooleanField(default=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["investigation", "-created_at"]
        indexes = [
            models.Index(fields=["session"]),
            models.Index(fields=["investigation"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["investigation"], name="unique_simulation_feedback_per_investigation"
            ),
        ]

    def __str__(self) -> str:
        return f"Feedback for {self.investigation} (usefulness={self.usefulness or 'unset'})"
