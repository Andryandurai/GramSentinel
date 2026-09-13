"""SimulationEngine — Phase 3 execution/session-lifecycle service layer,
extended in Phase 4 to also run and persist the multi-agent pipeline.

Deliberately thin and deterministic: it only ever reads seeded
`SimulationEvent`/`SimulationSourceSignal` rows and advances a
`SimulationSession`'s own `status`/`replay_position`. Nothing here calls the
real Safety Engine, `run_community_pipeline()`, or the operational
`AgentRun`, and nothing here imports or writes to any operational table —
`CommunityReport`, `CommunitySignal`, `Alert`, `Investigation`, `Feedback`
never appear in this module. The one exception, added in Phase 4, is
`simulation.orchestrator.MultiAgentOrchestrator`: a simulation-only,
deterministic (plus optional LLM narrative) pipeline that reads the same
seeded rows and produces `SimulationAgentRun` records — never an
operational one.

Defense in depth (Phase 3 task §1/§6): the DRF permission class
(`SessionBelongsToOfficerVillage`) and the object-permission check on the
scenario before a session is created are the first layers; every method
here independently re-checks village scope a further time using the same
`users.scoping.scoped_village_id` helper used everywhere else in the
codebase — so a bug or omission in the view layer alone cannot leak another
village's session.

Session lifecycle actually used in Phase 3 (the real Phase 2 `Status`
choices — `NOT_STARTED` / `IN_PROGRESS` / `COMPLETED`, not the blueprint's
illustrative `RUNNING`/`COMPLETE` naming): a seed-created *template* session
(`health_officer=None`) stays `NOT_STARTED` forever and is never advanced —
it only exists to hold a scenario's canonical weekly timeline. `start()`
creates a brand new, officer-owned session at `IN_PROGRESS`; `advance()`
moves it forward one seeded week at a time and flips it to `COMPLETED` the
moment it lands on the last one. A `COMPLETED` session can never advance
again — enforced here, not only by the frontend disabling a button.

Phase 4 boundary: the multi-agent pipeline runs on `advance()` only, not on
`start()`. Week 1 (returned by `start()`) is the scenario's opening state —
there is no "previous week" for it to analyse yet, and the task explicitly
scopes pipeline execution to advancing ("NEXT WEEK"). `start()`'s response
still carries an `agent_runs` key (empty) so the frontend's shape is uniform.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied

from alerts.models import Alert
from users.scoping import scoped_village_id

from .models import (
    EvidenceStrength,
    SafetyGateResult,
    SimulationAgentRun,
    SimulationEvent,
    SimulationResult,
    SimulationSafetyCheck,
    SimulationScenario,
    SimulationSession,
    get_template_session,
)
from .orchestrator import MultiAgentOrchestrator
from .safety import SafetyEngine

logger = logging.getLogger("gramsentinel.simulation")


class SimulationVillageMismatch(PermissionDenied):
    """Raised whenever a scenario/session's village does not match the
    requesting officer's own village. Maps to HTTP 403 via DRF's default
    exception handling (then re-wrapped into the project's usual
    `{"error": true, "detail": ...}` envelope by
    `config.exceptions.gramsentinel_exception_handler`)."""

    default_detail = "This simulation session is outside your authorized village."
    default_code = "simulation_village_mismatch"


class SimulationSessionNotRunning(APIException):
    """Raised when `advance()` is called on a session that is not
    `IN_PROGRESS` — a state conflict, not an authorization failure, so this
    maps to HTTP 409 rather than 403."""

    status_code = 409
    default_detail = (
        "This simulation session has already finished and cannot be advanced."
    )
    default_code = "simulation_session_not_running"


def officer_may_access_village(village_id: int, user) -> bool:
    """The one village-comparison rule, reused for both scenario and session
    checks — the same "no village on the officer = district-wide" rule
    `users.scoping` already applies to every other officer-facing view."""

    officer_village_id = scoped_village_id(user)
    return officer_village_id is None or officer_village_id == village_id


def _event_payload(event: SimulationEvent) -> dict[str, Any]:
    """One week's synthetic data, exactly as seeded in Phase 2 — never
    recomputed and never generated on the fly. `source_signals` (the
    denormalized category summary) is merged with the per-source rows so
    the "missing != zero" distinction the Missing Data scenario needs is
    actually visible in the response, not only in the database."""

    payload = dict(event.source_signals)
    payload["sources"] = [
        {
            "source_type": row.source_type,
            "reported": row.reported,
            "value": row.value,
        }
        for row in event.per_source_signals.all()
    ]
    return payload


def _create_agent_run(
    session: SimulationSession, result: dict[str, Any], cursor
) -> tuple[SimulationAgentRun, Any]:
    """Persists one stage result and returns `(row, next_cursor)` — the
    shared piece of `_persist_agent_runs`' bookkeeping (real `duration_ms`
    measurements walked forward from one timestamp anchor) reused for both
    stages 1-4 and the stage-5 safety row below, so the two don't drift
    into two slightly different timestamp conventions."""

    ran = result["duration_ms"] is not None
    started_at = cursor if ran else None
    if ran:
        cursor = cursor + timedelta(milliseconds=result["duration_ms"])
    ended_at = cursor if ran else None

    run = SimulationAgentRun.objects.create(
        session=session,
        village=session.village,
        agent_name=result["agent"],
        status=result["status"],
        input=result["input"],
        output=result["output"],
        duration_ms=result["duration_ms"],
        started_at=started_at,
        ended_at=ended_at,
    )
    return run, cursor


def _investigation_priority(evidence_strength: str, gate_result: str) -> str:
    """Phase 9's one deterministic triage label — `SimulationResult
    .investigation_priority` was schema-only since Phase 2, explicitly
    reserved for "a later phase's investigation-priority workflow" (see
    that field's own docstring). Reuses `Alert.Severity` (LOW/MODERATE/
    HIGH), the same vocabulary the operational system already uses for
    this exact concept — never a new score. Inputs are exactly the two
    values Phase 6 already finalized for this week; nothing here
    recomputes evidence or re-runs a safety rule.

    A BLOCKed week is always LOW: escalation is disallowed for it, so
    there is nothing to prioritise highly regardless of what the
    preliminary evidence strength happened to be.
    """

    if gate_result == SafetyGateResult.BLOCK:
        return Alert.Severity.LOW
    if evidence_strength == EvidenceStrength.STRONG and gate_result == SafetyGateResult.PASS:
        return Alert.Severity.HIGH
    if evidence_strength == EvidenceStrength.MODERATE:
        return Alert.Severity.MODERATE
    return Alert.Severity.LOW


def _persist_safety_evaluation(
    session: SimulationSession, safety_result: dict[str, Any]
) -> None:
    """One `SimulationSafetyCheck` row per rule (task §11) plus one
    finalized `SimulationResult` row — both an append-only audit trail
    (mirroring `SimulationAgentRun`'s own per-week history) never read back
    by the API itself: `GET .../safety/` and `.../intelligence/` both call
    `SafetyEngine.evaluate_latest()` fresh, the same "compute on read"
    convention Phase 5's `build_intelligence` already established, so a
    persisted row can never silently drift from the live session state."""

    SimulationSafetyCheck.objects.bulk_create(
        [
            SimulationSafetyCheck(
                session=session,
                village=session.village,
                rule_name=check["rule"],
                result=check["result"],
                reason=check["reason"],
            )
            for check in safety_result["checks"]
        ]
    )
    SimulationResult.objects.create(
        session=session,
        village=session.village,
        evidence_strength=safety_result["evidence_strength"],
        gate_result=safety_result["gate_result"],
        investigation_priority=_investigation_priority(
            safety_result["evidence_strength"], safety_result["gate_result"]
        ),
    )


def _persist_agent_runs(
    session: SimulationSession,
    event: SimulationEvent,
    previous_event: SimulationEvent | None,
    health_officer,
    *,
    on_stage_start=None,
    on_stage_persisted=None,
) -> list[SimulationAgentRun]:
    """Runs the Phase 4 pipeline (stages 1-4) for one advanced week,
    persists each as a `SimulationAgentRun`, and — Phase 6 — if evidence
    genuinely completed, runs the real deterministic Safety Engine
    (`simulation.safety.SafetyEngine`) against the now-persisted week and
    persists ITS result as the 5th `SimulationAgentRun` (`agent_name`
    `"safety"`) plus the full `SimulationSafetyCheck` audit trail and a
    finalized `SimulationResult` row.

    If an earlier stage failed, `run_pipeline()` already returned a
    skipped/`FAILED` `safety` entry via `_fill_remaining` — there is no
    usable evidence for the Safety Engine to evaluate, so it is correctly
    recorded as not having run rather than invoked against nothing; no
    `SimulationSafetyCheck`/`SimulationResult` rows are created for that
    week either.

    If the Safety Engine itself raises unexpectedly (a genuine
    implementation bug, not a rule finding), the 5th row is persisted as
    `FAILED` with a clean error message — never a false `COMPLETE`/PASS
    (task §15: "never fail open").

    `on_stage_start`/`on_stage_persisted` (Phase 8 — Live Streaming, both
    default `None`, so `advance()`'s ordinary REST callers are completely
    unaffected): optional hooks invoked around each of the 5 stages —
    `on_stage_start(agent_name)` immediately before that stage runs,
    `on_stage_persisted(run)` immediately after its `SimulationAgentRun`
    row is actually written to the database. Persistence happens
    stage-by-stage (interleaved into the orchestrator's own stage loop via
    `run_pipeline`'s hooks below), never batched after the fact — a caller
    hooking these never observes a "COMPLETE" for a stage whose row is not
    yet committed. This function still runs the exact same
    `MultiAgentOrchestrator.run_pipeline`/`SafetyEngine.evaluate_latest`
    calls as before; the hooks only let a caller *observe* that unchanged
    sequence, never alter it.
    """

    runs: list[SimulationAgentRun] = []
    cursor = timezone.now()

    def _persist_and_notify(result: dict[str, Any]) -> None:
        nonlocal cursor
        run, cursor = _create_agent_run(session, result, cursor)
        runs.append(run)
        if on_stage_persisted is not None:
            on_stage_persisted(run)

    results = MultiAgentOrchestrator.run_pipeline(
        event,
        previous_event,
        on_stage_start=on_stage_start,
        on_stage_done=_persist_and_notify,
    )

    evidence_completed = (
        len(results) == 4
        and results[-1]["agent"] == "evidence"
        and results[-1]["status"] == SimulationAgentRun.Status.COMPLETE
    )
    if evidence_completed:
        if on_stage_start is not None:
            on_stage_start("safety")
        safety_started = time.perf_counter()
        try:
            safety_result = SafetyEngine.evaluate_latest(session, health_officer)
            safety_status = SimulationAgentRun.Status.COMPLETE
            safety_output: dict[str, Any] = safety_result
        except Exception:  # noqa: BLE001 - never let a bug produce a false PASS
            logger.exception(
                "[SIMULATION PIPELINE] safety evaluation failed unexpectedly for session %s",
                session.id,
            )
            safety_result = None
            safety_status = SimulationAgentRun.Status.FAILED
            safety_output = {"error": "Safety evaluation could not complete."}
        safety_duration_ms = round((time.perf_counter() - safety_started) * 1000, 2)

        safety_run, cursor = _create_agent_run(
            session,
            {
                "agent": "safety",
                "status": safety_status,
                "input": {"upstream": "evidence"},
                "output": safety_output,
                "duration_ms": safety_duration_ms,
            },
            cursor,
        )
        runs.append(safety_run)
        if on_stage_persisted is not None:
            on_stage_persisted(safety_run)

        if safety_result is not None:
            _persist_safety_evaluation(session, safety_result)

    return runs


def _serialize_agent_run(run: SimulationAgentRun) -> dict[str, Any]:
    return {
        "agent_name": run.agent_name,
        "status": run.status,
        "status_display": run.get_status_display(),
        "input": run.input,
        "output": run.output,
        "duration_ms": run.duration_ms,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
    }


class SimulationEngine:
    """No instance state — every method is a `classmethod`/`staticmethod`
    taking exactly what it needs. Kept as a class (rather than bare module
    functions) purely for a stable, single import site
    (`from simulation.services import SimulationEngine`).
    """

    @staticmethod
    def _template_session(scenario: SimulationScenario) -> SimulationSession:
        """Thin wrapper around `models.get_template_session` that adds the
        session-lifecycle-specific `SimulationSessionNotRunning` error —
        appropriate for `start()`/`advance()`, which cannot proceed at all
        without a template, but not assumed by `get_template_session`
        itself (Phase 6's `intelligence.py`/`safety/engine.py` also call
        that function directly and handle a missing template differently)."""

        template = get_template_session(scenario)
        if template is None:
            raise SimulationSessionNotRunning(
                detail="This scenario has no seeded timeline to run yet."
            )
        return template

    @classmethod
    def start(cls, scenario: SimulationScenario, health_officer) -> dict[str, Any]:
        """Create a new, officer-owned `SimulationSession` and return week 1.

        Village re-check #2 here (service layer), independent of whatever
        object-level permission already ran in the view.
        """

        if not officer_may_access_village(scenario.village_id, health_officer):
            raise SimulationVillageMismatch()

        template = cls._template_session(scenario)
        first_event = template.events.order_by("week_number").first()
        if first_event is None:
            raise SimulationSessionNotRunning(
                detail="This scenario has no seeded weeks to run yet."
            )

        with transaction.atomic():
            session = SimulationSession.objects.create(
                scenario=scenario,
                village=scenario.village,
                health_officer=health_officer,
                status=SimulationSession.Status.IN_PROGRESS,
                replay_position=first_event.week_number,
            )

        return cls._state(session, first_event, template.events.count(), [])

    @classmethod
    def advance(
        cls,
        session: SimulationSession,
        health_officer,
        *,
        on_stage_start=None,
        on_stage_persisted=None,
    ) -> dict[str, Any]:
        """Move a session to its next seeded week, run the Phase 4
        multi-agent pipeline against it, and return both.

        Village re-check #2 here too (service layer), independent of
        whatever object-level permission already ran in the view.

        `on_stage_start`/`on_stage_persisted` (Phase 8 — Live Streaming):
        optional, forwarded verbatim to `_persist_agent_runs`. Both default
        to `None`, which is exactly what `SimulationSessionAdvanceView` still
        passes (`SimulationEngine.advance(session, request.user)`, two
        positional args) — so the ordinary REST advance path is byte-for-byte
        unchanged. Only the Phase 8 live runner (`simulation.live_runner`)
        supplies these, to observe each stage the instant its row is
        actually persisted.
        """

        if not officer_may_access_village(session.village_id, health_officer):
            raise SimulationVillageMismatch()

        if session.status != SimulationSession.Status.IN_PROGRESS:
            raise SimulationSessionNotRunning()

        template = cls._template_session(session.scenario)
        previous_week_number = session.replay_position
        next_week_number = previous_week_number + 1
        next_event = template.events.filter(week_number=next_week_number).first()
        if next_event is None:
            # Defensive only: normal flow already marks COMPLETED the moment
            # it lands on the last seeded event, so a healthy client can
            # never reach this — it means advance() was called past the end
            # of the seeded timeline somehow.
            raise SimulationSessionNotRunning()

        previous_event = template.events.filter(
            week_number=previous_week_number
        ).first()
        is_last = not template.events.filter(week_number__gt=next_week_number).exists()

        with transaction.atomic():
            session.replay_position = next_week_number
            session.status = (
                SimulationSession.Status.COMPLETED
                if is_last
                else SimulationSession.Status.IN_PROGRESS
            )
            session.save(update_fields=["replay_position", "status"])
            agent_runs = _persist_agent_runs(
                session,
                next_event,
                previous_event,
                health_officer,
                on_stage_start=on_stage_start,
                on_stage_persisted=on_stage_persisted,
            )

        return cls._state(session, next_event, template.events.count(), agent_runs)

    @staticmethod
    def _state(
        session: SimulationSession,
        event: SimulationEvent,
        total_weeks: int,
        agent_runs: list[SimulationAgentRun],
    ) -> dict[str, Any]:
        return {
            "session_id": session.id,
            "scenario_id": session.scenario_id,
            "scenario_name": session.scenario.name,
            "village_code": session.village.code,
            "village_name": session.village.name,
            "status": session.status,
            "status_display": session.get_status_display(),
            "week": event.week_number,
            "total_weeks": total_weeks,
            "values": _event_payload(event),
            "is_complete": session.status == SimulationSession.Status.COMPLETED,
            "agent_runs": [_serialize_agent_run(run) for run in agent_runs],
        }
