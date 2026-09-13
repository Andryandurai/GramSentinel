"""Phase 8 — live WebSocket streaming tests.

Reuses the Phase 4 scenario-building helpers and village/officer fixtures
from `test_simulation.py` (see that file's own docstrings) rather than
redefining them. No `pytest-asyncio` is installed in this project, so every
test below is a plain sync function that drives the async WebSocket
communicator via `asgiref.sync.async_to_sync` — the same pattern Channels'
own documentation recommends for pytest-django projects without a dedicated
asyncio plugin.

`STAGE_PACING_SECONDS`/`WEEK_PACING_SECONDS` (`simulation.live_runner`) are
monkeypatched to ~0 in most tests purely so the suite stays fast — see that
module's own docstring: they are presentation-only pacing, never part of
the deterministic computation, so patching them to 0 changes nothing about
what a test observes except how quickly the events arrive.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from asgiref.sync import async_to_sync
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken

from agents.llm import LLMUnavailable
from simulation import live_runner
from simulation.models import (
    SimulationAgentRun,
    SimulationResult,
    SimulationScenario,
    SimulationSession,
)
from simulation.routing import websocket_urlpatterns
from simulation.orchestrator import STAGE_ORDER

from tests.test_simulation import (
    SESSIONS_URL,
    _advance,
    _build_pipeline_scenario,
    _operational_counts,
    _week,
    officer_a_api,  # noqa: F401 - reused fixture
    officer_b_api,  # noqa: F401 - reused fixture
    village_b,  # noqa: F401 - reused fixture
)

User = get_user_model()
pytestmark = pytest.mark.django_db

APP = URLRouter(websocket_urlpatterns)

#: A short, real-but-tiny scenario: 3 weeks is enough to see every stage
#: fire, a mid-run pause, and natural completion, without a slow test suite.
_DEFAULT_WEEKS = [
    _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
    _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True)}),
    _week(3, {"FEVER": 5}, {"CHW": (5, True), "PHC": (9, True)}),
]


@pytest.fixture(autouse=True)
def _fast_pacing(monkeypatch):
    """Presentation-only pacing (see module docstring) — zeroed for every
    test in this file so the suite runs quickly and deterministically."""

    monkeypatch.setattr(live_runner, "STAGE_PACING_SECONDS", 0)
    monkeypatch.setattr(live_runner, "WEEK_PACING_SECONDS", 0)


@pytest.fixture(autouse=True)
def _no_leaked_runners_across_tests():
    """`live_runner._RUNNERS` is a process-wide dict keyed by session id —
    correct in production (real autoincrement ids are never reused), but a
    hazard in this test suite: each test's `pytest.mark.django_db`
    transaction is rolled back afterwards, and SQLite reuses the same
    integer session id in the very next test. If a previous test's
    background `_drive()` task (a real asyncio Task, cancelled or not) is
    still finishing its own `database_sync_to_async` call when the next
    test starts, it can keep executing against a session id that now
    belongs to a different test — the exact cross-test contamination this
    fixture exists to rule out. Waiting here for the registry to drain
    (with a generous but bounded timeout) before the next test's transaction
    begins removes that hazard entirely; the final forced-clear is a
    defensive backstop, never expected to actually trigger."""

    yield

    async def _drain():
        for _ in range(200):  # up to ~2s
            if not live_runner._RUNNERS:
                return
            await asyncio.sleep(0.01)

    async_to_sync(_drain)()
    live_runner._RUNNERS.clear()


def _token_for(user) -> str:
    return str(AccessToken.for_user(user))


def _ws_path(session_id: int, token: str | None) -> str:
    base = f"/ws/simulation/sessions/{session_id}/"
    return f"{base}?token={token}" if token else base


def _start_session(api_client, scenario) -> int:
    response = api_client.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    assert response.status_code == 201
    return response.data["session_id"]


async def _drain_until(communicator, predicate, *, max_events: int = 200, timeout: float = 5):
    """Reads events off the socket until `predicate(event)` is true (which
    is also returned), or gives up after `max_events` — used instead of a
    fixed sleep so tests never depend on real wall-clock timing beyond the
    already-zeroed pacing constants."""

    events = []
    for _ in range(max_events):
        event = await communicator.receive_json_from(timeout=timeout)
        events.append(event)
        if predicate(event):
            return events
    raise AssertionError(f"predicate never satisfied after {max_events} events: {events}")


# ===========================================================================
# A. Connection authorization — server-side, not merely frontend-hidden
# ===========================================================================
def test_connect_rejected_without_a_token(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "LIVE-NOAUTH", _DEFAULT_WEEKS)
    session_id = _start_session(officer_a_api, scenario)

    async def scenario_body():
        communicator = WebsocketCommunicator(APP, _ws_path(session_id, None))
        connected, _ = await communicator.connect()
        assert connected is False
        await communicator.disconnect()

    async_to_sync(scenario_body)()


def test_connect_rejected_with_an_invalid_token(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "LIVE-BADTOKEN", _DEFAULT_WEEKS)
    session_id = _start_session(officer_a_api, scenario)

    async def scenario_body():
        communicator = WebsocketCommunicator(APP, _ws_path(session_id, "not-a-real-token"))
        connected, _ = await communicator.connect()
        assert connected is False
        await communicator.disconnect()

    async_to_sync(scenario_body)()


def test_connect_rejected_for_nonexistent_session(officer_a_api, village):
    officer = User.objects.get(username="officer.simulation-test")
    token = _token_for(officer)

    async def scenario_body():
        communicator = WebsocketCommunicator(APP, _ws_path(999999, token))
        connected, _ = await communicator.connect()
        assert connected is False
        await communicator.disconnect()

    async_to_sync(scenario_body)()


def test_connect_rejected_for_a_template_session(officer_a_api, village):
    """The seed-created template session (`health_officer=None`) holds a
    scenario's canonical timeline, not a per-officer run — never streamable
    (task's own "session is a simulation session" auth requirement)."""

    scenario = _build_pipeline_scenario(village, "LIVE-TEMPLATE", _DEFAULT_WEEKS)
    template = scenario.sessions.get(health_officer__isnull=True)
    officer = User.objects.get(username="officer.simulation-test")
    token = _token_for(officer)

    async def scenario_body():
        communicator = WebsocketCommunicator(APP, _ws_path(template.id, token))
        connected, _ = await communicator.connect()
        assert connected is False
        await communicator.disconnect()

    async_to_sync(scenario_body)()


def test_connect_rejected_cross_village_officer_b_to_village_a_session(
    officer_a_api, officer_b_api, village
):
    scenario = _build_pipeline_scenario(village, "LIVE-XVILLAGE-1", _DEFAULT_WEEKS)
    session_id = _start_session(officer_a_api, scenario)
    officer_b = User.objects.get(username="officer.simulation-test-b")
    token_b = _token_for(officer_b)

    async def scenario_body():
        communicator = WebsocketCommunicator(APP, _ws_path(session_id, token_b))
        connected, _ = await communicator.connect()
        assert connected is False
        await communicator.disconnect()

    async_to_sync(scenario_body)()


def test_connect_rejected_cross_village_officer_a_to_village_b_session(
    officer_a_api, officer_b_api, village_b
):
    scenario = _build_pipeline_scenario(village_b, "LIVE-XVILLAGE-2", _DEFAULT_WEEKS)
    session_id = _start_session(officer_b_api, scenario)
    officer_a = User.objects.get(username="officer.simulation-test")
    token_a = _token_for(officer_a)

    async def scenario_body():
        communicator = WebsocketCommunicator(APP, _ws_path(session_id, token_a))
        connected, _ = await communicator.connect()
        assert connected is False
        await communicator.disconnect()

    async_to_sync(scenario_body)()


def test_connect_accepted_and_sends_connected_snapshot(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "LIVE-CONNECTED", _DEFAULT_WEEKS)
    session_id = _start_session(officer_a_api, scenario)
    officer = User.objects.get(username="officer.simulation-test")
    token = _token_for(officer)

    async def scenario_body():
        communicator = WebsocketCommunicator(APP, _ws_path(session_id, token))
        connected, _ = await communicator.connect()
        assert connected is True

        event = await communicator.receive_json_from(timeout=5)
        assert event["type"] == "simulation.connected"
        assert event["session_id"] == session_id
        assert event["village_id"] == village.id
        assert event["week"] == 1
        assert event["is_complete"] is False
        assert event["live_running"] is False

        await communicator.disconnect()

    async_to_sync(scenario_body)()


# ===========================================================================
# B. Streamed stage order, statuses, and persistence
# ===========================================================================
def test_start_streams_fixed_stage_order_with_processing_then_complete(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "LIVE-ORDER", _DEFAULT_WEEKS)
    session_id = _start_session(officer_a_api, scenario)
    officer = User.objects.get(username="officer.simulation-test")
    token = _token_for(officer)

    async def scenario_body():
        communicator = WebsocketCommunicator(APP, _ws_path(session_id, token))
        await communicator.connect()
        await communicator.receive_json_from(timeout=5)  # simulation.connected

        await communicator.send_json_to({"action": "start"})
        events = await _drain_until(
            communicator, lambda e: e["type"] == "simulation.completed", max_events=200
        )
        await communicator.disconnect()
        return events

    events = async_to_sync(scenario_body)()

    assert events[0]["type"] == "simulation.started"
    assert events[1] == {"type": "simulation.week_started", "session_id": session_id, "week": 2}

    stage_events = [e for e in events if e["type"] == "simulation.stage" and e["week"] == 2]
    observed_order = []
    for stage in STAGE_ORDER:
        pair = [e for e in stage_events if e["stage"] == stage]
        assert [p["status"] for p in pair] == ["PROCESSING", "COMPLETE"], (stage, pair)
        observed_order.append(stage)
    assert observed_order == list(STAGE_ORDER)

    week_completed = next(e for e in events if e["type"] == "simulation.week_completed" and e["week"] == 2)
    assert week_completed["is_complete"] is False

    assert events[-1]["type"] == "simulation.completed"
    assert events[-1]["week"] == 3


def test_streamed_rows_match_what_advance_would_have_persisted(officer_a_api, village):
    """The live path must never be a second engine: run one scenario over
    the WebSocket and an identical scenario over the plain REST
    `.../advance/` calls, and confirm both leave byte-identical
    `SimulationAgentRun`/`SimulationResult` outputs behind."""

    live_scenario = _build_pipeline_scenario(village, "LIVE-PARITY-WS", _DEFAULT_WEEKS)

    live_session_id = _start_session(officer_a_api, live_scenario)
    officer = User.objects.get(username="officer.simulation-test")
    token = _token_for(officer)

    async def scenario_body():
        communicator = WebsocketCommunicator(APP, _ws_path(live_session_id, token))
        await communicator.connect()
        await communicator.receive_json_from(timeout=5)
        await communicator.send_json_to({"action": "start"})
        await _drain_until(communicator, lambda e: e["type"] == "simulation.completed")
        await communicator.disconnect()

    async_to_sync(scenario_body)()

    live_outputs = list(
        SimulationAgentRun.objects.filter(session_id=live_session_id)
        .order_by("id")
        .values_list("agent_name", "status", "output")
    )
    live_results = list(
        SimulationResult.objects.filter(session_id=live_session_id).values_list(
            "evidence_strength", "gate_result"
        )
    )

    # Freed here (rather than reused): `_build_pipeline_scenario` always
    # creates version=1 of `EMERGING_SIGNAL` for the village, and the model
    # enforces one such row per village — the REST comparison scenario below
    # needs that same (village, type, version) slot. Everything this test
    # needs from the live run was already captured above as plain Python
    # values, so deleting it here loses nothing.
    live_scenario.delete()

    rest_scenario = _build_pipeline_scenario(village, "LIVE-PARITY-REST", _DEFAULT_WEEKS)
    rest_session_id = _start_session(officer_a_api, rest_scenario)
    _advance(officer_a_api, rest_session_id)
    _advance(officer_a_api, rest_session_id)

    rest_outputs = list(
        SimulationAgentRun.objects.filter(session_id=rest_session_id)
        .order_by("id")
        .values_list("agent_name", "status", "output")
    )
    assert live_outputs == rest_outputs

    rest_results = list(
        SimulationResult.objects.filter(session_id=rest_session_id).values_list(
            "evidence_strength", "gate_result"
        )
    )
    assert live_results == rest_results


def test_downstream_stages_never_falsely_complete_after_a_failure(officer_a_api, village):
    """An empty-categories week makes `signal_analysis` raise `StageFailure`
    — `correlation`/`evidence`/`safety` must stream as skipped/FAILED, never
    silently omitted or shown COMPLETE."""

    scenario = _build_pipeline_scenario(
        village,
        "LIVE-FAIL",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {}, {"CHW": (3, True)}),
        ],
    )
    session_id = _start_session(officer_a_api, scenario)
    officer = User.objects.get(username="officer.simulation-test")
    token = _token_for(officer)

    async def scenario_body():
        communicator = WebsocketCommunicator(APP, _ws_path(session_id, token))
        await communicator.connect()
        await communicator.receive_json_from(timeout=5)
        await communicator.send_json_to({"action": "start"})
        events = await _drain_until(
            communicator, lambda e: e["type"] == "simulation.completed", max_events=200
        )
        await communicator.disconnect()
        return events

    events = async_to_sync(scenario_body)()

    stage_events = [e for e in events if e["type"] == "simulation.stage" and e["week"] == 2]
    by_stage = {}
    for e in stage_events:
        by_stage.setdefault(e["stage"], []).append(e["status"])

    assert by_stage["ingestion"] == ["PROCESSING", "COMPLETE"]
    assert by_stage["signal_analysis"] == ["PROCESSING", "FAILED"]
    # Skipped downstream stages are announced once, as FAILED — never
    # COMPLETE, never silently absent.
    assert by_stage["correlation"] == ["FAILED"]
    assert by_stage["evidence"] == ["FAILED"]
    assert by_stage["safety"] == ["FAILED"]


