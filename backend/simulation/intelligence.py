"""Phase 5 — Signal Intelligence + Evidence Constellation.

Assembles the structured data Phase 2 (`SimulationEvent`/
`SimulationSourceSignal`) and Phase 4 (`SimulationAgentRun`) already produced
into ONE `intelligence` payload:

    {"timeline": [...], "constellation": [...], "source_fusion": [...],
     "data_quality": {...}, "explanation": {...}}

This module computes nothing an agent hasn't already computed. It reads:
  - the officer's own `SimulationSession.agent_runs` (Phase 4's persisted,
    already-deterministic `ingestion`/`signal_analysis`/`correlation`
    output) for trend, direction and source relationships, and
  - the scenario's template session's `SimulationEvent`/
    `SimulationSourceSignal` rows (via `models.get_template_session`,
    reused rather than re-queried) for the raw per-week reported counts.

It never re-derives a trend or a source relationship with a second copy of
the classification formula — see `_latest_batches()` below. No LLM is ever
consulted here, and no operational table is read or written. No new
`SimulationAgentRun` row is created — Phase 5 is presentation/aggregation
over Phase 4's existing output, not a sixth agent (task §41/§42).

Only weeks the session has actually advanced through
(`week_number <= session.replay_position`) are included — an officer still
on week 2 of a 4-week scenario never sees week 3/4 data through this
endpoint either, matching the same reveal-as-you-advance behaviour already
enforced by `SimulationEngine.advance()`.
"""

from __future__ import annotations

from typing import Any

from .models import SafetyGateResult, SimulationAgentRun, SimulationSession, get_template_session
from .orchestrator import (
    RELATIONSHIP_CONFLICTING,
    RELATIONSHIP_INSUFFICIENT,
    RELATIONSHIP_SUPPORTING,
    STAGE_ORDER,
    TREND_INCREASING,
    TREND_NORMAL,
    TREND_SIGNAL_DETECTED,
    TREND_STABLE,
)

#: One deterministic, plain-language phrase per trend value — used only for
#: the "Why am I seeing this?" `signal` sentence. Deliberately NOT the
#: persisted `signal_analysis` run's own `explanation` field, because that
#: field may have been LLM-phrased (Phase 4 task §5/§6); this panel is a
#: safety-adjacent surface and stays 100% template-driven, with zero LLM
#: involvement, even indirectly.
_TREND_PHRASES: dict[str, str] = {
    TREND_NORMAL: "Reported signals are within their normal range",
    TREND_STABLE: "Reported signals remain broadly stable",
    TREND_INCREASING: "Reported signals show a sustained increase",
    TREND_SIGNAL_DETECTED: "Reported signals show a sharp, sustained increase",
}

#: One deterministic, plain-language phrase per Phase 6 gate result — used
#: only for the "Why am I seeing this?" `safety_status` sentence. Phase 6
#: (`simulation.safety.SafetyEngine`) has been fully implemented since this
#: module was first written; the gate result it actually persists
#: (`SimulationAgentRun(agent_name="safety").output["gate_result"]`) is the
#: single source of truth read below — never re-derived, never LLM-phrased.
_SAFETY_STATUS_PHRASES: dict[str, str] = {
    SafetyGateResult.PASS: (
        "Safety evaluation: PASS. All deterministic checks were satisfied; "
        "human review is still required before any action."
    ),
    SafetyGateResult.BLOCK: (
        "Safety evaluation: BLOCK. One or more deterministic checks failed; "
        "this signal cannot be escalated."
    ),
    SafetyGateResult.INSUFFICIENT: (
        "Safety evaluation: INSUFFICIENT. The evidence does not yet meet the "
        "threshold required for escalation."
    ),
}
_SAFETY_STATUS_NOT_YET_RUN = "Safety evaluation has not yet run for this reporting week."
_SAFETY_STATUS_FAILED = "Safety evaluation could not complete for this reporting week."

