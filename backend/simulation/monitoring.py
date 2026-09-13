"""Phase 10 — Intelligence Quality Monitoring.

Backend-aggregated, village-scoped metrics over ALREADY-PERSISTED
simulation data (task §33/§61: "metrics must be calculated on the
backend... do not fetch all raw records to the frontend"). Every number
here is either a straightforward Django ORM count/percentage of an
existing field, or — for the per-source relationship tally — a plain
count over the same relationship labels `simulation.orchestrator
._correlation` already produced. Nothing here is a new intelligence
score, a new correlation algorithm, or causal inference (task §16/§17/
§27: "do not create a new intelligence scoring system").

This module is READ-ONLY. It never writes to any model — Phase 10 is an
observability/evaluation loop, never an autonomous learning or tuning
loop (task §19/§20/§56): nothing here can change a safety rule, an
evidence-strength value, a threshold, or an officer's decision.

Isolation: every queryset here is scoped to ONE village (never aggregated
across villages — task §3/§31: "no cross-village monitoring... do not
implement district-level access now") and touches only the
`Simulation*` tables listed in the task's own §34 allowlist — never
`Patient`/`CommunityReport`/operational `Alert`/`Investigation`.

What-If isolation: every evidence/safety aggregate filters
`is_what_if=False` (task §40 — What-If's `transaction.atomic()` rollback
already prevents its rows from surviving in practice; this filter is the
same explicit, defensive rule Phase 7 itself established for this exact
field, applied here too rather than assumed). Replay is inherently
excluded already: it creates no rows at all, so there is nothing to
filter out.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Count

from .investigation import suggested_decision as compute_suggested_decision
from .intelligence import build_intelligence
from .models import (
    FeedbackEvidenceSufficiency,
    FeedbackYesNo,
    FeedbackYesPartiallyNo,
    FeedbackUsefulness,
    InvestigationDecision,
    SafetyGateResult,
    SimulationAgentRun,
    SimulationFeedback,
    SimulationInvestigation,
    SimulationResult,
    SimulationSession,
    SimulationSourceSignal,
)
from .safety import SafetyEngine

#: Below this many observations, a percentage is presented with
#: `limited_sample: True` rather than implying a stable estimate (task
#: §22) — a monitoring presentation rule, not a clinical threshold.
MIN_SAMPLE_SIZE = 5


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    if denominator == 0:
        return {"numerator": 0, "denominator": 0, "percentage": None, "limited_sample": True}
    return {
        "numerator": numerator,
        "denominator": denominator,
        "percentage": round(numerator / denominator * 100),
        "limited_sample": denominator < MIN_SAMPLE_SIZE,
    }


def _real_sessions(village_id: int):
    """Real, officer-created sessions only — never the seed-created
    template session (`health_officer=None`), and What-If never creates a
    surviving session at all (its `transaction.atomic()` always rolls
    back), so nothing further needs excluding here."""

    return SimulationSession.objects.filter(village_id=village_id, health_officer__isnull=False)


def _real_results(village_id: int):
    return SimulationResult.objects.filter(village_id=village_id, is_what_if=False)


def _choice_distribution(queryset, field: str, choices_class) -> dict[str, int]:
    counts = dict(
        queryset.exclude(**{field: ""}).values_list(field).annotate(count=Count("id")).values_list(
            field, "count"
        )
    )
    return {value: counts.get(value, 0) for value, _label in choices_class.choices}


def _source_relationship_tally(village_id: int) -> list[dict[str, Any]]:
    """Per-source SUPPORTING/CONFLICTING/INSUFFICIENT counts — a plain
    tally of the relationship labels `MultiAgentOrchestrator._correlation`
    already computed and persisted on each week's `correlation`
    `SimulationAgentRun.output` (task §17: "use actual simulation
    relationship data. Do not infer causality"). Deliberately NOT a
    source-to-source pairwise table: the underlying data is each source's
    relationship to the week's primary signal, not to another named
    source — inventing a pairwise cross-tabulation from that would be a
    second, unrequested correlation computation. One bounded query
    (village-scoped `SimulationAgentRun` rows are never more than a few
    hundred even across a full demo), then a plain Python tally — not an
    N+1 pattern."""

    outputs = SimulationAgentRun.objects.filter(
        village_id=village_id, agent_name="correlation", status=SimulationAgentRun.Status.COMPLETE
    ).values_list("output", flat=True)

    tally: dict[str, dict[str, int]] = {}
    for output in outputs:
        if not isinstance(output, dict):
            continue
        for relationship in output.get("relationships", []):
            source = relationship.get("source")
            relation = relationship.get("relationship")
            if not source or relation not in {"SUPPORTING", "CONFLICTING", "INSUFFICIENT"}:
                continue
            bucket = tally.setdefault(source, {"SUPPORTING": 0, "CONFLICTING": 0, "INSUFFICIENT": 0})
            bucket[relation] += 1

    return [{"source": source, **counts} for source, counts in sorted(tally.items())]


def _decision_alignment(village_id: int) -> dict[str, Any]:
    """Human Decision Alignment (task §25/§26) — compares each decided
    investigation's ACTUAL officer decision against
    `simulation.investigation.suggested_decision()`, the same non-binding
    suggestion function the Investigation Notebook itself already shows
    (never persisted, always recomputed — reused here verbatim, not a
    second suggestion algorithm). Framed as alignment, never "AI
    accuracy": a human choosing differently from the suggestion is not an
    error (task §26)."""

    investigations = (
        SimulationInvestigation.objects.filter(village_id=village_id)
        .exclude(decision="")
        .select_related("session", "session__scenario", "session__village", "decided_by")
    )

    aligned = 0
    differed = 0
    no_suggestion = 0
    for investigation in investigations:
        session = investigation.session
        intelligence = build_intelligence(session)
        officer = investigation.decided_by
        if officer is None:
            no_suggestion += 1
            continue
        safety = SafetyEngine.evaluate_latest(session, officer)
        suggestion = compute_suggested_decision(intelligence, safety)
        if not suggestion:
            no_suggestion += 1
        elif suggestion == investigation.decision:
            aligned += 1
        else:
            differed += 1

    total = aligned + differed + no_suggestion
    return {"aligned": aligned, "differed": differed, "no_suggestion": no_suggestion, "total": total}


#: Recent Investigation Activity (task §28) — bounded so this never grows
#: into an unbounded raw-record dump.
RECENT_ACTIVITY_LIMIT = 15


def _recent_activity(village_id: int) -> list[dict[str, Any]]:
    """Flattens each investigation's own `activity_history` (task's own
    "use existing Phase 9 activity history if available... do not create a
    duplicate event system") into one village-wide, most-recent-first feed,
    capped at `RECENT_ACTIVITY_LIMIT`. Only the most recently updated
    investigations are read at all — never every investigation the village
    has ever had, however large that grows."""

    investigations = SimulationInvestigation.objects.filter(village_id=village_id).order_by(
        "-updated_at"
    )[:RECENT_ACTIVITY_LIMIT]

    entries: list[dict[str, Any]] = []
    for investigation in investigations:
        for entry in investigation.activity_history[-3:]:
            entries.append({**entry, "investigation_id": investigation.id})

    entries.sort(key=lambda entry: entry.get("timestamp", ""), reverse=True)
    return entries[:RECENT_ACTIVITY_LIMIT]


def _quality_observations(report: dict[str, Any]) -> list[str]:
    """Deterministic, evidence-grounded observations (task §46/§47) —
    never "the AI failed"/"the model is wrong", always a plain count-based
    statement plus a suggested review action. Nothing here alters system
    behaviour; these are display strings only."""

    observations: list[str] = []
    safety = report["safety"]
    if safety["BLOCK"] > 0:
        observations.append(f"Safety blocked {safety['BLOCK']} simulated signal(s).")

    conflicting_total = sum(entry["CONFLICTING"] for entry in report["source_relationships"])
    if conflicting_total > 0:
        observations.append(
            f"{conflicting_total} correlation check(s) found conflicting source relationships. "
            "Review investigations with repeated source disagreement."
        )

    if report["evidence"]["WEAK"] > 0:
        observations.append(
            f"{report['evidence']['WEAK']} week(s) produced weak evidence. "
            "Review signals with persistent missing or weak evidence."
        )

    if report["missing_data_occurrences"] > 0:
        observations.append(
            f"{report['missing_data_occurrences']} source report(s) were missing across "
            "investigated weeks. Review signals with persistent missing data."
        )

    feedback_rate = report["feedback"]["response_rate"]
    if feedback_rate["limited_sample"]:
        observations.append(
            "Feedback response rate has a limited sample. Collect more feedback before "
            "interpreting usefulness trends."
        )

    alignment = report["decision_alignment"]
    if alignment["differed"] > 0:
        observations.append(
            f"{alignment['differed']} investigation(s) had a system suggestion that differed "
            "from the officer's decision. Review investigations where system suggestions "
            "frequently differ from officer decisions."
        )

    return observations


def build_monitoring_report(village) -> dict[str, Any]:
    village_id = village.id

    sessions = _real_sessions(village_id)
    session_total = sessions.count()
    session_completed = sessions.filter(status=SimulationSession.Status.COMPLETED).count()

    investigations = SimulationInvestigation.objects.filter(village_id=village_id)
    investigation_started = investigations.count()
    decisions_recorded = investigations.exclude(decision="").count()

    feedback_qs = SimulationFeedback.objects.filter(village_id=village_id)
    feedback_submitted = feedback_qs.count()

    results = _real_results(village_id)
    evidence_counts = {
        "STRONG": results.filter(evidence_strength="STRONG").count(),
        "MODERATE": results.filter(evidence_strength="MODERATE").count(),
        "WEAK": results.filter(evidence_strength="WEAK").count(),
    }
    safety_counts = {
        "PASS": results.filter(gate_result=SafetyGateResult.PASS).count(),
        "INSUFFICIENT": results.filter(gate_result=SafetyGateResult.INSUFFICIENT).count(),
        "BLOCK": results.filter(gate_result=SafetyGateResult.BLOCK).count(),
    }

    missing_data_occurrences = SimulationSourceSignal.objects.filter(
        village_id=village_id, reported=False
    ).count()

    decision_distribution = _choice_distribution(investigations, "decision", InvestigationDecision)

    report: dict[str, Any] = {
        "scope": {"village_code": village.code, "village_name": village.name},
        "sessions": {"total": session_total, "completed": session_completed},
        "investigations": {
            "started": investigation_started,
            "decisions_recorded": decisions_recorded,
            "decision_rate": _ratio(decisions_recorded, investigation_started),
        },
        "feedback": {
            "submitted": feedback_submitted,
            # Denominator = decisions recorded: feedback's primary moment
            # is after a decision (task §11), so "response rate" measures
            # that window, not every investigation ever opened.
            "response_rate": _ratio(feedback_submitted, decisions_recorded),
            "usefulness": {
                value: _ratio(feedback_qs.filter(usefulness=value).count(), feedback_submitted)
                for value, _label in FeedbackUsefulness.choices
            },
            "evidence_sufficiency": {
                value: _ratio(
                    feedback_qs.filter(evidence_sufficiency=value).count(), feedback_submitted
                )
                for value, _label in FeedbackEvidenceSufficiency.choices
            },
            "recommendation_helpful": {
                value: _ratio(
                    feedback_qs.filter(recommendation_helpful=value).count(), feedback_submitted
                )
                for value, _label in FeedbackYesPartiallyNo.choices
            },
            "additional_verification_required": {
                value: _ratio(
                    feedback_qs.filter(additional_verification_required=value).count(),
                    feedback_submitted,
                )
                for value, _label in FeedbackYesNo.choices
            },
        },
        "evidence": {**evidence_counts, "total": sum(evidence_counts.values())},
        "safety": {**safety_counts, "total": sum(safety_counts.values())},
        "decisions": decision_distribution,
        "source_relationships": _source_relationship_tally(village_id),
        "missing_data_occurrences": missing_data_occurrences,
        "decision_alignment": _decision_alignment(village_id),
        "recent_activity": _recent_activity(village_id),
    }
    report["quality_observations"] = _quality_observations(report)
    return report