# ===========================================================================
# C. Malicious/degraded LLM output over the live path — Phase 6 preserved
# ===========================================================================
def test_malicious_llm_output_is_still_blocked_over_the_live_path(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "LIVE-MALICIOUS",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True)}),
            _week(3, {"FEVER": 9}, {"CHW": (9, True), "PHC": (14, True)}),
        ],
    )
    session_id = _start_session(officer_a_api, scenario)
    officer = User.objects.get(username="officer.simulation-test")
    token = _token_for(officer)

    class _MaliciousClient:
        def summarise(self, **kwargs):
            return "Outbreak confirmed in this village — we declare an emergency."

    async def scenario_body():
        communicator = WebsocketCommunicator(APP, _ws_path(session_id, token))
        await communicator.connect()
        await communicator.receive_json_from(timeout=5)
        await communicator.send_json_to({"action": "start"})
        events = await _drain_until(
            communicator, lambda e: e["type"] == "simulation.completed", max_events=200
        )
        await communicator.disconnect()
        return events

    with patch("simulation.orchestrator.get_llm_client", return_value=_MaliciousClient()):
        events = async_to_sync(scenario_body)()

    safety_events = [
        e for e in events if e["type"] == "simulation.stage" and e["stage"] == "safety"
    ]
    completed_safety = [e for e in safety_events if e["status"] == "COMPLETE"]
    assert completed_safety, "safety never completed for at least one week"

    for e in completed_safety:
        gate_result = e["payload"]["output"]["gate_result"]
        assert gate_result == "BLOCK"
        # Never surfaced as a successful/valid outcome.
        assert "outbreak detected" not in str(e["payload"]).lower()
        assert "ai confidence" not in str(e["payload"]).lower()