#: Deterministic evidence-strength rule (task §16/§30 — no arbitrary score,
#: no "AI confidence"). Inputs are exactly the counts already visible in the
#: constellation:
#:
#:   STRONG   — an escalating trend (INCREASING/SIGNAL_DETECTED), at least
#:              one supporting source, and no conflicting source.
#:   WEAK     — a non-escalating trend (NORMAL/STABLE), OR no supporting
#:              source at all, OR conflicting sources outnumber supporting
#:              ones.
#:   MODERATE — everything else (e.g. an escalating trend with a genuine
#:              source disagreement, or an escalating trend with only
#:              insufficient/no corroboration).
#:
#: This is a fixed lookup table over three small integers/booleans — never a
#: percentage, never a model output.
def _evidence_strength(trend: str, supporting: int, conflicting: int) -> str:
    escalating = trend in (TREND_INCREASING, TREND_SIGNAL_DETECTED)
    if not escalating or supporting == 0 or conflicting > supporting:
        return "WEAK"
    if escalating and supporting > 0 and conflicting == 0:
        return "STRONG"
    return "MODERATE"


_VERIFICATION_BY_STRENGTH: dict[str, str] = {
    "STRONG": (
        "Verify the trend with a field visit or additional source reports "
        "before any operational action."
    ),
    "MODERATE": (
        "Verify the trend with the available reporting sources before "
        "taking operational action."
    ),
    "WEAK": (
        "Continue routine monitoring; there is not yet enough evidence to "
        "warrant action."
    ),
}


def _week_label(weeks: list[int]) -> str:
    if not weeks:
        return "No reporting periods yet"
    if len(weeks) == 1:
        return f"Week {weeks[0]}"
    return f"Weeks {min(weeks)}-{max(weeks)}"


def _batches_by_week(agent_runs: list[SimulationAgentRun]) -> dict[int, dict[str, SimulationAgentRun]]:
    """Groups the session's `SimulationAgentRun` history into one batch per
    advanced week.

    `_persist_agent_runs` (Phase 4, `simulation.services`) always creates
    exactly `len(STAGE_ORDER)` rows per `advance()` call, in `STAGE_ORDER`,
    inside one transaction — so consecutive chunks of that size, in
    creation order, are exactly one week's batch each. The real week number
    for a batch is read from its `ingestion` row's own recorded
    `output["week"]` (Phase 4's `_ingestion` already returns this) rather
    than re-deriving it, and rather than adding a new column to the frozen
    `SimulationAgentRun` model.
    """

    stage_count = len(STAGE_ORDER)
    batches: dict[int, dict[str, SimulationAgentRun]] = {}
    for start in range(0, len(agent_runs), stage_count):
        chunk = agent_runs[start : start + stage_count]
        by_agent = {run.agent_name: run for run in chunk}
        ingestion_run = by_agent.get("ingestion")
        if ingestion_run is None:
            continue
        week_number = ingestion_run.output.get("week")
        if week_number is None:
            continue
        batches[week_number] = by_agent
    return batches


def _compute_data_quality(revealed_events: list) -> dict[str, Any]:
    """`completeness_pct` = reported_weeks / expected_weeks, per source and
    overall — the ONE place this formula lives (task §10/§27 of Phase 5/7:
    "do not invent a new completeness formula"). Reused by
    `build_intelligence` for a session's real persisted history, and by
    `simulation.what_if.WhatIfEngine` for a hypothetical week substituted in
    place of the real current one — both pass a plain list of
    `SimulationEvent`-like rows (each with a queryable `.per_source_signals`)
    and get back the identical shape."""

    expected_weeks = len(revealed_events)
    source_types: list[str] = []
    reported_counts: dict[str, int] = {}
    missing_periods: list[str] = []
    for event in revealed_events:
        for row in event.per_source_signals.all():
            if row.source_type not in reported_counts:
                reported_counts[row.source_type] = 0
                source_types.append(row.source_type)
            if row.reported:
                reported_counts[row.source_type] += 1
            else:
                missing_periods.append(f"{row.source_type} — Week {event.week_number}")

    per_source_quality = [
        {
            "source": source_type,
            "reported_weeks": reported_counts[source_type],
            "expected_weeks": expected_weeks,
            "completeness_pct": (
                round(reported_counts[source_type] / expected_weeks * 100)
                if expected_weeks
                else 0
            ),
        }
        for source_type in source_types
    ]
    total_reported = sum(reported_counts.values())
    total_expected = expected_weeks * len(source_types)
    overall_completeness_pct = (
        round(total_reported / total_expected * 100) if total_expected else 0
    )
    window_label = _week_label([event.week_number for event in revealed_events])

    return {
        "expected_weeks": expected_weeks,
        "window_label": window_label,
        "completeness_pct": overall_completeness_pct,
        "missing": missing_periods,
        "sources": per_source_quality,
        # No duplicate-report metadata exists anywhere in the Phase 2/3/4
        # schema — say so plainly rather than inventing detection (task
        # §12).
        "duplicates_checked": False,
    }


