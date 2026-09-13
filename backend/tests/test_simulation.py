"""GramSentinel Intelligence Simulator — Phase 2 backend tests.

Covers: model creation and village-scoping (every simulation model carries
its own explicit `village` FK), the "missing != zero" invariant, the
read-only scenario API, village isolation (including the mandatory
cross-village negative test — Phase 2 task §35), inactive scenarios being
excluded, and operational-data isolation (seeding the simulator must never
touch CommunityReport/Alert/Investigation/etc.).

A dedicated `village_b` fixture is used here rather than `conftest.py`'s
shared `other_village` — that fixture's `name` is "Village C" (kept that way
deliberately, for an unrelated admin-overview test — see
`backend/tests/conftest.py`), and reusing it here would make a test file
about a simulator whose brief explicitly says "do not create a Village C
simulation scenario" read as if it does exactly that. `village_b` below uses
the real Village B's own code (`ARY`) instead.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError

from alerts.models import Alert, Investigation
from community.models import CommunityReport
from core.models import Village
from simulation.models import (
    SimulationAgentRun,
    SimulationEvent,
    SimulationInvestigation,
    SimulationResult,
    SimulationSafetyCheck,
    SimulationScenario,
    SimulationSession,
    SimulationSourceSignal,
)

User = get_user_model()
pytestmark = pytest.mark.django_db

SCENARIOS_URL = "/api/simulation/scenarios/"

ALL_SIMULATION_MODELS = (
    SimulationScenario,
    SimulationSession,
    SimulationEvent,
    SimulationSourceSignal,
    SimulationAgentRun,
    SimulationSafetyCheck,
    SimulationResult,
    SimulationInvestigation,
)


@pytest.fixture
def village_b(db) -> Village:
    return Village.objects.create(
        code="ARY", name="Ariyanur", cluster="Village Cluster A", district="Thiruvannamalai"
    )


@pytest.fixture
def scenario_a(village) -> SimulationScenario:
    return SimulationScenario.objects.create(
        village=village,
        scenario_type=SimulationScenario.ScenarioType.EMERGING_SIGNAL,
        name="SIM-A-001",
        description="Village A test scenario.",
    )


@pytest.fixture
def scenario_b(village_b) -> SimulationScenario:
    return SimulationScenario.objects.create(
        village=village_b,
        scenario_type=SimulationScenario.ScenarioType.EMERGING_SIGNAL,
        name="SIM-B-001",
        description="Village B test scenario.",
    )


@pytest.fixture
def officer_a_api(api, village):
    """A Health Officer explicitly scoped to `village` (Village A / KVL) —
    not the shared `officer`/`officer_api` fixtures, which are district-wide
    by default and would defeat the point of a village-isolation test."""

    officer = User.objects.create_user(
        username="officer.simulation-test",
        password="demo1234",
        role=User.Role.HEALTH_OFFICER,
        village=village,
        district="Thiruvannamalai",
    )
    api.force_authenticate(user=officer)
    return api


# ---------------------------------------------------------------------------
# Model creation, relationships, explicit village scope
# ---------------------------------------------------------------------------
def test_simulation_scenario_can_be_created(scenario_a, village):
    assert scenario_a.village_id == village.id
    assert scenario_a.is_active is True
    assert scenario_a.version == 1


def test_simulation_session_is_village_scoped(scenario_a, village):
    session = SimulationSession.objects.create(scenario=scenario_a, village=village)
    assert session.village_id == village.id
    assert session.scenario_id == scenario_a.id
    assert session.health_officer is None
    assert session.status == SimulationSession.Status.NOT_STARTED


def test_simulation_event_is_village_scoped(scenario_a, village):
    session = SimulationSession.objects.create(scenario=scenario_a, village=village)
    event = SimulationEvent.objects.create(
        session=session,
        village=village,
        week_number=1,
        source_signals={"categories": {"FEVER": 2}, "status_label": "NORMAL"},
    )
    assert event.village_id == village.id
    assert event.session_id == session.id


def test_simulation_source_signal_is_village_scoped(scenario_a, village):
    session = SimulationSession.objects.create(scenario=scenario_a, village=village)
    event = SimulationEvent.objects.create(session=session, village=village, week_number=1)
    signal = SimulationSourceSignal.objects.create(
        event=event, village=village, source_type="CHW", value=2, reported=True
    )
    assert signal.village_id == village.id
    assert signal.event_id == event.id


def test_every_simulation_model_has_an_explicit_village_field():
    for model in ALL_SIMULATION_MODELS:
        field_names = {f.name for f in model._meta.get_fields()}
        assert "village" in field_names, f"{model.__name__} has no village field"


def test_reuses_the_existing_village_model_not_a_duplicate(scenario_a, village):
    assert type(scenario_a.village) is Village
    # No SimulationVillage (or similarly named) model exists in the app.
    import simulation.models as sim_models

    assert not hasattr(sim_models, "SimulationVillage")


def test_reuses_the_existing_user_model_for_health_officer(scenario_a, village, officer):
    session = SimulationSession.objects.create(
        scenario=scenario_a, village=village, health_officer=officer
    )
    assert type(session.health_officer) is User


# ---------------------------------------------------------------------------
# Missing != zero
# ---------------------------------------------------------------------------
def test_reported_zero_differs_from_not_reported(scenario_a, village):
    session = SimulationSession.objects.create(scenario=scenario_a, village=village)
    event = SimulationEvent.objects.create(session=session, village=village, week_number=1)

    zero = SimulationSourceSignal.objects.create(
        event=event, village=village, source_type="CHW", value=0, reported=True
    )
    missing = SimulationSourceSignal.objects.create(
        event=event, village=village, source_type="PHC", value=None, reported=False
    )

    assert zero.reported is True and zero.value == 0
    assert missing.reported is False and missing.value is None
    assert zero.value != missing.value or zero.reported != missing.reported


def test_a_missing_report_cannot_carry_a_numeric_value(scenario_a, village):
    """DB-level guarantee (CheckConstraint), not just application discipline."""

    session = SimulationSession.objects.create(scenario=scenario_a, village=village)
    event = SimulationEvent.objects.create(session=session, village=village, week_number=1)
    with pytest.raises(IntegrityError):
        SimulationSourceSignal.objects.create(
            event=event, village=village, source_type="PHC", value=5, reported=False
        )


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------
def test_seed_creates_the_three_required_village_a_scenarios():
    call_command("seed_demo")
    kvl = Village.objects.get(code="KVL")
    types = set(
        SimulationScenario.objects.filter(village=kvl, is_active=True).values_list(
            "scenario_type", flat=True
        )
    )
    assert {
        SimulationScenario.ScenarioType.EMERGING_SIGNAL,
        SimulationScenario.ScenarioType.STABLE_COMMUNITY,
        SimulationScenario.ScenarioType.MISSING_DATA,
    } <= types


def test_seed_creates_no_village_b_scenarios():
    call_command("seed_demo")
    ary = Village.objects.filter(code="ARY").first()
    if ary is not None:
        assert not SimulationScenario.objects.filter(village=ary).exists()


def test_seeded_missing_data_scenario_preserves_missing_vs_zero():
    call_command("seed_demo")
    scenario = SimulationScenario.objects.get(
        village__code="KVL", scenario_type=SimulationScenario.ScenarioType.MISSING_DATA
    )
    session = scenario.sessions.get(health_officer=None)
    week_3 = session.events.get(week_number=3)
    phc = week_3.per_source_signals.get(source_type="PHC")
    assert phc.reported is False
    assert phc.value is None


def test_reseeding_leaves_operational_counts_stable():
    """Idempotency + isolation together: re-running seed_demo (which now also
    seeds simulation scenarios) must not change operational row counts on
    the second pass, matching the existing pattern in
    test_worker_officer_reconciliation.py."""

    call_command("seed_demo")
    reports = CommunityReport.objects.count()
    alerts = Alert.objects.count()
    investigations = Investigation.objects.count()

    call_command("seed_demo")

    assert CommunityReport.objects.count() == reports
    assert Alert.objects.count() == alerts
    assert Investigation.objects.count() == investigations


# ---------------------------------------------------------------------------
# Read-only scenario API
# ---------------------------------------------------------------------------
def test_scenario_list_requires_authentication(api):
    assert api.get(SCENARIOS_URL).status_code == 401


def test_worker_cannot_reach_the_scenario_endpoint(worker_api):
    assert worker_api.get(SCENARIOS_URL).status_code == 403


def test_officer_a_receives_only_village_a_scenarios(officer_a_api, scenario_a, scenario_b):
    response = officer_a_api.get(SCENARIOS_URL)
    assert response.status_code == 200
    names = {row["name"] for row in response.data}
    assert scenario_a.name in names
    assert scenario_b.name not in names


def test_inactive_scenarios_are_not_returned(officer_a_api, scenario_a):
    scenario_a.is_active = False
    scenario_a.save(update_fields=["is_active"])
    response = officer_a_api.get(SCENARIOS_URL)
    assert scenario_a.name not in {row["name"] for row in response.data}


def test_scenario_response_shape(officer_a_api, scenario_a):
    response = officer_a_api.get(SCENARIOS_URL)
    row = next(r for r in response.data if r["id"] == scenario_a.id)
    assert row["scenario_type"] == "EMERGING_SIGNAL"
    assert row["village_code"] == scenario_a.village.code
    assert row["is_active"] is True
    assert row["version"] == 1
    assert "description" in row


# ---------------------------------------------------------------------------
# Cross-village negative test — mandatory (Phase 2 task §35)
# ---------------------------------------------------------------------------
def test_cross_village_negative_authorization(officer_a_api, scenario_a, scenario_b):
    """SIM-A-001 (Village A) is returned to Health Officer A; SIM-B-001
    (Village B) is not, and a direct attempt to retrieve it by id is denied
    with 403 — never a silent 200 with the wrong data, and never relying on
    the frontend to hide it."""

    response = officer_a_api.get(SCENARIOS_URL)
    ids = {row["id"] for row in response.data}
    assert scenario_a.id in ids
    assert scenario_b.id not in ids

    own_detail = officer_a_api.get(f"{SCENARIOS_URL}{scenario_a.id}/")
    assert own_detail.status_code == 200
    assert own_detail.data["name"] == scenario_a.name

    other_detail = officer_a_api.get(f"{SCENARIOS_URL}{scenario_b.id}/")
    assert other_detail.status_code == 403


# ===========================================================================
# Phase 3 — SimulationEngine / session execution
# ===========================================================================
from rest_framework.test import APIClient  # noqa: E402

from alerts.models import AgentRun, AlertEvidence, Feedback, SafetyCheck  # noqa: E402
from community.models import CommunityReportEntry, CommunitySignal  # noqa: E402
from simulation.services import (  # noqa: E402
    SimulationEngine,
    SimulationSessionNotRunning,
    SimulationVillageMismatch,
)

SESSIONS_URL = "/api/simulation/sessions/"

OPERATIONAL_MODELS = (
    CommunityReport,
    CommunityReportEntry,
    CommunitySignal,
    Alert,
    AlertEvidence,
    SafetyCheck,
    Investigation,
    Feedback,
    AgentRun,
)


def _operational_counts() -> dict[str, int]:
    return {model.__name__: model.objects.count() for model in OPERATIONAL_MODELS}


def _seeded_scenario(
    village, scenario_type=SimulationScenario.ScenarioType.EMERGING_SIGNAL, weeks=((1, 2), (2, 5))
) -> SimulationScenario:
    """A scenario with a real template session + weekly events + source
    signals — everything `SimulationEngine` needs, built directly (not via
    the real `seed_demo` command) so these tests stay fast and
    self-contained. Uses the real Phase 2 field names throughout."""

    scenario = SimulationScenario.objects.create(
        village=village,
        scenario_type=scenario_type,
        name=f"TEST-{scenario_type}-{village.code}",
        description="Test scenario for Phase 3 execution tests.",
    )
    template = SimulationSession.objects.create(scenario=scenario, village=village)
    for week_number, fever in weeks:
        event = SimulationEvent.objects.create(
            session=template,
            village=village,
            week_number=week_number,
            source_signals={"categories": {"FEVER": fever}, "status_label": "NORMAL"},
        )
        SimulationSourceSignal.objects.create(
            event=event, village=village, source_type="CHW", value=fever, reported=True
        )
    return scenario


@pytest.fixture
def seeded_scenario_a(village) -> SimulationScenario:
    return _seeded_scenario(village)


@pytest.fixture
def seeded_scenario_b(village_b) -> SimulationScenario:
    return _seeded_scenario(village_b)


@pytest.fixture
def officer_b_api(village_b):
    officer = User.objects.create_user(
        username="officer.simulation-test-b",
        password="demo1234",
        role=User.Role.HEALTH_OFFICER,
        village=village_b,
        district="Thiruvannamalai",
    )
    client = APIClient()
    client.force_authenticate(user=officer)
    return client


# A. Start session successfully
def test_start_session_successfully(officer_a_api, seeded_scenario_a):
    response = officer_a_api.post(
        SESSIONS_URL, {"scenario_id": seeded_scenario_a.id}, format="json"
    )

    assert response.status_code == 201
    assert response.data["status"] == "IN_PROGRESS"
    assert response.data["week"] == 1
    assert response.data["total_weeks"] == 2
    assert response.data["values"]["categories"]["FEVER"] == 2
    assert response.data["is_complete"] is False

    session = SimulationSession.objects.get(id=response.data["session_id"])
    assert session.health_officer is not None
    assert session.village_id == seeded_scenario_a.village_id
    assert session.status == SimulationSession.Status.IN_PROGRESS
    assert session.replay_position == 1


# B. Start session cross-village rejection
def test_start_session_cross_village_rejected(officer_a_api, seeded_scenario_b):
    response = officer_a_api.post(
        SESSIONS_URL, {"scenario_id": seeded_scenario_b.id}, format="json"
    )
    assert response.status_code == 403
    assert not SimulationSession.objects.filter(scenario=seeded_scenario_b, health_officer__isnull=False).exists()


def test_worker_cannot_start_a_session(worker_api, seeded_scenario_a):
    response = worker_api.post(
        SESSIONS_URL, {"scenario_id": seeded_scenario_a.id}, format="json"
    )
    assert response.status_code == 403


def test_start_session_requires_authentication(api, seeded_scenario_a):
    response = api.post(SESSIONS_URL, {"scenario_id": seeded_scenario_a.id}, format="json")
    assert response.status_code == 401


# C. Advance session successfully
def test_advance_session_successfully(officer_a_api, seeded_scenario_a):
    start = officer_a_api.post(
        SESSIONS_URL, {"scenario_id": seeded_scenario_a.id}, format="json"
    )
    session_id = start.data["session_id"]

    response = officer_a_api.post(f"{SESSIONS_URL}{session_id}/advance/")

    assert response.status_code == 200
    assert response.data["week"] == 2
    assert response.data["values"]["categories"]["FEVER"] == 5

    session = SimulationSession.objects.get(id=session_id)
    assert session.replay_position == 2


# D. Full session completion
def test_full_session_completion(officer_a_api, seeded_scenario_a):
    start = officer_a_api.post(
        SESSIONS_URL, {"scenario_id": seeded_scenario_a.id}, format="json"
    )
    session_id = start.data["session_id"]
    assert start.data["status"] == "IN_PROGRESS"

    final = officer_a_api.post(f"{SESSIONS_URL}{session_id}/advance/")

    assert final.status_code == 200
    assert final.data["status"] == "COMPLETED"
    assert final.data["is_complete"] is True

    session = SimulationSession.objects.get(id=session_id)
    assert session.status == SimulationSession.Status.COMPLETED


# E. Completed session cannot advance
def test_completed_session_cannot_advance_again(officer_a_api, seeded_scenario_a):
    start = officer_a_api.post(
        SESSIONS_URL, {"scenario_id": seeded_scenario_a.id}, format="json"
    )
    session_id = start.data["session_id"]
    officer_a_api.post(f"{SESSIONS_URL}{session_id}/advance/")  # -> COMPLETED

    response = officer_a_api.post(f"{SESSIONS_URL}{session_id}/advance/")

    assert response.status_code == 409


# F. Cross-village session access
def test_cross_village_session_advance_rejected(officer_a_api, officer_b_api, seeded_scenario_b):
    start = officer_b_api.post(
        SESSIONS_URL, {"scenario_id": seeded_scenario_b.id}, format="json"
    )
    session_id = start.data["session_id"]

    response = officer_a_api.post(f"{SESSIONS_URL}{session_id}/advance/")

    assert response.status_code == 403
    session = SimulationSession.objects.get(id=session_id)
    assert session.replay_position == 1  # untouched by the rejected attempt


# G. Service-layer scope enforcement (direct, not via HTTP)
def test_engine_start_rejects_cross_village_officer(village, seeded_scenario_b):
    officer_a = User.objects.create_user(
        username="officer.engine-test-a",
        password="demo1234",
        role=User.Role.HEALTH_OFFICER,
        village=village,
    )
    with pytest.raises(SimulationVillageMismatch):
        SimulationEngine.start(seeded_scenario_b, officer_a)
    assert not SimulationSession.objects.filter(
        scenario=seeded_scenario_b, health_officer=officer_a
    ).exists()


def test_engine_advance_rejects_mismatched_officer(village, village_b, seeded_scenario_a):
    officer_a = User.objects.create_user(
        username="officer.engine-test-a2",
        password="demo1234",
        role=User.Role.HEALTH_OFFICER,
        village=village,
    )
    officer_b = User.objects.create_user(
        username="officer.engine-test-b2",
        password="demo1234",
        role=User.Role.HEALTH_OFFICER,
        village=village_b,
    )
    state = SimulationEngine.start(seeded_scenario_a, officer_a)
    session = SimulationSession.objects.get(id=state["session_id"])

    with pytest.raises(SimulationVillageMismatch):
        SimulationEngine.advance(session, officer_b)

    session.refresh_from_db()
    assert session.replay_position == 1  # untouched


def test_engine_advance_rejects_a_completed_session(village, seeded_scenario_a):
    officer_a = User.objects.create_user(
        username="officer.engine-test-a3",
        password="demo1234",
        role=User.Role.HEALTH_OFFICER,
        village=village,
    )
    state = SimulationEngine.start(seeded_scenario_a, officer_a)
    session = SimulationSession.objects.get(id=state["session_id"])
    SimulationEngine.advance(session, officer_a)  # -> COMPLETED (2-week scenario)
    session.refresh_from_db()

    with pytest.raises(SimulationSessionNotRunning):
        SimulationEngine.advance(session, officer_a)


# H + I. Operational isolation and simulation-row state changes together
def test_full_simulation_run_leaves_operational_tables_untouched(
    officer_a_api, seeded_scenario_a
):
    before = _operational_counts()

    start = officer_a_api.post(
        SESSIONS_URL, {"scenario_id": seeded_scenario_a.id}, format="json"
    )
    session_id = start.data["session_id"]
    officer_a_api.post(f"{SESSIONS_URL}{session_id}/advance/")  # runs to COMPLETED

    assert _operational_counts() == before

    # I. Simulation rows themselves DID change, as expected.
    session = SimulationSession.objects.get(id=session_id)
    assert session.status == SimulationSession.Status.COMPLETED
    assert session.replay_position == 2
    assert session.health_officer is not None


# ===========================================================================
# Phase 4 — Multi-agent pipeline execution + visualization
# ===========================================================================
from unittest.mock import patch  # noqa: E402

from agents.llm import LLMUnavailable  # noqa: E402
from simulation.orchestrator import STAGE_ORDER, MultiAgentOrchestrator  # noqa: E402


def _week(
    week_number: int,
    categories: dict[str, float],
    sources: dict[str, tuple[float | None, bool]],
    status_label: str = "NORMAL",
) -> dict:
    return {
        "week": week_number,
        "categories": categories,
        "status_label": status_label,
        "sources": sources,
    }


def _build_pipeline_scenario(village, name: str, weeks: list[dict]) -> SimulationScenario:
    """Like `_seeded_scenario` but with full control over each week's
    category totals and per-source reported/value pairs — Phase 4's
    deterministic pipeline (unlike Phase 3's plain replay) actually reads
    that per-source detail, week over week, so these tests need to shape it
    precisely rather than reusing the single-source Phase 3 helper."""

    scenario = SimulationScenario.objects.create(
        village=village,
        scenario_type=SimulationScenario.ScenarioType.EMERGING_SIGNAL,
        name=name,
        description="Test scenario for Phase 4 pipeline tests.",
    )
    template = SimulationSession.objects.create(scenario=scenario, village=village)
    for week in weeks:
        event = SimulationEvent.objects.create(
            session=template,
            village=village,
            week_number=week["week"],
            source_signals={
                "categories": week["categories"],
                "status_label": week["status_label"],
            },
        )
        for source_type, (value, reported) in week["sources"].items():
            SimulationSourceSignal.objects.create(
                event=event,
                village=village,
                source_type=source_type,
                value=value,
                reported=reported,
            )
    return scenario


def _advance(api_client, session_id: int):
    return api_client.post(f"{SESSIONS_URL}{session_id}/advance/")


# A. Five stages, fixed order, every advance() call
def test_advance_runs_all_five_stages_in_fixed_order(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "PIPE-ORDER",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (3, True)}),
        ],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    response = _advance(officer_a_api, start.data["session_id"])

    assert response.status_code == 200
    names = [run["agent_name"] for run in response.data["agent_runs"]]
    assert names == list(STAGE_ORDER)
    assert names == ["ingestion", "signal_analysis", "correlation", "evidence", "safety"]


# B. Correct statuses: all 5 stages COMPLETE on a healthy week (Phase 6:
# safety is a real executed stage now, no longer a permanent WAITING stub —
# see tests/test_simulation_safety.py for the full Safety Engine suite).
def test_advance_produces_five_complete_stages(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "PIPE-STATUS",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    response = _advance(officer_a_api, start.data["session_id"])

    runs = {r["agent_name"]: r for r in response.data["agent_runs"]}
    assert runs["ingestion"]["status"] == "COMPLETE"
    assert runs["signal_analysis"]["status"] == "COMPLETE"
    assert runs["correlation"]["status"] == "COMPLETE"
    assert runs["evidence"]["status"] == "COMPLETE"
    assert runs["safety"]["status"] == "COMPLETE"
    assert runs["safety"]["output"]["gate_result"] in {"PASS", "BLOCK", "INSUFFICIENT"}


# C. Rich structured JSON, not just prose
def test_agent_run_outputs_are_structured_not_prose(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "PIPE-STRUCTURED",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (2, True)}),
            _week(2, {"FEVER": 5}, {"CHW": (5, True), "PHC": (5, True)}),
        ],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    response = _advance(officer_a_api, start.data["session_id"])
    runs = {r["agent_name"]: r for r in response.data["agent_runs"]}

    assert set(runs["ingestion"]["output"]) >= {
        "sources",
        "reported_source_count",
        "missing_source_count",
    }
    assert set(runs["signal_analysis"]["output"]) >= {
        "primary_signal",
        "trend",
        "current_value",
        "previous_value",
        "explanation",
    }
    assert set(runs["correlation"]["output"]) >= {"relationships"}
    assert isinstance(runs["correlation"]["output"]["relationships"], list)
    assert set(runs["evidence"]["output"]) >= {"source_relationships", "reporting_summary"}
    for run in runs.values():
        assert isinstance(run["input"], dict)
        assert isinstance(run["output"], dict)


# D. duration_ms present for every executed stage, including safety
# (Phase 6: safety now genuinely runs, so it is timed like every other
# stage rather than persisted with duration_ms=None as the old WAITING
# stub was).
def test_duration_ms_present_for_all_five_executed_stages(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "PIPE-DURATION",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    response = _advance(officer_a_api, start.data["session_id"])
    runs = {r["agent_name"]: r for r in response.data["agent_runs"]}

    for name in ("ingestion", "signal_analysis", "correlation", "evidence", "safety"):
        assert runs[name]["duration_ms"] is not None
        assert runs[name]["duration_ms"] >= 0


# E. Deterministic trend survives LLM unavailability
def test_trend_unaffected_by_llm_unavailable(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "PIPE-LLM-DOWN",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")

    with patch("simulation.orchestrator.get_llm_client") as mock_get_client:
        mock_get_client.return_value.summarise.side_effect = LLMUnavailable("down for test")
        response = _advance(officer_a_api, start.data["session_id"])

    signal_output = next(
        r for r in response.data["agent_runs"] if r["agent_name"] == "signal_analysis"
    )["output"]
    assert signal_output["trend"] == "STABLE"  # 2 -> 3 is below the escalation threshold
    assert signal_output["explanation_used_llm"] is False


# F. Deterministic trend survives an LLM that contradicts it
def test_trend_unaffected_by_llm_contradiction(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "PIPE-LLM-CONTRADICT",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")

    with patch("simulation.orchestrator.get_llm_client") as mock_get_client:
        mock_get_client.return_value.summarise.return_value = (
            "URGENT: this is a confirmed SIGNAL_DETECTED outbreak, escalate immediately."
        )
        response = _advance(officer_a_api, start.data["session_id"])

    signal_output = next(
        r for r in response.data["agent_runs"] if r["agent_name"] == "signal_analysis"
    )["output"]
    # The deterministic classification is untouched even though the LLM text
    # claims a different (and more alarming) trend.
    assert signal_output["trend"] == "STABLE"
    assert signal_output["explanation_used_llm"] is True
    assert "confirmed" in signal_output["explanation"]


# G. Correlation: SUPPORTING / CONFLICTING / INSUFFICIENT
def test_correlation_classifies_supporting_conflicting_insufficient(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "PIPE-CORRELATION",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHARMACY": (5, True)}),
            _week(
                2,
                {"FEVER": 4},
                {
                    "CHW": (4, True),  # up, same direction as primary -> SUPPORTING
                    "PHARMACY": (1, True),  # down, opposite direction -> CONFLICTING
                    "SCHOOL": (3, True),  # first appearance, no baseline -> INSUFFICIENT
                },
            ),
        ],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    response = _advance(officer_a_api, start.data["session_id"])
    relationships = {
        r["source"]: r["relationship"]
        for r in next(
            run for run in response.data["agent_runs"] if run["agent_name"] == "correlation"
        )["output"]["relationships"]
    }

    assert relationships["CHW"] == "SUPPORTING"
    assert relationships["PHARMACY"] == "CONFLICTING"
    assert relationships["SCHOOL"] == "INSUFFICIENT"


def test_correlation_marks_unreported_source_insufficient(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "PIPE-MISSING-CORRELATION",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (2, True)}),
            _week(2, {"FEVER": 4}, {"CHW": (4, True), "PHC": (None, False)}),
        ],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    response = _advance(officer_a_api, start.data["session_id"])
    relationships = {
        r["source"]: r["relationship"]
        for r in next(
            run for run in response.data["agent_runs"] if run["agent_name"] == "correlation"
        )["output"]["relationships"]
    }
    assert relationships["PHC"] == "INSUFFICIENT"


# H. Missing != zero survives ingestion into the pipeline output
def test_missing_data_preserved_through_ingestion_stage(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "PIPE-MISSING-INGESTION",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (None, False)}),
        ],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    response = _advance(officer_a_api, start.data["session_id"])
    ingestion_output = next(
        r for r in response.data["agent_runs"] if r["agent_name"] == "ingestion"
    )["output"]

    assert ingestion_output["sources"]["PHC"]["reported"] is False
    assert ingestion_output["sources"]["PHC"]["value"] is None
    assert ingestion_output["missing_source_count"] == 1
    assert ingestion_output["reported_source_count"] == 1


# I. Stage failure is handled safely, not silently promoted to success
def test_stage_failure_does_not_mark_later_stages_as_succeeding(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "PIPE-STAGE-FAILURE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {}, {"CHW": (3, True)}),  # no categories -> signal_analysis fails
        ],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    response = _advance(officer_a_api, start.data["session_id"])

    assert response.status_code == 200  # the scenario replay itself still advances
    runs = {r["agent_name"]: r for r in response.data["agent_runs"]}

    assert runs["ingestion"]["status"] == "COMPLETE"
    assert runs["signal_analysis"]["status"] == "FAILED"
    assert isinstance(runs["signal_analysis"]["output"].get("error"), str)
    assert runs["signal_analysis"]["duration_ms"] is not None  # it genuinely attempted to run

    for name in ("correlation", "evidence", "safety"):
        assert runs[name]["status"] == "FAILED"
        assert runs[name]["duration_ms"] is None  # never actually executed
        assert "error" in runs[name]["output"]

    # No raw traceback ever reaches the API response.
    for run in runs.values():
        payload = str(run["output"])
        assert "Traceback" not in payload
        assert "line " not in payload

    session = SimulationSession.objects.get(id=start.data["session_id"])
    assert session.replay_position == 2  # a pipeline failure does not block replay progress


# J. Cross-village enforcement holds with the pipeline attached
def test_cross_village_advance_creates_no_agent_runs(officer_a_api, officer_b_api, village_b):
    scenario = _build_pipeline_scenario(
        village_b,
        "PIPE-CROSS-VILLAGE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    start = officer_b_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    session_id = start.data["session_id"]

    response = officer_a_api.post(f"{SESSIONS_URL}{session_id}/advance/")

    assert response.status_code == 403
    assert SimulationAgentRun.objects.filter(session_id=session_id).count() == 0


# K. Every persisted AgentRun is scoped to the session's own village
def test_agent_run_is_scoped_to_the_session_village(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "PIPE-VILLAGE-SCOPE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    _advance(officer_a_api, start.data["session_id"])

    runs = SimulationAgentRun.objects.filter(session_id=start.data["session_id"])
    assert runs.count() == 5
    assert all(run.village_id == village.id for run in runs)


# L. Operational isolation, extended: agent-run rows are the only thing that grows
def test_pipeline_execution_leaves_operational_tables_untouched(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "PIPE-ISOLATION",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    before = _operational_counts()
    before_agent_runs = SimulationAgentRun.objects.count()

    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    _advance(officer_a_api, start.data["session_id"])

    assert _operational_counts() == before  # includes the operational AgentRun model
    assert SimulationAgentRun.objects.count() == before_agent_runs + 5
    assert not Alert.objects.exists() or Alert.objects.count() == before["Alert"]


# M. A full multi-week run produces exactly 5 agent runs per *advanced* week.
# 5 seeded weeks -> 1 `start()` (no pipeline, per §N) + 4 `advance()` calls
# (pipeline runs on each) = 4 x 5 = 20 `SimulationAgentRun` rows.
def test_full_run_produces_twenty_agent_runs_across_four_advances(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "PIPE-FULL-RUN",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (6, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True)}),
            _week(3, {"FEVER": 5}, {"CHW": (5, True), "PHC": (7, True)}),
            _week(4, {"FEVER": 8}, {"CHW": (8, True), "PHC": (9, True)}),
            _week(5, {"FEVER": 12}, {"CHW": (12, True), "PHC": (10, True)}),
        ],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    session_id = start.data["session_id"]

    trends = []
    response = start
    while not response.data["is_complete"]:
        response = _advance(officer_a_api, session_id)
        trends.append(
            next(r for r in response.data["agent_runs"] if r["agent_name"] == "signal_analysis")[
                "output"
            ]["trend"]
        )

    assert response.data["status"] == "COMPLETED"
    assert trends == ["STABLE", "INCREASING", "SIGNAL_DETECTED", "INCREASING"]
    assert SimulationAgentRun.objects.filter(session_id=session_id).count() == 20  # 4 advances x 5


# N. start() itself never runs the pipeline (week 1 has no "previous week")
def test_start_session_returns_empty_agent_runs(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "PIPE-START-EMPTY",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    response = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")

    assert response.data["agent_runs"] == []
    assert SimulationAgentRun.objects.filter(session_id=response.data["session_id"]).count() == 0


# O. Orchestrator pipeline order is a fixed constant, not derived at runtime
def test_stage_order_is_fixed_and_matches_orchestrator_constant():
    assert STAGE_ORDER == (
        "ingestion",
        "signal_analysis",
        "correlation",
        "evidence",
        "safety",
    )
    assert callable(MultiAgentOrchestrator.run_pipeline)


# ===========================================================================
# Phase 5 — Signal Intelligence + Evidence Constellation
# ===========================================================================
from simulation.intelligence import (  # noqa: E402
    _TREND_PHRASES,
    _VERIFICATION_BY_STRENGTH,
    SimulationIntelligenceSerializer,
    build_intelligence,
)

INTELLIGENCE_FIELDS = ("timeline", "constellation", "source_fusion", "data_quality", "explanation")


def _intelligence_url(session_id: int) -> str:
    return f"{SESSIONS_URL}{session_id}/intelligence/"


def _start_and_advance(api_client, scenario_id: int, times: int):
    """Starts a session and advances it `times` times, returning the final
    HTTP response (the intelligence endpoint is exercised separately)."""

    response = api_client.post(SESSIONS_URL, {"scenario_id": scenario_id}, format="json")
    session_id = response.data["session_id"]
    for _ in range(times):
        response = _advance(api_client, session_id)
    return session_id, response


# A + B. Endpoint success and payload structure
def test_intelligence_endpoint_success_and_structure(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "INTEL-STRUCTURE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    response = officer_a_api.get(_intelligence_url(session_id))

    assert response.status_code == 200
    for field in INTELLIGENCE_FIELDS:
        assert field in response.data
    assert isinstance(response.data["timeline"], list)
    assert isinstance(response.data["constellation"], list)
    assert isinstance(response.data["source_fusion"], list)
    assert isinstance(response.data["data_quality"], dict)
    assert isinstance(response.data["explanation"], dict)


# C. Timeline uses actual counts, never a normalized percentage/index
def test_timeline_uses_actual_synthetic_counts(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "INTEL-ACTUAL-COUNTS",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True)}),
            _week(3, {"FEVER": 5}, {"CHW": (5, True), "PHC": (9, True)}),
            _week(4, {"FEVER": 8}, {"CHW": (8, True), "PHC": (14, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 3)

    response = officer_a_api.get(_intelligence_url(session_id))
    values = [row["value"] for row in response.data["timeline"]]

    assert values == [2, 3, 5, 8]  # the actual seeded counts, not a percentage
    assert all(0 <= v <= 100 for v in values)  # incidental, not a 0-150% normalized band
    for row in response.data["timeline"]:
        assert row["primary_signal"] == "FEVER"


# D. A genuinely absent category value is null, never fabricated to 0 or hidden
def test_timeline_shows_null_not_zero_for_a_genuinely_missing_category(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "INTEL-MISSING-CATEGORY",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {}, {"CHW": (3, True)}),  # FEVER key genuinely absent this week
        ],
    )
    session_id, response = _start_and_advance(officer_a_api, scenario.id, 1)
    # signal_analysis fails on an empty categories dict (Phase 4 behaviour) —
    # the timeline must still show week 2 with a null value, not a fabricated
    # number and not a silently dropped row.
    assert response.status_code == 200

    intelligence = officer_a_api.get(_intelligence_url(session_id)).data
    week_2 = next(row for row in intelligence["timeline"] if row["week"] == 2)
    assert week_2["value"] is None
    assert week_2["primary_signal"] == "FEVER"  # still the session's known primary signal


# E. reported=True, value=0 remains a real, visible 0 — never null
def test_timeline_preserves_a_genuine_reported_zero(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "INTEL-REPORTED-ZERO",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 0}, {"CHW": (0, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    intelligence = officer_a_api.get(_intelligence_url(session_id)).data
    week_2 = next(row for row in intelligence["timeline"] if row["week"] == 2)
    assert week_2["value"] == 0
    assert week_2["value"] is not None
    chw = next(s for s in week_2["sources"] if s["source_type"] == "CHW")
    assert chw["reported"] is True
    assert chw["value"] == 0


# F. Constellation SUPPORTING
def test_constellation_marks_agreeing_source_supporting(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "INTEL-SUPPORTING",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 4}, {"CHW": (4, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)
    intelligence = officer_a_api.get(_intelligence_url(session_id)).data
    relation = next(c["relation"] for c in intelligence["constellation"] if c["source"] == "CHW")
    assert relation == "SUPPORTING"
    assert "CHW" in intelligence["explanation"]["sources_supporting"]


# G. Constellation CONFLICTING
def test_constellation_marks_disagreeing_source_conflicting(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "INTEL-CONFLICTING",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHARMACY": (5, True)}),
            _week(2, {"FEVER": 4}, {"CHW": (4, True), "PHARMACY": (1, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)
    intelligence = officer_a_api.get(_intelligence_url(session_id)).data
    relation = next(c["relation"] for c in intelligence["constellation"] if c["source"] == "PHARMACY")
    assert relation == "CONFLICTING"
    assert "PHARMACY" in intelligence["explanation"]["sources_conflicting"]
    assert intelligence["explanation"]["evidence_strength"] == "MODERATE"
    assert "disagreement" in intelligence["explanation"]["routed_reason"]


# H. Constellation INSUFFICIENT
def test_constellation_marks_unreported_source_insufficient(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "INTEL-INSUFFICIENT",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (2, True)}),
            _week(2, {"FEVER": 4}, {"CHW": (4, True), "PHC": (None, False)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)
    intelligence = officer_a_api.get(_intelligence_url(session_id)).data
    relation = next(c["relation"] for c in intelligence["constellation"] if c["source"] == "PHC")
    assert relation == "INSUFFICIENT"
    assert "PHC" in intelligence["explanation"]["sources_insufficient"]


# I. Data-quality formula: reported_weeks / expected_weeks
def test_data_quality_completeness_formula(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "INTEL-COMPLETENESS",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (1, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (2, True)}),
            _week(3, {"FEVER": 4}, {"CHW": (4, True), "PHC": (None, False)}),
            _week(4, {"FEVER": 5}, {"CHW": (5, True), "PHC": (None, False)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 3)
    intelligence = officer_a_api.get(_intelligence_url(session_id)).data

    phc_quality = next(s for s in intelligence["data_quality"]["sources"] if s["source"] == "PHC")
    assert phc_quality["reported_weeks"] == 2
    assert phc_quality["expected_weeks"] == 4
    assert phc_quality["completeness_pct"] == 50  # 2 / 4

    chw_quality = next(s for s in intelligence["data_quality"]["sources"] if s["source"] == "CHW")
    assert chw_quality["completeness_pct"] == 100  # 4 / 4

    # Overall: (4 reported CHW + 2 reported PHC) / (4 expected x 2 sources)
    assert intelligence["data_quality"]["completeness_pct"] == 75


# J. Missing periods are explicitly listed, never silently dropped
def test_data_quality_lists_missing_periods_explicitly(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "INTEL-MISSING-PERIODS",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (2, True)}),
            _week(3, {"FEVER": 4}, {"CHW": (4, True), "PHC": (None, False)}),
            _week(4, {"FEVER": 5}, {"CHW": (5, True), "PHC": (None, False)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 3)
    intelligence = officer_a_api.get(_intelligence_url(session_id)).data

    assert intelligence["data_quality"]["missing"] == ["PHC — Week 3", "PHC — Week 4"]
    assert intelligence["data_quality"]["window_label"] == "Weeks 1-4"


# K. Source disagreement — deterministic relationships from real per-week data
def test_source_disagreement_scenario_relationships(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "INTEL-DISAGREEMENT",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHARMACY": (5, True)}),
            _week(2, {"FEVER": 4}, {"CHW": (4, True), "PHARMACY": (1, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)
    intelligence = officer_a_api.get(_intelligence_url(session_id)).data

    relations = {c["source"]: c["relation"] for c in intelligence["constellation"]}
    assert relations == {"CHW": "SUPPORTING", "PHARMACY": "CONFLICTING"}
    assert "disagreement" in intelligence["explanation"]["routed_reason"]
    assert intelligence["explanation"]["evidence_strength"] == "MODERATE"
    # No diagnosis, no outbreak language anywhere in the explanation.
    explanation_text = json.dumps(intelligence["explanation"]).lower()
    assert "outbreak" not in explanation_text
    assert "diagnos" not in explanation_text


# L. Stable scenario — no false escalation
def test_stable_scenario_shows_no_false_escalation(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "INTEL-STABLE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(3, {"FEVER": 3}, {"CHW": (3, True), "PHC": (5, True)}),
            _week(4, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 3)
    intelligence = officer_a_api.get(_intelligence_url(session_id)).data

    statuses = [row["status"] for row in intelligence["timeline"]]
    assert "SIGNAL_DETECTED" not in statuses
    assert "INCREASING" not in statuses
    assert intelligence["explanation"]["evidence_strength"] == "WEAK"
    assert "outbreak" not in json.dumps(intelligence["explanation"]).lower()


# M. Cross-village access is rejected with 403, not partial data
def test_intelligence_cross_village_access_rejected(officer_a_api, officer_b_api, village_b):
    scenario = _build_pipeline_scenario(
        village_b,
        "INTEL-CROSS-VILLAGE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_b_api, scenario.id, 1)

    response = officer_a_api.get(_intelligence_url(session_id))

    assert response.status_code == 403
    assert "timeline" not in response.data  # never partial data alongside the error


def test_officer_b_own_village_intelligence_succeeds(officer_b_api, village_b):
    scenario = _build_pipeline_scenario(
        village_b,
        "INTEL-OWN-VILLAGE-B",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_b_api, scenario.id, 1)
    response = officer_b_api.get(_intelligence_url(session_id))
    assert response.status_code == 200


def test_worker_cannot_reach_the_intelligence_endpoint(officer_a_api, village, worker):
    # A dedicated `APIClient()` here, not the shared `worker_api` fixture —
    # `worker_api` and `officer_a_api` both build on the same underlying
    # `api` fixture instance, so requesting both in one test would have the
    # second one silently re-authenticate the first's client.
    scenario = _build_pipeline_scenario(
        village,
        "INTEL-WORKER-DENIED",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    dedicated_worker_client = APIClient()
    dedicated_worker_client.force_authenticate(user=worker)
    response = dedicated_worker_client.get(_intelligence_url(session_id))
    assert response.status_code == 403


# N + O. Simulation isolation — read-only w.r.t. every operational table
def test_intelligence_endpoint_leaves_operational_tables_untouched(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "INTEL-ISOLATION",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    before = _operational_counts()
    response = officer_a_api.get(_intelligence_url(session_id))
    response = officer_a_api.get(_intelligence_url(session_id))  # called twice: still read-only

    assert response.status_code == 200
    assert _operational_counts() == before
    assert not Alert.objects.exists()


# P. No patient-identity fields anywhere in the payload
def test_intelligence_payload_contains_no_patient_identity_fields(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "INTEL-NO-PATIENT-DATA",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)
    intelligence = officer_a_api.get(_intelligence_url(session_id)).data

    payload_text = json.dumps(intelligence).lower()
    for forbidden in ("patient", "phone", "aadhaar", "date_of_birth", "address", "name\":"):
        assert forbidden not in payload_text


# Q. Deterministic calculation is unaffected by LLM behaviour
def test_intelligence_constellation_and_quality_unaffected_by_llm(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "INTEL-LLM-INDEPENDENCE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHARMACY": (5, True)}),
            _week(2, {"FEVER": 4}, {"CHW": (4, True), "PHARMACY": (1, True)}),
        ],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    session_id = start.data["session_id"]

    with patch("simulation.orchestrator.get_llm_client") as mock_get_client:
        mock_get_client.return_value.summarise.return_value = (
            "This is a confirmed outbreak — AI confidence 99%."
        )
        _advance(officer_a_api, session_id)

    intelligence = officer_a_api.get(_intelligence_url(session_id)).data
    relations = {c["source"]: c["relation"] for c in intelligence["constellation"]}
    assert relations == {"CHW": "SUPPORTING", "PHARMACY": "CONFLICTING"}
    assert intelligence["data_quality"]["completeness_pct"] == 100
    # The LLM's fabricated text never reaches any of Phase 5's five
    # original deterministic fields.
    phase_5_fields_text = json.dumps(
        {k: v for k, v in intelligence.items() if k != "safety"}
    ).lower()
    assert "outbreak" not in phase_5_fields_text
    assert "confidence" not in phase_5_fields_text
    # Phase 6: the injected text does not silently pass — the Safety Engine
    # (added in Phase 6) catches it and BLOCKs, and even there only the
    # short matched phrase is ever quoted back, never the LLM's full
    # fabricated sentence (so "confidence" never appears anywhere either).
    assert intelligence["safety"]["gate_result"] == "BLOCK"
    payload_text = json.dumps(intelligence).lower()
    assert "confidence" not in payload_text


# No "AI confidence" anywhere in the intelligence payload (task §17/§35)
def test_intelligence_payload_never_contains_ai_confidence_language():
    session = SimulationSession(replay_position=0)  # unsaved; used only for the static text scan
    forbidden_terms = ("ai confidence", "model confidence", "confidence score", "confidence %")
    static_text = " ".join(_VERIFICATION_BY_STRENGTH.values()) + " " + " ".join(_TREND_PHRASES.values())
    for term in forbidden_terms:
        assert term not in static_text.lower()


def test_intelligence_serializer_data_matches_build_intelligence(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "INTEL-SERIALIZER-PARITY",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)
    session = SimulationSession.objects.get(id=session_id)
    assert SimulationIntelligenceSerializer(session).data == build_intelligence(session)