def test_llm_failure_does_not_change_the_deterministic_trend(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "LIVE-LLMFAIL", _DEFAULT_WEEKS)
    session_id = _start_session(officer_a_api, scenario)
    officer = User.objects.get(username="officer.simulation-test")
    token = _token_for(officer)

    async def scenario_body():
        communicator = WebsocketCommunicator(APP, _ws_path(session_id, token))
        await communicator.connect()
        await communicator.receive_json_from(timeout=5)
        await communicator.send_json_to({"action": "start"})
        events = await _drain_until(
            communicator, lambda e: e["type"] == "simulation.completed", max_events=200
        )
        await communicator.disconnect()
        return events

    with patch(
        "simulation.orchestrator.get_llm_client", side_effect=LLMUnavailable("down for test")
    ):
        events = async_to_sync(scenario_body)()

    signal_events = [
        e
        for e in events
        if e["type"] == "simulation.stage" and e["stage"] == "signal_analysis" and e["status"] == "COMPLETE"
    ]
    assert signal_events, "signal_analysis never completed"
    for e in signal_events:
        assert e["payload"]["output"]["explanation_used_llm"] is False
        assert e["payload"]["output"]["trend"] in {"NORMAL", "STABLE", "INCREASING", "SIGNAL_DETECTED"}