def build_intelligence(
    session: SimulationSession, as_of_week: int | None = None
) -> dict[str, Any]:
    """Pure read: no row is created or modified. Returns the frozen Phase 5
    shape — `timeline` / `constellation` / `source_fusion` / `data_quality`
    / `explanation` — Phase 6 added a sixth `safety` key alongside these
    (via `with_safety`), never restructuring them (task §43).

    `as_of_week` (Phase 7 — Replay, task §9): when given, caps the revealed
    history at that week instead of `session.replay_position` — the exact
    same "reveal-as-you-advance" truncation Phase 5 already applies, just
    anchored to an earlier point for browsing history rather than always
    "now". `None` (the default) preserves the Phase 5/6 behaviour exactly:
    every existing caller is unaffected.
    """

    template = get_template_session(session.scenario)
    if template is None:
        # Defensive only: every session `SimulationEngine.start()` ever
        # creates already required a template to exist. No real session
        # can reach this branch — it exists so a malformed/hand-built
        # session (as some safety-rule tests deliberately construct)
        # degrades to an honestly empty payload instead of an
        # `AttributeError`.
        empty_data_quality = {
            "expected_weeks": 0,
            "window_label": _week_label([]),
            "completeness_pct": 0,
            "missing": [],
            "sources": [],
            "duplicates_checked": False,
        }
        return {
            "timeline": [],
            "constellation": [],
            "source_fusion": [],
            "data_quality": empty_data_quality,
            "explanation": {
                "signal": "No reported signal is available yet for this session.",
                "sources_supporting": [],
                "sources_conflicting": [],
                "sources_insufficient": [],
                "reporting_periods": empty_data_quality["window_label"],
                "data_quality_summary": "No sources have reported yet.",
                "evidence_strength": "WEAK",
                "routed_reason": "No reported signal is available yet for this session.",
                "suggested_verification": _VERIFICATION_BY_STRENGTH["WEAK"],
                "safety_status": _SAFETY_STATUS_NOT_YET_RUN,
            },
        }

    effective_week = session.replay_position if as_of_week is None else as_of_week
    revealed_events = list(
        template.events.filter(week_number__lte=effective_week)
        .order_by("week_number")
        .prefetch_related("per_source_signals")
    )
    agent_runs = list(session.agent_runs.order_by("id"))
    batches = _batches_by_week(agent_runs)
    revealed_weeks = [event.week_number for event in revealed_events]

    latest_signal_analysis = None
    latest_correlation = None
    latest_safety = None
    for week in revealed_weeks:
        batch = batches.get(week)
        if not batch:
            continue
        if batch.get("signal_analysis") and batch["signal_analysis"].status == SimulationAgentRun.Status.COMPLETE:
            latest_signal_analysis = batch["signal_analysis"]
        if batch.get("correlation") and batch["correlation"].status == SimulationAgentRun.Status.COMPLETE:
            latest_correlation = batch["correlation"]
        if batch.get("safety"):
            latest_safety = batch["safety"]

    if latest_signal_analysis is not None:
        primary_signal = latest_signal_analysis.output.get("primary_signal")
    else:
        # No successfully-analysed week yet — either only `start()` has run
        # (week 1 never gets its own agent run), or every advanced week's
        # signal_analysis stage genuinely failed (empty categories; not
        # something any real seeded scenario triggers). Fall back to the
        # same trivial "largest reported category" pick Phase 4's own
        # `_signal_analysis` makes, computed directly rather than
        # duplicating that stage's full classification logic — scanning
        # backward from the most recent revealed week so a broken latest
        # week doesn't erase a perfectly good earlier one.
        primary_signal = None
        for event in reversed(revealed_events):
            categories = event.source_signals.get("categories", {})
            if categories:
                primary_signal = max(categories, key=lambda k: categories[k])
                break

    # -----------------------------------------------------------------
    # Signal Timeline — actual reported counts, never normalised, never
    # fabricated for a week whose category value is genuinely absent.
    # -----------------------------------------------------------------
    timeline: list[dict[str, Any]] = []
    for event in revealed_events:
        categories = event.source_signals.get("categories", {})
        value = categories.get(primary_signal) if primary_signal else None
        batch = batches.get(event.week_number)
        if batch and batch.get("signal_analysis") and batch["signal_analysis"].status == SimulationAgentRun.Status.COMPLETE:
            status = batch["signal_analysis"].output.get("trend")
        else:
            # Week 1 has no "previous week" to compare against — the same
            # deterministic rule `_classify_trend(current, previous=None)`
            # already returns (Phase 4 orchestrator) — or a week whose
            # stage genuinely failed, which real seeded scenarios never hit.
            status = TREND_NORMAL
        timeline.append(
            {
                "week": event.week_number,
                "primary_signal": primary_signal,
                "value": value,
                "status": status,
                "sources": [
                    {
                        "source_type": row.source_type,
                        "reported": row.reported,
                        "value": row.value,
                    }
                    for row in event.per_source_signals.all()
                ],
            }
        )

    # -----------------------------------------------------------------
    # Evidence Constellation + Source Fusion — both read the SAME latest
    # completed `correlation` agent run; neither recomputes a relationship.
    # `relation` keeps Phase 4's own frozen vocabulary (SUPPORTING /
    # CONFLICTING / INSUFFICIENT) rather than introducing a second spelling
    # (SUPPORTS / CONFLICTS) for the identical concept — the same
    # "existing convention over the prompt's illustrative spelling" call
    # made in Phase 2/3.
    # -----------------------------------------------------------------
    relationships = latest_correlation.output.get("relationships", []) if latest_correlation else []
    latest_ingestion_sources: dict[str, dict[str, Any]] = {}
    if revealed_events:
        latest_ingestion_sources = {
            row.source_type: {"reported": row.reported, "value": row.value}
            for row in revealed_events[-1].per_source_signals.all()
        }

    constellation = [
        {"source": r["source"], "relation": r["relationship"], "reason": r["reason"]}
        for r in relationships
    ]
    source_fusion = [
        {
            "source": r["source"],
            "relation": r["relationship"],
            "reason": r["reason"],
            "reported": latest_ingestion_sources.get(r["source"], {}).get("reported"),
            "current_value": latest_ingestion_sources.get(r["source"], {}).get("value"),
        }
        for r in relationships
    ]

    supporting_sources = [c["source"] for c in constellation if c["relation"] == RELATIONSHIP_SUPPORTING]
    conflicting_sources = [c["source"] for c in constellation if c["relation"] == RELATIONSHIP_CONFLICTING]
    insufficient_sources = [c["source"] for c in constellation if c["relation"] == RELATIONSHIP_INSUFFICIENT]

    # -----------------------------------------------------------------
    # Data Quality Lens — see `_compute_data_quality`'s own docstring for
    # the formula. `expected_weeks` there is the number of weeks THIS
    # session has actually revealed so far (not the scenario's full future
    # length) — a session on week 2 of 4 is not penalised for weeks 3-4 it
    # has not reached yet.
    # -----------------------------------------------------------------
    data_quality = _compute_data_quality(revealed_events)
    window_label = data_quality["window_label"]
    overall_completeness_pct = data_quality["completeness_pct"]
    source_types = [source["source"] for source in data_quality["sources"]]

    # -----------------------------------------------------------------
    # Why Am I Seeing This? — evidence-grounded and deterministic.
    # `safety_status` below reads the real, persisted Phase 6
    # `SafetyEngine` result for this week (`gate_result` on the "safety"
    # `SimulationAgentRun` row) — Phase 6 is fully implemented; this is a
    # read of its already-computed output, never a re-evaluation.
    # -----------------------------------------------------------------
    trend = timeline[-1]["status"] if timeline else TREND_NORMAL
    evidence_strength = _evidence_strength(trend, len(supporting_sources), len(conflicting_sources))
    signal_phrase = _TREND_PHRASES.get(trend, _TREND_PHRASES[TREND_NORMAL])
    signal_sentence = (
        f"{signal_phrase} for {primary_signal.replace('_', ' ').title()}."
        if primary_signal
        else "No reported signal is available yet for this session."
    )

    if conflicting_sources:
        routed_reason = f"{signal_phrase} with partial source disagreement."
    elif supporting_sources:
        channel_word = "channel" if len(supporting_sources) == 1 else "channels"
        routed_reason = (
            f"{signal_phrase} with source agreement across "
            f"{len(supporting_sources)} reporting {channel_word}."
        )
    elif insufficient_sources:
        routed_reason = f"{signal_phrase} with insufficient corroborating data."
    else:
        routed_reason = f"{signal_phrase}."

    if latest_safety is None:
        safety_status = _SAFETY_STATUS_NOT_YET_RUN
    elif latest_safety.status != SimulationAgentRun.Status.COMPLETE:
        safety_status = _SAFETY_STATUS_FAILED
    else:
        gate_result = (
            latest_safety.output.get("gate_result") if isinstance(latest_safety.output, dict) else None
        )
        safety_status = _SAFETY_STATUS_PHRASES.get(gate_result, _SAFETY_STATUS_NOT_YET_RUN)

    explanation = {
        "signal": signal_sentence,
        "sources_supporting": supporting_sources,
        "sources_conflicting": conflicting_sources,
        "sources_insufficient": insufficient_sources,
        "reporting_periods": window_label,
        "data_quality_summary": (
            f"{overall_completeness_pct}% reporting completeness across "
            f"{', '.join(source_types) if source_types else 'no sources yet'}."
        ),
        "evidence_strength": evidence_strength,
        "routed_reason": routed_reason,
        "suggested_verification": _VERIFICATION_BY_STRENGTH[evidence_strength],
        # The real, persisted Phase 6 gate result (PASS/BLOCK/INSUFFICIENT)
        # for this week — never a fabricated or optimistic default.
        "safety_status": safety_status,
    }

    return {
        "timeline": timeline,
        "constellation": constellation,
        "source_fusion": source_fusion,
        "data_quality": data_quality,
        "explanation": explanation,
    }


