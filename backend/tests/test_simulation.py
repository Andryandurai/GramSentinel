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