# ===========================================================================
# D. Concurrency — multi-tab / reconnection must never double-execute
# ===========================================================================
def test_second_start_on_an_already_running_session_is_rejected(officer_a_api, village, monkeypatch):
    # Non-zero here (unlike the rest of this file): this test needs a real
    # window in which the run is provably still in progress when a second
    # connection asks to observe it. The value only affects how long that
    # window is, never the deterministic outcome (module docstring).
    monkeypatch.setattr(live_runner, "STAGE_PACING_SECONDS", 0.05)
    monkeypatch.setattr(live_runner, "WEEK_PACING_SECONDS", 0.2)

    scenario = _build_pipeline_scenario(village, "LIVE-DUPSTART", _DEFAULT_WEEKS)
    session_id = _start_session(officer_a_api, scenario)
    officer = User.objects.get(username="officer.simulation-test")
    token = _token_for(officer)

    async def scenario_body():
        driver = WebsocketCommunicator(APP, _ws_path(session_id, token))
        await driver.connect()
        await driver.receive_json_from(timeout=5)
        await driver.send_json_to({"action": "start"})
        await driver.receive_json_from(timeout=5)  # simulation.started

        observer = WebsocketCommunicator(APP, _ws_path(session_id, token))
        await observer.connect()
        connected_snapshot = await observer.receive_json_from(timeout=5)
        assert connected_snapshot["live_running"] is True

        await observer.send_json_to({"action": "start"})
        error_event = await observer.receive_json_from(timeout=5)
        assert error_event["type"] == "simulation.error"

        await _drain_until(driver, lambda e: e["type"] == "simulation.completed")
        await driver.disconnect()
        await observer.disconnect()

    async_to_sync(scenario_body)()

    # Exactly one week's worth of stages per advanced week — never doubled.
    total_runs = SimulationAgentRun.objects.filter(session_id=session_id).count()
    assert total_runs == len(_DEFAULT_WEEKS[1:]) * len(STAGE_ORDER)


