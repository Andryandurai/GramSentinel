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

from alerts.models import Alert, Feedback
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
    """Schema for one simulated agent invocation — created in Phase 2,
    first populated in Phase 4.

    Field shape deliberately mirrors the operational `alerts.AgentRun`
    (`agent_name`, `status`, `input`/`output` as JSON, timing) so a future
    `AgentTrace` UI render call can accept either shape with minimal
    adaptation. No agent is invoked by anything in this file or in the
    Phase 2 seed command.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        OK = "OK", "OK"
        FAILED = "FAILED", "Failed"

    session = models.ForeignKey(
        SimulationSession, on_delete=models.CASCADE, related_name="agent_runs"
    )
    agent_name = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    input = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
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


class SimulationSafetyCheck(SimulationVillageScoped):
    """Schema for one simulated deterministic-safety-rule result — created
    in Phase 2, first populated in Phase 6.

    `rule_name`/`result`/`reason` mirror the shape of a `SafetyResult`'s
    per-rule `RuleResult` (`backend/safety/types.py`) so the real
    `SafetyEngine` output can be persisted here later with no field
    renaming. The deterministic Safety Engine itself is not called by
    anything in this file.
    """

    session = models.ForeignKey(
        SimulationSession, on_delete=models.CASCADE, related_name="safety_checks"
    )
    rule_name = models.CharField(max_length=64, blank=True)
    result = models.CharField(max_length=16, blank=True)
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
    """Schema for a simulated evidence/prioritisation outcome — created in
    Phase 2, first populated in Phase 5/7.

    `investigation_priority` reuses the existing `Alert.Severity` choices
    (LOW/MODERATE/HIGH) rather than inventing a parallel scale, matching
    Phase 1's "reuse existing vocabulary" guidance. Nothing computes
    `evidence_strength` in this phase.
    """

    session = models.ForeignKey(
        SimulationSession, on_delete=models.CASCADE, related_name="results"
    )
    evidence_strength = models.FloatField(null=True, blank=True)
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
        return f"Result for {self.session} (priority={self.investigation_priority or '—'})"


class SimulationInvestigation(SimulationVillageScoped):
    """Schema for a simulated officer decision — created in Phase 2, first
    populated (workflow implemented) in Phase 9.

    `decision` reuses the existing `Feedback.Outcome` choices
    (VALID_SIGNAL/FALSE_ALERT/RESOLVED). `is_simulation` defaults to True and
    exists purely so a simulated investigation is structurally
    self-identifying even though it already lives in a table physically
    separate from the operational `alerts.Investigation`/`alerts.Feedback` —
    belt-and-braces, matching the safety-boundary emphasis of this whole
    feature.
    """

    session = models.ForeignKey(
        SimulationSession, on_delete=models.CASCADE, related_name="investigations"
    )
    officer_notes = models.TextField(blank=True, default="")
    decision = models.CharField(
        max_length=24, choices=Feedback.Outcome.choices, blank=True, default=""
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    is_simulation = models.BooleanField(default=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["session", "-created_at"]
        indexes = [
            models.Index(fields=["session"]),
        ]

    def __str__(self) -> str:
        return f"Investigation for {self.session} (decision={self.decision or 'pending'})"
