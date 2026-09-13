"""Phase 6 — the nine deterministic Safety Engine rules.

Every rule below has the exact shape the task specifies: a pure function
taking one `SafetyContext` and returning one `SafetyRuleResult` — a stable
rule name, a result in `{"PASS", "BLOCK", "INSUFFICIENT"}`
(`simulation.models.SafetyGateResult`), and a plain-language reason.
Nothing here is randomised, nothing here depends on wall-clock time beyond
what is already frozen into the session/event rows, and nothing here
imports an LLM client — see `test_simulation_safety.py`'s static import
scan, which fails the whole suite if one ever appears under this package.

Rules 5 and 6 deliberately do NOT recompute correlation or completeness —
they read `SafetyContext.intelligence`, which is exactly
`simulation.intelligence.build_intelligence(session)`'s own output (the
same Phase 4 correlation / Phase 5 data-quality Health Officers already
see in the Intelligence View). A second, competing algorithm here would be
exactly the "duplicate calculation" the whole simulator has avoided since
Phase 5.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from simulation.models import SafetyGateResult
from simulation.orchestrator import (
    RELATIONSHIP_CONFLICTING,
    RELATIONSHIP_INSUFFICIENT,
    RELATIONSHIP_SUPPORTING,
    TREND_INCREASING,
    TREND_SIGNAL_DETECTED,
)
from users.scoping import scoped_village_id

# ---------------------------------------------------------------------------
# Stable rule names, in the one fixed evaluation order (task §7). This tuple
# — not a dict, not frontend input, not anything an LLM could reorder — is
# the single source of truth `SafetyEngine.RULES` iterates.
# ---------------------------------------------------------------------------
RULE_VILLAGE_SCOPE_VERIFIED = "village_scope_verified"
RULE_REPORTING_PERIOD_VALIDATED = "reporting_period_validated"
RULE_DUPLICATE_RECORDS_CHECKED = "duplicate_records_checked"
RULE_SUFFICIENT_HISTORICAL_WINDOW = "sufficient_historical_window"
RULE_SOURCE_RELATIONSHIPS_EVALUATED = "source_relationships_evaluated"
RULE_MISSING_DATA_ASSESSED = "missing_data_assessed"
RULE_NO_INDIVIDUAL_DIAGNOSIS_GENERATED = "no_individual_diagnosis_generated"
RULE_NO_AUTONOMOUS_OUTBREAK_DECLARATION = "no_autonomous_outbreak_declaration"
RULE_HUMAN_REVIEW_REQUIRED = "human_review_required"

#: Rule 4 — minimum revealed reporting weeks required before an escalating
#: (INCREASING/SIGNAL_DETECTED) trend may pass safety. A single named
#: constant, read from exactly one place (this module), never re-typed
#: elsewhere — task §6 Rule 4's explicit requirement. 3 was chosen because
#: every real seeded scenario is a 4-week timeline, and the Emerging Signal
#: scenario's own trend first reaches INCREASING at week 3 — the earliest
#: point an escalating signal genuinely exists to evaluate.
MIN_HISTORICAL_WEEKS = 3

#: Rule 6 — minimum overall reporting completeness (from Phase 5's own
#: `data_quality.completeness_pct`) required before safety may PASS,
#: regardless of what the Evidence stage otherwise concluded. Set above the
#: real Missing Data scenario's own steady-state figure (75% once PHC stops
#: reporting) so that scenario deterministically demonstrates this rule,
#: while the other two real scenarios (100% completeness throughout) are
#: unaffected.
MIN_COMPLETENESS_PCT = 80

#: Rule 7 — deterministic, conservative individual-diagnosis phrase list.
#: Overlaps by design with `core.constants.PROHIBITED_OUTPUT_TERMS` and
#: `backend.safety.rules.PROHIBITED_TERMS` (two existing, and not
#: consistent with each other today), but is intentionally its OWN list
#: rather than an import from either: this package must stay physically
#: separate and independently auditable (task §4), and neither existing
#: list is actually a stable, shared, cross-app contract today — one has
#: zero consumers anywhere in the codebase, the other is scoped to the
#: individual-level RuralCare narrative rule. "the patient has" (without
#: requiring a specific disease name, unlike the narrower existing lists)
#: is safe to match unqualified here specifically because this simulator
#: is a population-level signal system — no genuine simulation narrative
#: anywhere in Phase 4/5 ever refers to "the patient" at all.
INDIVIDUAL_DIAGNOSIS_PHRASES = (
    "diagnosis is",
    "diagnosed with",
    "the patient has",
    "confirmed case of",
    "patient is positive for",
)

#: Rule 8 — deterministic outbreak-declaration phrase list. Same
#: independent-list rationale as `INDIVIDUAL_DIAGNOSIS_PHRASES` above.
#: "outbreak detected" is included explicitly because it is the literal
#: phrase this phase's own required negative test injects, and neither
#: existing codebase list (`core.constants.PROHIBITED_OUTPUT_TERMS` nor
#: `backend.safety.rules.PROHIBITED_TERMS`) actually contains it.
OUTBREAK_DECLARATION_PHRASES = (
    "outbreak confirmed",
    "confirmed outbreak",
    "outbreak declared",
    "outbreak detected",
    "declare an outbreak",
    "declaring an outbreak",
    "we declare",
    "epidemic confirmed",
)

_VALID_RELATIONS = {RELATIONSHIP_SUPPORTING, RELATIONSHIP_CONFLICTING, RELATIONSHIP_INSUFFICIENT}
_EXPECTED_EVIDENCE_KEYS = {"primary_signal", "trend", "source_relationships"}


@dataclass(frozen=True)
class SafetyContext:
    """Everything a rule might need, bundled once per evaluation so every
    rule function stays a plain `(ctx) -> SafetyRuleResult` — independently
    callable and testable without constructing a live HTTP request or a
    full orchestrator run (task §5)."""

    session: Any  # SimulationSession
    officer: Any  # the authenticated User the evaluation is being run for
    template: Any  # SimulationSession — the scenario's seed-created timeline
    revealed_events: list = field(default_factory=list)  # SimulationEvent, week order
    intelligence: dict = field(default_factory=dict)  # simulation.intelligence.build_intelligence(session)
    ingestion_output: dict = field(default_factory=dict)
    signal_output: dict = field(default_factory=dict)
    correlation_output: dict = field(default_factory=dict)
    evidence_output: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SafetyRuleResult:
    rule_name: str
    result: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"rule": self.rule_name, "result": self.result, "reason": self.reason}


def _narrative_text(ctx: SafetyContext) -> str:
    """Every free-text explanation an upstream stage produced for the
    *current* week — the one place LLM-phrased content can enter the
    pipeline (Phase 4's Signal Analysis explanation, when
    `explanation_used_llm` is true) — lower-cased once for substring
    matching, mirroring the existing operational
    `backend.safety.rules.rule_6_no_automatic_outbreak_declaration`'s own
    case-insensitive substring approach."""

    parts = []
    for output in (ctx.signal_output, ctx.evidence_output):
        if isinstance(output, dict):
            explanation = output.get("explanation")
            if isinstance(explanation, str):
                parts.append(explanation)
    return " ".join(parts).lower()


# ---------------------------------------------------------------------------
# Rule 1
# ---------------------------------------------------------------------------
def rule_1_village_scope_verified(ctx: SafetyContext) -> SafetyRuleResult:
    """Third independent village check (Phase 2's permission class and
    Phase 3's `SimulationEngine` service-layer check are the other two) —
    deliberately re-derived from the officer's own scoped village rather
    than trusted from any upstream layer, per task §6 Rule 1."""

    officer_village_id = scoped_village_id(ctx.officer)
    if officer_village_id is not None and officer_village_id != ctx.session.village_id:
        return SafetyRuleResult(
            RULE_VILLAGE_SCOPE_VERIFIED,
            SafetyGateResult.BLOCK,
            "Session village does not match the authenticated officer's village.",
        )
    return SafetyRuleResult(
        RULE_VILLAGE_SCOPE_VERIFIED,
        SafetyGateResult.PASS,
        "Session village matches the authenticated officer's village.",
    )


# ---------------------------------------------------------------------------
# Rule 2
# ---------------------------------------------------------------------------
def rule_2_reporting_period_validated(ctx: SafetyContext) -> SafetyRuleResult:
    position = ctx.session.replay_position

    if position <= 0:
        return SafetyRuleResult(
            RULE_REPORTING_PERIOD_VALIDATED,
            SafetyGateResult.BLOCK,
            "No reporting period has been established for this session yet.",
        )

    all_weeks = sorted(ctx.template.events.values_list("week_number", flat=True))
    if not all_weeks:
        return SafetyRuleResult(
            RULE_REPORTING_PERIOD_VALIDATED,
            SafetyGateResult.BLOCK,
            "This scenario has no seeded reporting weeks to validate against.",
        )

    if position not in all_weeks:
        # Covers both "not a real week at all" and "beyond the scenario's
        # seeded/available data" — if `position` exceeded the maximum
        # seeded week it could not be a member of `all_weeks` either, so
        # there is only one branch, not two, for "not a valid week".
        return SafetyRuleResult(
            RULE_REPORTING_PERIOD_VALIDATED,
            SafetyGateResult.BLOCK,
            f"Week {position} does not correspond to any recorded reporting "
            "period — it may be beyond the scenario's available data or not "
            "a real seeded week.",
        )

    expected = set(range(1, position + 1))
    revealed = {week for week in all_weeks if week <= position}
    if revealed != expected:
        return SafetyRuleResult(
            RULE_REPORTING_PERIOD_VALIDATED,
            SafetyGateResult.BLOCK,
            "The reporting period history has gaps and cannot be reliably validated.",
        )

    return SafetyRuleResult(
        RULE_REPORTING_PERIOD_VALIDATED,
        SafetyGateResult.PASS,
        f"Reporting period (week {position}) is valid.",
    )


# ---------------------------------------------------------------------------
# Rule 3
# ---------------------------------------------------------------------------
def rule_3_duplicate_records_checked(ctx: SafetyContext) -> SafetyRuleResult:
    """The schema already makes an exact-key duplicate structurally
    impossible to persist — `SimulationEvent` has a
    `unique_simulation_event_week_per_session` constraint and
    `SimulationSourceSignal` has `unique_simulation_source_signal_per_event`
    — so checking those again here would always trivially pass and could
    never be tested with a real duplicate fixture. The one duplicate class
    the schema does NOT prevent, and that this rule actually checks, is
    duplicate *pipeline processing*: more than one `ingestion`
    `SimulationAgentRun` claiming the same reporting week for this
    session (e.g. a retried/duplicated `advance()` call)."""

    week_counts: Counter[int] = Counter()
    for run in ctx.session.agent_runs.filter(agent_name="ingestion"):
        output = run.output if isinstance(run.output, dict) else {}
        week = output.get("week")
        if week is not None:
            week_counts[week] += 1

    duplicated_weeks = sorted(week for week, count in week_counts.items() if count > 1)
    if duplicated_weeks:
        weeks_text = ", ".join(str(week) for week in duplicated_weeks)
        return SafetyRuleResult(
            RULE_DUPLICATE_RECORDS_CHECKED,
            SafetyGateResult.BLOCK,
            f"Duplicate pipeline processing detected for week(s) {weeks_text} — "
            "more than one ingestion record exists for the same reporting week.",
        )
    return SafetyRuleResult(
        RULE_DUPLICATE_RECORDS_CHECKED,
        SafetyGateResult.PASS,
        "No duplicate simulation records detected: each reporting week has been "
        "ingested exactly once, and the schema's own uniqueness constraints "
        "prevent duplicate events or source signals at the database level.",
    )


# ---------------------------------------------------------------------------
# Rule 4
# ---------------------------------------------------------------------------
def rule_4_sufficient_historical_window(ctx: SafetyContext) -> SafetyRuleResult:
    revealed_count = len(ctx.revealed_events)
    trend = ctx.signal_output.get("trend") if isinstance(ctx.signal_output, dict) else None
    is_escalating = trend in (TREND_INCREASING, TREND_SIGNAL_DETECTED)

    if is_escalating and revealed_count < MIN_HISTORICAL_WEEKS:
        return SafetyRuleResult(
            RULE_SUFFICIENT_HISTORICAL_WINDOW,
            SafetyGateResult.INSUFFICIENT,
            f"Only {revealed_count} reporting week(s) are available; additional "
            "historical data is required before escalation.",
        )
    return SafetyRuleResult(
        RULE_SUFFICIENT_HISTORICAL_WINDOW,
        SafetyGateResult.PASS,
        f"{revealed_count} reporting week(s) available.",
    )


# ---------------------------------------------------------------------------
# Rule 5
# ---------------------------------------------------------------------------
def rule_5_source_relationships_evaluated(ctx: SafetyContext) -> SafetyRuleResult:
    evidence_output = ctx.evidence_output

    if evidence_output and not isinstance(evidence_output, dict):
        return SafetyRuleResult(
            RULE_SOURCE_RELATIONSHIPS_EVALUATED,
            SafetyGateResult.INSUFFICIENT,
            "Upstream evidence output is not a structured record and cannot be "
            "safety-evaluated.",
        )

    if isinstance(evidence_output, dict) and evidence_output:
        if not _EXPECTED_EVIDENCE_KEYS <= set(evidence_output.keys()):
            return SafetyRuleResult(
                RULE_SOURCE_RELATIONSHIPS_EVALUATED,
                SafetyGateResult.INSUFFICIENT,
                "Upstream evidence output is missing expected fields and cannot "
                "be safety-evaluated.",
            )
        relationships = evidence_output.get("source_relationships")
        if not isinstance(relationships, list):
            return SafetyRuleResult(
                RULE_SOURCE_RELATIONSHIPS_EVALUATED,
                SafetyGateResult.INSUFFICIENT,
                "Upstream evidence output's source relationships are malformed.",
            )

    constellation = ctx.intelligence.get("constellation", [])
    if not constellation:
        return SafetyRuleResult(
            RULE_SOURCE_RELATIONSHIPS_EVALUATED,
            SafetyGateResult.INSUFFICIENT,
            "Source relationships have not yet been evaluated for this session.",
        )
    if any(entry.get("relation") not in _VALID_RELATIONS for entry in constellation):
        return SafetyRuleResult(
            RULE_SOURCE_RELATIONSHIPS_EVALUATED,
            SafetyGateResult.INSUFFICIENT,
            "Source relationship data is malformed and cannot be safety-evaluated.",
        )

    # A conflicting source is not, by itself, unsafe — it means the signal
    # needs cautious human interpretation, which Rule 9 already guarantees
    # unconditionally. Manufacturing a BLOCK here merely because evidence
    # disagrees would be a false failure (task §6 Rule 5).
    return SafetyRuleResult(
        RULE_SOURCE_RELATIONSHIPS_EVALUATED,
        SafetyGateResult.PASS,
        f"Source relationships evaluated across {len(constellation)} source(s).",
    )


# ---------------------------------------------------------------------------
# Rule 6
# ---------------------------------------------------------------------------
def rule_6_missing_data_assessed(ctx: SafetyContext) -> SafetyRuleResult:
    """Reuses Phase 5's own `data_quality.completeness_pct`
    (`reported_weeks / expected_weeks`, computed once in
    `simulation.intelligence.build_intelligence`) — never recomputed here.
    `reported=True, value=0` and `reported=False, value=None` are already
    kept structurally distinct at that layer; this rule only compares the
    resulting percentage against `MIN_COMPLETENESS_PCT`."""

    data_quality = ctx.intelligence.get("data_quality", {})
    completeness = data_quality.get("completeness_pct", 0)

    if completeness < MIN_COMPLETENESS_PCT:
        return SafetyRuleResult(
            RULE_MISSING_DATA_ASSESSED,
            SafetyGateResult.INSUFFICIENT,
            f"Reporting completeness is {completeness}%, below the "
            f"{MIN_COMPLETENESS_PCT}% required before escalation.",
        )
    return SafetyRuleResult(
        RULE_MISSING_DATA_ASSESSED,
        SafetyGateResult.PASS,
        f"Reporting completeness is {completeness}%, meeting the required threshold.",
    )


# ---------------------------------------------------------------------------
# Rule 7
# ---------------------------------------------------------------------------
def rule_7_no_individual_diagnosis_generated(ctx: SafetyContext) -> SafetyRuleResult:
    haystack = _narrative_text(ctx)
    matched = next((phrase for phrase in INDIVIDUAL_DIAGNOSIS_PHRASES if phrase in haystack), None)
    if matched:
        return SafetyRuleResult(
            RULE_NO_INDIVIDUAL_DIAGNOSIS_GENERATED,
            SafetyGateResult.BLOCK,
            f"Upstream narrative contains individual-diagnosis language "
            f"('{matched}'), which this system must never present as a conclusion.",
        )
    return SafetyRuleResult(
        RULE_NO_INDIVIDUAL_DIAGNOSIS_GENERATED,
        SafetyGateResult.PASS,
        "No individual-diagnosis language detected in upstream narrative text.",
    )


# ---------------------------------------------------------------------------
# Rule 8
# ---------------------------------------------------------------------------
def rule_8_no_autonomous_outbreak_declaration(ctx: SafetyContext) -> SafetyRuleResult:
    haystack = _narrative_text(ctx)
    matched = next((phrase for phrase in OUTBREAK_DECLARATION_PHRASES if phrase in haystack), None)
    if matched:
        return SafetyRuleResult(
            RULE_NO_AUTONOMOUS_OUTBREAK_DECLARATION,
            SafetyGateResult.BLOCK,
            f"Upstream narrative contains an autonomous outbreak-declaration "
            f"phrase ('{matched}'), which is never a permitted system output.",
        )
    return SafetyRuleResult(
        RULE_NO_AUTONOMOUS_OUTBREAK_DECLARATION,
        SafetyGateResult.PASS,
        "No outbreak-declaration language detected in upstream narrative text.",
    )


# ---------------------------------------------------------------------------
# Rule 9
# ---------------------------------------------------------------------------
def rule_9_human_review_required(ctx: SafetyContext) -> SafetyRuleResult:
    """Unconditional by design (task §6 Rule 9) — this is the one rule that
    can never itself produce anything other than PASS, because it is not
    gating a condition; it is asserting the standing invariant that no
    result from this engine, including a full PASS, ever means autonomous
    approval."""

    return SafetyRuleResult(
        RULE_HUMAN_REVIEW_REQUIRED,
        SafetyGateResult.PASS,
        "Human review is always required before any operational action is "
        "taken on this signal.",
    )


#: Fixed order (task §7) — the ONE place this order is declared.
RULES = (
    rule_1_village_scope_verified,
    rule_2_reporting_period_validated,
    rule_3_duplicate_records_checked,
    rule_4_sufficient_historical_window,
    rule_5_source_relationships_evaluated,
    rule_6_missing_data_assessed,
    rule_7_no_individual_diagnosis_generated,
    rule_8_no_autonomous_outbreak_declaration,
    rule_9_human_review_required,
)

RULE_ORDER = (
    RULE_VILLAGE_SCOPE_VERIFIED,
    RULE_REPORTING_PERIOD_VALIDATED,
    RULE_DUPLICATE_RECORDS_CHECKED,
    RULE_SUFFICIENT_HISTORICAL_WINDOW,
    RULE_SOURCE_RELATIONSHIPS_EVALUATED,
    RULE_MISSING_DATA_ASSESSED,
    RULE_NO_INDIVIDUAL_DIAGNOSIS_GENERATED,
    RULE_NO_AUTONOMOUS_OUTBREAK_DECLARATION,
    RULE_HUMAN_REVIEW_REQUIRED,
)