def test_pause_blocks_progression_and_resume_continues_from_the_same_place(
    officer_a_api, village, monkeypatch
):
    # Non-zero (see test_second_start... above for why): pause needs a real
    # inter-week window to land in before the next week starts.
    monkeypatch.setattr(live_runner, "WEEK_PACING_SECONDS", 0.3)

    scenario = _build_pipeline_scenario(
        village,
        "LIVE-PAUSE",
        _DEFAULT_WEEKS
        + [_week(4, {"FEVER": 8}, {"CHW": (8, True), "PHC": (12, True)})],
    )
    session_id = _start_session(officer_a_api, scenario)
    officer = User.objects.get(username="officer.simulation-test")
    token = _token_for(officer)

    async def scenario_body():
        communicator = WebsocketCommunicator(APP, _ws_path(session_id, token))
        await communicator.connect()
        await communicator.receive_json_from(timeout=5)
        await communicator.send_json_to({"action": "start"})

        # Let exactly one week complete, then pause.
        await _drain_until(communicator, lambda e: e["type"] == "simulation.week_completed")
        await communicator.send_json_to({"action": "pause"})

        # Give the background loop a moment to actually reach the paused
        # wait point, then confirm it is genuinely paused rather than
        # racing a receive-timeout against the still-running task (which is
        # prone to spurious cancellation in the test ASGI harness).
        await asyncio.sleep(0.4)
        runner = live_runner.get_active_runner(session_id)
        assert runner is not None
        assert runner.is_paused is True

        session = await _get_session(session_id)
        paused_week = session.replay_position

        await communicator.send_json_to({"action": "resume"})
        events = await _drain_until(communicator, lambda e: e["type"] == "simulation.completed")
        await communicator.disconnect()
        return paused_week, events

    paused_week, events = async_to_sync(scenario_body)()

    assert paused_week == 2
    week_started_weeks = [e["week"] for e in events if e["type"] == "simulation.week_started"]
    # Resumed from the correct position — week 3 next, never re-running week 2.
    assert week_started_weeks == [3, 4]


