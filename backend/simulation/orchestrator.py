"""Phase 4 — the simulation's own multi-agent pipeline (stages 1-4).

Deliberately separate from `agents.orchestration.orchestrator` (the
operational RuralCare/Community orchestrators, Phase 1 audit §12): this
orchestrator only ever reads seeded `SimulationEvent`/`SimulationSourceSignal`
rows and produces plain dicts. It never touches an operational model and
never persists anything itself — persistence stays in
`simulation.services.SimulationEngine`, mirroring the existing project's own
split between `agents/orchestration/orchestrator.py` (pure logic) and
`alerts/services.py` (the thing that actually writes rows).

Fixed order, always:

    ingestion -> signal_analysis -> correlation -> evidence -> safety

Nothing here reorders itself based on a stage's own output, and no LLM
decides what runs next — `STAGE_ORDER` below is a plain Python tuple.

`STAGE_ORDER` names all 5 stages (still used for frontend display order and
for `simulation.intelligence`'s per-week batching, which groups persisted
`SimulationAgentRun` rows into chunks of `len(STAGE_ORDER)`), but as of
Phase 6 `MultiAgentOrchestrator.run_pipeline()` itself only executes and
returns stages 1-4. Stage 5 — the real deterministic Safety Engine — lives
in the physically separate `simulation.safety` package and is invoked by
`simulation.services._persist_agent_runs`, not by this module; see
`MultiAgentOrchestrator`'s own docstring below for exactly why.

LLM boundary (Phase 4 task §5/§6/§19/§27): the only place an LLM is ever
consulted is to *phrase* the Signal Analysis explanation. The trend
classification itself, and every other stage's output, is plain
deterministic Python — verified by `signal_analysis()` computing `trend`
*before* ever calling the LLM, and never overwriting it with whatever the
LLM said.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from agents.llm import LLMUnavailable, get_llm_client

from .models import SimulationEvent, SimulationSourceSignal

logger = logging.getLogger("gramsentinel.simulation")

STAGE_ORDER = ("ingestion", "signal_analysis", "correlation", "evidence", "safety")

#: The same four-value narrative vocabulary Phase 2's own seed data already
#: uses for `SimulationEvent.source_signals["status_label"]` — reused here
#: rather than inventing a second trend vocabulary (Phase 4 task §5).
TREND_NORMAL = "NORMAL"
TREND_STABLE = "STABLE"
TREND_INCREASING = "INCREASING"
TREND_SIGNAL_DETECTED = "SIGNAL_DETECTED"

RELATIONSHIP_SUPPORTING = "SUPPORTING"
RELATIONSHIP_CONFLICTING = "CONFLICTING"
RELATIONSHIP_INSUFFICIENT = "INSUFFICIENT"


class StageFailure(Exception):
    """Raised by a stage function when it cannot produce a usable result.

    Caught by `MultiAgentOrchestrator.run_stage`, which records it as a
    `FAILED` `SimulationAgentRun` with the failure preserved in structured
    `output` — never silently treated as success, and never surfaced to the
    officer as a raw traceback.
    """


# ---------------------------------------------------------------------------
# Stage 1 — Data Ingestion (deterministic)
# ---------------------------------------------------------------------------
def _ingestion(event: SimulationEvent, previous_event: SimulationEvent | None) -> dict[str, Any]:
    """Normalise this week's `SimulationSourceSignal` rows into one
    structured record. `reported=False` always maps to `value: None` here —
    never `0` — which is exactly the distinction the Missing Data scenario
    exists to demonstrate.
    """

    sources: dict[str, dict[str, Any]] = {}
    reported_count = 0
    missing_count = 0
    for row in event.per_source_signals.all():
        sources[row.source_type] = {"reported": row.reported, "value": row.value}
        if row.reported:
            reported_count += 1
        else:
            missing_count += 1

    return {
        "week": event.week_number,
        "sources": sources,
        "reported_source_count": reported_count,
        "missing_source_count": missing_count,
    }


# ---------------------------------------------------------------------------
# Stage 2 — Signal Analysis (deterministic trend; LLM-assisted wording only)
# ---------------------------------------------------------------------------
def _trend_direction(change: float) -> str:
    if change > 0:
        return "UP"
    if change < 0:
        return "DOWN"
    return "FLAT"


def _classify_trend(current: float, previous: float | None) -> str:
    """Pure, deterministic classification.

    Combines a relative (`change_pct`) AND an absolute (`change`) threshold
    on purpose — mirroring the same idea the operational
    `agents.gramsentinel.signal_agents.SchoolSignalAgent` already uses
    (relative change alone is misleading at small counts: 2 -> 3 is "+50%"
    but is really just "+1"). Thresholds are simulator-local, tuned for this
    scenario's small illustrative counts — not a copy of, or a substitute
    for, the operational Safety Engine's own rules.
    """

    if previous is None:
        return TREND_NORMAL

    change = current - previous
    if previous == 0:
        if change >= 3:
            return TREND_SIGNAL_DETECTED
        if change >= 2:
            return TREND_INCREASING
        return TREND_NORMAL if change == 0 else TREND_STABLE

    change_pct = (change / previous) * 100.0
    if change_pct >= 60.0 and change >= 3:
        return TREND_SIGNAL_DETECTED
    if change_pct >= 25.0 and change >= 2:
        return TREND_INCREASING
    if change_pct <= -20.0:
        return TREND_NORMAL
    return TREND_STABLE


def _deterministic_explanation(trend: str, primary_signal: str, current: float, previous: float | None) -> str:
    label = primary_signal.replace("_", " ").title()
    if previous is None:
        return f"First reporting period on record for {label}; no prior week to compare against."
    if trend == TREND_SIGNAL_DETECTED:
        return f"Detected a sharp rise in reported {label} signals — from {previous:g} to {current:g}."
    if trend == TREND_INCREASING:
        return f"Detected a sustained increase in reported {label} signals across consecutive reporting periods."
    if trend == TREND_NORMAL:
        return f"Reported {label} signals returned to their normal range ({previous:g} to {current:g})."
    return f"Reported {label} signals remained broadly stable ({previous:g} to {current:g})."


def _signal_analysis(ingestion_output: dict[str, Any], event: SimulationEvent, previous_event: SimulationEvent | None) -> dict[str, Any]:
    categories: dict[str, float] = dict(event.source_signals.get("categories", {}))
    previous_categories: dict[str, float] = (
        dict(previous_event.source_signals.get("categories", {})) if previous_event else {}
    )

    if not categories:
        raise StageFailure("This week has no reported category values to analyse.")

    primary_signal = max(categories, key=lambda key: categories[key])
    current_value = categories[primary_signal]
    previous_value = previous_categories.get(primary_signal)

    # --- deterministic classification, computed first and never overwritten ---
    trend = _classify_trend(current_value, previous_value)
    direction = _trend_direction(current_value - (previous_value or 0) if previous_value is not None else 0)

    explanation = _deterministic_explanation(trend, primary_signal, current_value, previous_value)
    used_llm = False
    try:
        client = get_llm_client()
        llm_text = client.summarise(
            system_prompt=(
                "You write one short, plain-language sentence describing a "
                "community health signal trend for a health officer. You are "
                "given the trend classification already decided by "
                "deterministic rules — restate it faithfully in plain "
                "language. Never contradict the given trend, never invent a "
                "different one, never mention diagnosis or outbreaks."
            ),
            user_prompt=(
                f"Category: {primary_signal}. Current value: {current_value:g}. "
                f"Previous value: {previous_value if previous_value is not None else 'unavailable'}. "
                f"Deterministically classified trend: {trend}. Write one sentence "
                "describing this for a health officer."
            ),
            max_tokens=80,
        )
        if llm_text.strip():
            explanation = llm_text.strip()
            used_llm = True
    except LLMUnavailable as exc:
        logger.info("Signal Analysis LLM narrative unavailable, using deterministic fallback: %s", exc)
    except Exception as exc:  # noqa: BLE001 - narrative failure must never fail the stage
        logger.warning("Signal Analysis LLM narrative failed unexpectedly, using deterministic fallback: %s", exc)

    return {
        "primary_signal": primary_signal,
        "trend": trend,
        "current_value": current_value,
        "previous_value": previous_value,
        "direction": direction,
        "explanation": explanation,
        "explanation_used_llm": used_llm,
    }


# ---------------------------------------------------------------------------
# Stage 3 — Correlation (deterministic)
# ---------------------------------------------------------------------------
def _source_history(event: SimulationEvent, previous_event: SimulationEvent | None) -> dict[str, dict[str, Any]]:
    current_rows = {row.source_type: row for row in event.per_source_signals.all()}
    previous_rows: dict[str, SimulationSourceSignal] = (
        {row.source_type: row for row in previous_event.per_source_signals.all()}
        if previous_event
        else {}
    )
    history = {}
    for source_type, row in current_rows.items():
        history[source_type] = {"current": row, "previous": previous_rows.get(source_type)}
    return history


def _correlation(event: SimulationEvent, previous_event: SimulationEvent | None, signal_output: dict[str, Any]) -> dict[str, Any]:
    primary_direction = signal_output["direction"]
    relationships = []

    for source_type, pair in _source_history(event, previous_event).items():
        current_row: SimulationSourceSignal = pair["current"]
        previous_row: SimulationSourceSignal | None = pair["previous"]

        if not current_row.reported:
            relationship = RELATIONSHIP_INSUFFICIENT
            reason = f"{source_type} did not report this week."
        elif previous_row is None or not previous_row.reported or previous_row.value is None:
            relationship = RELATIONSHIP_INSUFFICIENT
            reason = f"{source_type} has no usable prior week to compare against."
        else:
            source_direction = _trend_direction(current_row.value - previous_row.value)
            if source_direction == primary_direction:
                relationship = RELATIONSHIP_SUPPORTING
                reason = f"{source_type} moved {source_direction.lower()}, matching the primary signal."
            elif "FLAT" in (source_direction, primary_direction):
                relationship = RELATIONSHIP_INSUFFICIENT
                reason = f"{source_type} moved {source_direction.lower()}, too small to compare against the primary signal."
            else:
                relationship = RELATIONSHIP_CONFLICTING
                reason = f"{source_type} moved {source_direction.lower()}, opposite the primary signal."

        relationships.append({"source": source_type, "relationship": relationship, "reason": reason})

    supporting = [r["source"] for r in relationships if r["relationship"] == RELATIONSHIP_SUPPORTING]
    conflicting = [r["source"] for r in relationships if r["relationship"] == RELATIONSHIP_CONFLICTING]
    insufficient = [r["source"] for r in relationships if r["relationship"] == RELATIONSHIP_INSUFFICIENT]

    parts = []
    if supporting:
        parts.append(f"{', '.join(supporting)} support the primary signal")
    if conflicting:
        parts.append(f"{', '.join(conflicting)} conflict with it")
    if insufficient:
        parts.append(f"{', '.join(insufficient)} {'is' if len(insufficient) == 1 else 'are'} insufficient")
    explanation = "; ".join(parts) + "." if parts else "No sources were available to correlate this week."

    return {"relationships": relationships, "explanation": explanation}


# ---------------------------------------------------------------------------
# Stage 4 — Evidence (deterministic; preliminary only)
# ---------------------------------------------------------------------------
def _evidence(ingestion_output: dict[str, Any], signal_output: dict[str, Any], correlation_output: dict[str, Any]) -> dict[str, Any]:
    return {
        "primary_signal": signal_output["primary_signal"],
        "trend": signal_output["trend"],
        "current_value": signal_output["current_value"],
        "source_relationships": correlation_output["relationships"],
        "reporting_summary": {
            "reported_sources": ingestion_output["reported_source_count"],
            "missing_sources": ingestion_output["missing_source_count"],
        },
        "preliminary_evidence": True,
        "explanation": (
            "Preliminary evidence assembled from the available source "
            "signals and their relationships. This is not a final evidence "
            "strength or safety determination."
        ),
    }


class MultiAgentOrchestrator:
    """Runs stages 1-4 of the fixed five-stage pipeline for one simulated
    week — ingestion, signal_analysis, correlation, evidence.

    Stage 5 (safety) is deliberately NOT run from here as of Phase 6: it
    lives in the physically separate `simulation.safety` package (task §4
    — "no LLM dependency", "physically separated... easy to audit"), and
    it needs the `SimulationSession`/officer to re-verify village scope
    (Rule 1) and to read back this week's own just-persisted
    `SimulationAgentRun` rows via `simulation.intelligence.build_intelligence`
    (Rules 5/6) — neither of which `run_pipeline` has or needs for stages
    1-4. Importing `simulation.safety` from here would also create an
    import cycle (`safety.rules` already imports the trend/relationship
    constants below). `simulation.services._persist_agent_runs` is the one
    place that calls `run_pipeline()` for stages 1-4, persists them, and
    then separately calls `SafetyEngine.evaluate_latest()` for stage 5 —
    see that function's own docstring.

    On success, `run_pipeline()` returns exactly 4 results (ingestion
    through evidence, all `COMPLETE`). On an upstream failure, it returns
    up to 5 (via `_fill_remaining`, which still marks a skipped `safety`
    entry too — there is no usable evidence for the real Safety Engine to
    evaluate, so it is correctly recorded as not having run rather than
    invoked against nothing).

    `run_stage` handles the bookkeeping every stage needs (timing, status,
    structured input/output) around a single stage function. `run_pipeline`
    calls it once per stage, in `STAGE_ORDER`, threading each stage's output
    into the ones that need it — never letting a stage's own output change
    what runs next.
    """

    @staticmethod
    def run_stage(agent_name: str, input_data: dict[str, Any], fn, *fn_args) -> dict[str, Any]:
        """Execute one stage function and return a structured result dict —
        `{agent, status, input, output, explanation, duration_ms}` — never
        persisting anything itself (see `simulation.services.SimulationEngine`,
        which turns this into a `SimulationAgentRun` row).
        """

        started = time.perf_counter()
        try:
            output = fn(*fn_args)
            status = "COMPLETE"
        except StageFailure as exc:
            output = {"error": str(exc)}
            status = "FAILED"
            logger.warning("[SIMULATION PIPELINE] %s failed: %s", agent_name, exc)
        except Exception as exc:  # noqa: BLE001 - a stage failure must be contained
            output = {"error": "This stage could not complete."}
            status = "FAILED"
            logger.exception("[SIMULATION PIPELINE] %s failed unexpectedly: %s", agent_name, exc)

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        explanation = (
            output.get("explanation", "This stage could not complete.")
            if status == "FAILED"
            else output.get("explanation", "Completed.")
        )

        return {
            "agent": agent_name,
            "status": status,
            "input": input_data,
            "output": output,
            "explanation": explanation,
            "duration_ms": duration_ms,
        }

    @classmethod
    def run_pipeline(
        cls,
        event: SimulationEvent,
        previous_event: SimulationEvent | None,
        *,
        on_stage_start: Any = None,
        on_stage_done: Any = None,
    ) -> list[dict[str, Any]]:
        """Runs stages 1-4 exactly as before. `on_stage_start`/`on_stage_done`
        are optional Phase 8 hooks (default `None`, so every existing caller
        — `simulation.services._persist_agent_runs`,
        `simulation.what_if.WhatIfEngine` — is completely unaffected): when
        given, `on_stage_start(agent_name)` fires immediately before a stage
        function runs and `on_stage_done(result)` fires immediately after,
        for both a normal completion and a `_fill_remaining` skip entry. This
        lets a caller (the Phase 8 live runner) observe/persist/broadcast
        each stage the instant it actually happens, without this module
        knowing anything about WebSockets, persistence, or timing — it stays
        exactly what it always was: pure stage functions over plain dicts.
        """

        def _run(agent_name: str, input_data: dict[str, Any], fn, *fn_args) -> dict[str, Any]:
            if on_stage_start is not None:
                on_stage_start(agent_name)
            result = cls.run_stage(agent_name, input_data, fn, *fn_args)
            if on_stage_done is not None:
                on_stage_done(result)
            return result

        results: list[dict[str, Any]] = []

        ingestion_input = {"week": event.week_number, "event_id": event.id}
        ingestion_result = _run("ingestion", ingestion_input, _ingestion, event, previous_event)
        results.append(ingestion_result)
        if ingestion_result["status"] != "COMPLETE":
            return cls._fill_remaining(results, "ingestion", on_stage_done=on_stage_done)

        signal_input = {"ingestion": ingestion_result["output"]}
        signal_result = _run(
            "signal_analysis", signal_input, _signal_analysis, ingestion_result["output"], event, previous_event
        )
        results.append(signal_result)
        if signal_result["status"] != "COMPLETE":
            return cls._fill_remaining(results, "signal_analysis", on_stage_done=on_stage_done)

        correlation_input = {
            "ingestion": ingestion_result["output"],
            "signal_analysis": signal_result["output"],
        }
        correlation_result = _run(
            "correlation", correlation_input, _correlation, event, previous_event, signal_result["output"]
        )
        results.append(correlation_result)
        if correlation_result["status"] != "COMPLETE":
            return cls._fill_remaining(results, "correlation", on_stage_done=on_stage_done)

        evidence_input = {
            "ingestion": ingestion_result["output"],
            "signal_analysis": signal_result["output"],
            "correlation": correlation_result["output"],
        }
        evidence_result = _run(
            "evidence",
            evidence_input,
            _evidence,
            ingestion_result["output"],
            signal_result["output"],
            correlation_result["output"],
        )
        results.append(evidence_result)
        if evidence_result["status"] != "COMPLETE":
            return cls._fill_remaining(results, "evidence", on_stage_done=on_stage_done)

        # Stage 5 (safety) is appended by the caller, not here — see this
        # class's own docstring above.
        return results

    @staticmethod
    def _fill_remaining(
        results: list[dict[str, Any]], failed_at: str, *, on_stage_done: Any = None
    ) -> list[dict[str, Any]]:
        """Once a stage fails, every later stage — including safety — is
        recorded as not having run, rather than silently marked complete or
        simply omitted. `on_stage_done`, when given, fires for each skipped
        entry too — so a Phase 8 stream shows every downstream stage as
        explicitly not-completed rather than silently stopping, and can
        never be mistaken for a stage that quietly succeeded."""

        remaining = STAGE_ORDER[STAGE_ORDER.index(failed_at) + 1 :]
        for agent_name in remaining:
            skipped = {
                "agent": agent_name,
                "status": "FAILED",
                "input": {},
                "output": {"error": f"Skipped: an earlier stage ({failed_at}) failed."},
                "explanation": f"Not run: {failed_at} failed.",
                "duration_ms": None,
            }
            results.append(skipped)
            if on_stage_done is not None:
                on_stage_done(skipped)
        return results