class SimulationIntelligenceSerializer:
    """Not a DRF `ModelSerializer` — there is no single model instance
    behind an "intelligence" payload, only a session's derived history
    across `SimulationEvent`/`SimulationSourceSignal`/`SimulationAgentRun`.
    Named to match the Phase 5 task's vocabulary; follows the same
    "hand-built dict for an aggregated/computed view" convention already
    used by `simulation.services.SimulationEngine._state()` and
    `alerts.views.OfficerDashboardView` (see `simulation/serializers.py`'s
    own docstring), exposed here through a `.data` property so the call
    site reads like any other DRF serializer.
    """

    def __init__(self, session: SimulationSession):
        self.session = session

    @property
    def data(self) -> dict[str, Any]:
        return build_intelligence(self.session)


def with_safety(intelligence: dict[str, Any], safety_result: dict[str, Any]) -> dict[str, Any]:
    """Phase 6 (task §19): extends an already-built `intelligence` payload
    with a sixth `safety` key, without touching the five frozen ones.
    Deliberately takes an already-computed `safety_result` dict rather than
    importing `simulation.safety` and computing it here — `simulation.safety
    .engine` already imports `build_intelligence` FROM this module (Rules 5
    and 6 read the same timeline/constellation/data_quality Health
    Officers see), so the reverse import would be a cycle. The caller
    (`simulation.views`) computes both and merges them.
    """

    return {**intelligence, "safety": safety_result}