def test_stop_ends_cleanly_without_corrupting_persisted_rows(officer_a_api, village, monkeypatch):
    monkeypatch.setattr(live_runner, "WEEK_PACING_SECONDS", 0.3)

    scenario = _build_pipeline_scenario(
        village,
        "LIVE-STOP",
        _DEFAULT_WEEKS
        + [_week(4, {"FEVER": 8}, {"CHW": (8, True), "PHC": (12, True)})],
    )
    session_id = _start_session(officer_a_api, scenario)
    officer = User.objects.get(username="officer.simulation-test")
    token = _token_for(officer)

    async def scenario_body():
        communicator = WebsocketCommunicator(APP, _ws_path(session_id, token))
        await communicator.connect()
        await communicator.receive_json_from(timeout=5)
        await communicator.send_json_to({"action": "start"})
        await _drain_until(communicator, lambda e: e["type"] == "simulation.week_completed")
        await communicator.send_json_to({"action": "stop"})
        stopped = await communicator.receive_json_from(timeout=5)
        assert stopped["type"] == "simulation.stopped"
        await communicator.disconnect()

    async_to_sync(scenario_body)()

    session = SimulationSession.objects.get(id=session_id)
    assert session.status == SimulationSession.Status.IN_PROGRESS
    assert session.replay_position == 2
    # Exactly one week's worth of rows — nothing partial or duplicated.
    assert SimulationAgentRun.objects.filter(session_id=session_id).count() == len(STAGE_ORDER)
    assert live_runner.get_active_runner(session_id) is None


def test_run_stops_when_the_driving_connection_disconnects(officer_a_api, village, monkeypatch):
    monkeypatch.setattr(live_runner, "WEEK_PACING_SECONDS", 0.3)

    scenario = _build_pipeline_scenario(
        village,
        "LIVE-DISCONNECT",
        _DEFAULT_WEEKS
        + [_week(4, {"FEVER": 8}, {"CHW": (8, True), "PHC": (12, True)})],
    )
    session_id = _start_session(officer_a_api, scenario)
    officer = User.objects.get(username="officer.simulation-test")
    token = _token_for(officer)

    async def scenario_body():
        communicator = WebsocketCommunicator(APP, _ws_path(session_id, token))
        await communicator.connect()
        await communicator.receive_json_from(timeout=5)
        await communicator.send_json_to({"action": "start"})
        await _drain_until(communicator, lambda e: e["type"] == "simulation.week_completed")
        await communicator.disconnect()

    async_to_sync(scenario_body)()

    assert live_runner.get_active_runner(session_id) is None
    session = SimulationSession.objects.get(id=session_id)
    # Must not have kept running after the page closed.
    assert session.replay_position == 2


async def _get_session(session_id: int) -> SimulationSession:
    from channels.db import database_sync_to_async

    return await database_sync_to_async(SimulationSession.objects.get)(id=session_id)


# ===========================================================================
# E. Operational data isolation
# ===========================================================================
def test_live_run_never_touches_operational_tables(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "LIVE-OPS-ISOLATION", _DEFAULT_WEEKS)
    session_id = _start_session(officer_a_api, scenario)
    officer = User.objects.get(username="officer.simulation-test")
    token = _token_for(officer)

    before = _operational_counts()

    async def scenario_body():
        communicator = WebsocketCommunicator(APP, _ws_path(session_id, token))
        await communicator.connect()
        await communicator.receive_json_from(timeout=5)
        await communicator.send_json_to({"action": "start"})
        await _drain_until(communicator, lambda e: e["type"] == "simulation.completed")
        await communicator.disconnect()

    async_to_sync(scenario_body)()

    after = _operational_counts()
    assert before == after


