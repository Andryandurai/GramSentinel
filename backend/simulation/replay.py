"""Phase 7 — Signal Replay: deterministic re-display of already-computed
weeks.

The central invariant (task §7/§36): "Replay = what already happened."
Nothing in this module recomputes a trend, a source relationship, a data
quality figure, or a safety verdict. `build_replay_state()` only:

  1. bounds the requested week to `[min_week, session.replay_position]` —
     never a future/unrevealed week, and never below the scenario's first
     seeded week — an INVARIANT ENFORCED HERE, not only by the frontend
     disabling a button (task §6);
  2. calls `simulation.intelligence.build_intelligence(session, as_of_week=
     week)` for the timeline/constellation/source_fusion/data_quality/
     explanation — itself already a pure read over persisted
     `SimulationAgentRun` output (Phase 5), now simply capped at an
     earlier week instead of always "now"; and
  3. reads the exact `SimulationAgentRun` row Phase 6's real
     `SafetyEngine.evaluate()` persisted for that week — `output` on that
     row IS the full `{checks, gate_result, human_review_required,
     evidence_strength}` dict, verbatim, from the moment it was computed.

It never calls `SafetyEngine.evaluate()`/`evaluate_latest()` again: doing
so would be a live *recomputation*, not a replay, and — while harmless
today since the rules are pure — would silently show a DIFFERENT result
for an old week if a future change ever touched a threshold constant,
misrepresenting what the officer was actually shown at the time (task §7:
"do not silently recompute it differently"). Reading the persisted row is
both cheaper and more honest.

No row is created, modified, or deleted anywhere in this module.
"""

from __future__ import annotations

from typing import Any

from rest_framework.exceptions import APIException

from .intelligence import _batches_by_week, build_intelligence, with_safety
from .investigation import suggested_decision
from .models import SimulationSession, get_template_session


class ReplayWeekOutOfRange(APIException):
    """Raised when a requested replay week falls outside
    `[min_week, max_week]` for this session — a 400, not a 403/404: the
    session itself is authorized and exists, but the requested week is
    structurally invalid (task §6: "never expose future/uncomputed
    weeks... this is a backend invariant, not merely a frontend
    restriction")."""

    status_code = 400
    default_detail = "The requested replay week is outside the range this session has computed."
    default_code = "simulation_replay_week_out_of_range"


def _persisted_safety_for_week(session: SimulationSession, week: int) -> dict[str, Any] | None:
    """The exact JSON Phase 6's `SafetyEngine.evaluate()` returned when
    this week was originally advanced into — read back verbatim from the
    `safety`-named `SimulationAgentRun` row `simulation.services
    ._persist_agent_runs` already created. `None` only for week 1 (the
    pipeline never runs on `start()`) or a week whose evidence stage
    genuinely failed upstream (the safety slot was recorded as a skipped
    `FAILED`, not a real evaluation — see `orchestrator._fill_remaining`)."""

    agent_runs = list(session.agent_runs.order_by("id"))
    batch = _batches_by_week(agent_runs).get(week, {})
    safety_run = batch.get("safety")
    if safety_run is None or not isinstance(safety_run.output, dict):
        return None
    if safety_run.status != safety_run.Status.COMPLETE:
        return None
    return safety_run.output


def _no_safety_yet(reason: str) -> dict[str, Any]:
    """A truthful "not evaluated" placeholder — never a fabricated PASS —
    for a replayed week that has no persisted safety result (week 1, or a
    week whose upstream pipeline failed)."""

    return {
        "checks": [],
        "gate_result": None,
        "human_review_required": True,
        "evidence_strength": None,
        "not_evaluated_reason": reason,
    }


def _min_week(template: SimulationSession) -> int:
    first = template.events.order_by("week_number").values_list("week_number", flat=True).first()
    return first if first is not None else 1


def build_replay_state(session: SimulationSession, week: int | None = None) -> dict[str, Any]:
    """The one Replay read. `week=None` means "show the latest computed
    week" (`session.replay_position`) — the same default `.../intelligence/`
    and `.../safety/` already use, so opening Replay without moving
    anything shows exactly what those endpoints already show.
    """

    template = get_template_session(session.scenario)
    min_week = _min_week(template) if template is not None else 1
    max_week = max(session.replay_position, 0)

    if max_week < min_week:
        # No week has ever been revealed for this session (defensive only
        # — every real `start()`-created session already has week 1).
        empty_intelligence = build_intelligence(session, as_of_week=min_week)
        empty_safety = _no_safety_yet("No reporting week has been revealed for this session yet.")
        empty_payload = with_safety(empty_intelligence, empty_safety)
        empty_payload["suggested_next_step"] = suggested_decision(empty_intelligence, empty_safety)
        return {
            "week": None,
            "min_week": min_week,
            "max_week": max_week,
            "is_first": True,
            "is_last": True,
            "intelligence": empty_payload,
        }

    effective_week = max_week if week is None else week
    if effective_week < min_week or effective_week > max_week:
        raise ReplayWeekOutOfRange(
            detail=(
                f"Week {effective_week} is outside the computed range "
                f"({min_week}-{max_week}) for this session."
            )
        )

    intelligence = build_intelligence(session, as_of_week=effective_week)
    safety = _persisted_safety_for_week(session, effective_week)
    if safety is None:
        safety = _no_safety_yet(
            "The multi-agent pipeline has not completed for this week — "
            "advance the session at least once to see a safety result."
        )
    # Replay is read-only (module docstring) — this is the exact same
    # `suggested_decision()` the live `.../intelligence/` endpoint calls,
    # applied to this ALREADY-persisted week's intelligence/safety, never
    # a live recomputation (task §44: "Replay must not recompute the
    # pipeline").
    payload = with_safety(intelligence, safety)
    payload["suggested_next_step"] = suggested_decision(intelligence, safety)

    return {
        "week": effective_week,
        "min_week": min_week,
        "max_week": max_week,
        "is_first": effective_week == min_week,
        "is_last": effective_week == max_week,
        "intelligence": payload,
    }