# ===========================================================================
# F. Replay / What-If stay unaffected by the live path
# ===========================================================================
def test_replay_still_read_only_after_a_live_run(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "LIVE-REPLAY-COMPAT", _DEFAULT_WEEKS)
    session_id = _start_session(officer_a_api, scenario)
    officer = User.objects.get(username="officer.simulation-test")
    token = _token_for(officer)

    async def scenario_body():
        communicator = WebsocketCommunicator(APP, _ws_path(session_id, token))
        await communicator.connect()
        await communicator.receive_json_from(timeout=5)
        await communicator.send_json_to({"action": "start"})
        await _drain_until(communicator, lambda e: e["type"] == "simulation.completed")
        await communicator.disconnect()

    async_to_sync(scenario_body)()

    run_count_before = SimulationAgentRun.objects.filter(session_id=session_id).count()
    response = officer_a_api.get(f"{SESSIONS_URL}{session_id}/replay/?week=2")
    assert response.status_code == 200
    assert response.data["week"] == 2

    run_count_after = SimulationAgentRun.objects.filter(session_id=session_id).count()
    assert run_count_before == run_count_after
    assert live_runner.get_active_runner(session_id) is None


def test_what_if_stays_isolated_after_a_live_run(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "LIVE-WHATIF-COMPAT", _DEFAULT_WEEKS)
    session_id = _start_session(officer_a_api, scenario)
    officer = User.objects.get(username="officer.simulation-test")
    token = _token_for(officer)

    async def scenario_body():
        communicator = WebsocketCommunicator(APP, _ws_path(session_id, token))
        await communicator.connect()
        await communicator.receive_json_from(timeout=5)
        await communicator.send_json_to({"action": "start"})
        await _drain_until(communicator, lambda e: e["type"] == "simulation.completed")
        await communicator.disconnect()

    async_to_sync(scenario_body)()

    run_count_before = SimulationAgentRun.objects.filter(session_id=session_id).count()
    session_count_before = SimulationSession.objects.count()

    response = officer_a_api.post(
        f"{SESSIONS_URL}{session_id}/what-if/", {"overrides": {"PHC": None}}, format="json"
    )
    assert response.status_code == 200
    assert response.data["is_hypothetical"] is True

    # The throwaway session/event/signal rows were rolled back — session
    # count is exactly what it was before the What-If call.
    assert SimulationSession.objects.count() == session_count_before
    assert SimulationAgentRun.objects.filter(session_id=session_id).count() == run_count_before


# ===========================================================================
# G. End-to-end against the real seeded LIVE_EMERGENCE scenario
# ===========================================================================
def test_seeded_live_emergence_scenario_streams_end_to_end(officer_a_api, village):
    """Unlike every test above (which builds a synthetic pipeline scenario
    for precise control), this one runs the actual `seed_demo`-created
    `LIVE_EMERGENCE` scenario end to end — the same one the real Simulation
    Lab UI lists and starts — confirming the minimum viable execution
    behaviour the scenario type needed (task's own §10) is real, not just
    schema."""

    from django.core.management import call_command

    call_command("seed_demo")

    scenario = SimulationScenario.objects.get(
        village=village, scenario_type=SimulationScenario.ScenarioType.LIVE_EMERGENCE
    )
    session_id = _start_session(officer_a_api, scenario)
    officer = User.objects.get(username="officer.simulation-test")
    token = _token_for(officer)

    async def scenario_body():
        communicator = WebsocketCommunicator(APP, _ws_path(session_id, token))
        connected, _ = await communicator.connect()
        assert connected is True
        snapshot = await communicator.receive_json_from(timeout=5)
        assert snapshot["type"] == "simulation.connected"

        await communicator.send_json_to({"action": "start"})
        events = await _drain_until(
            communicator, lambda e: e["type"] == "simulation.completed", max_events=200
        )
        await communicator.disconnect()
        return events

    events = async_to_sync(scenario_body)()

    assert events[-1]["type"] == "simulation.completed"
    session = SimulationSession.objects.get(id=session_id)
    assert session.status == SimulationSession.Status.COMPLETED
    # Every seeded week beyond week 1 produced a full 5-stage batch.
    total_weeks = scenario.sessions.get(health_officer__isnull=True).events.count()
    assert (
        SimulationAgentRun.objects.filter(session_id=session_id).count()
        == (total_weeks - 1) * len(STAGE_ORDER)
    )
