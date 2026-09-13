"""Phase 10 — Intelligence Quality Monitoring backend tests.

Reuses the Phase 4 scenario-building helpers and village/officer fixtures
from `test_simulation.py`, and the shared `officer`/`officer_api`
(district-wide) fixtures from `conftest.py`.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from simulation.models import (
    SimulationEvent,
    SimulationResult,
    SimulationScenario,
    SimulationSession,
    SimulationSourceSignal,
)

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

MONITORING_URL = "/api/simulation/monitoring/"

_DEFAULT_WEEKS = [
    _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
    _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True)}),
    _week(3, {"FEVER": 5}, {"CHW": (5, True), "PHC": (9, True)}),
    _week(4, {"FEVER": 9}, {"CHW": (9, True), "PHC": (14, True)}),
]


def _investigation_url(session_id: int) -> str:
    return f"{SESSIONS_URL}{session_id}/investigation/"


def _decision_url(session_id: int) -> str:
    return f"{SESSIONS_URL}{session_id}/investigation/decision/"


def _feedback_url(session_id: int) -> str:
    return f"{SESSIONS_URL}{session_id}/investigation/feedback/"


def _distinct_scenario(village, name: str, weeks: list[dict], version: int) -> SimulationScenario:
    """`_build_pipeline_scenario` always creates `EMERGING_SIGNAL` version 1
    — fine for one scenario per village, but this file needs several
    coexisting scenarios in the SAME village, and `(village, scenario_type,
    version)` is unique. Same body as that shared helper, with `version`
    exposed as a parameter (which the shared one doesn't need, since every
    other test file only ever builds one scenario per village)."""

    scenario = SimulationScenario.objects.create(
        village=village,
        scenario_type=SimulationScenario.ScenarioType.EMERGING_SIGNAL,
        name=name,
        version=version,
        description="Test scenario for Phase 10 monitoring tests.",
    )
    template = SimulationSession.objects.create(scenario=scenario, village=village)
    for week in weeks:
        event = SimulationEvent.objects.create(
            session=template,
            village=village,
            week_number=week["week"],
            source_signals={"categories": week["categories"], "status_label": week["status_label"]},
        )
        for source_type, (value, reported) in week["sources"].items():
            SimulationSourceSignal.objects.create(
                event=event, village=village, source_type=source_type, value=value, reported=reported
            )
    return scenario


def _start_and_advance(api_client, scenario, times: int) -> int:
    response = api_client.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    session_id = response.data["session_id"]
    for _ in range(times):
        _advance(api_client, session_id)
    return session_id


# ===========================================================================
# A. Village scope / isolation
# ===========================================================================
def test_monitoring_returns_only_officer_village_data(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "MON-SCOPE", _DEFAULT_WEEKS)
    _start_and_advance(officer_a_api, scenario, 1)

    response = officer_a_api.get(MONITORING_URL)
    assert response.status_code == 200
    assert response.data["scope"]["village_code"] == village.code


def test_officer_a_and_officer_b_see_disjoint_village_metrics(officer_a_api, officer_b_api, village, village_b):
    scenario_a = _build_pipeline_scenario(village, "MON-A-ONLY", _DEFAULT_WEEKS)
    scenario_b = _build_pipeline_scenario(village_b, "MON-B-ONLY", _DEFAULT_WEEKS)
    _start_and_advance(officer_a_api, scenario_a, 3)
    _start_and_advance(officer_b_api, scenario_b, 3)

    response_a = officer_a_api.get(MONITORING_URL)
    response_b = officer_b_api.get(MONITORING_URL)

    assert response_a.data["scope"]["village_code"] == village.code
    assert response_a.data["sessions"]["total"] == 1
    assert response_b.data["scope"]["village_code"] == village_b.code
    assert response_b.data["sessions"]["total"] == 1


def test_district_wide_officer_gets_explicit_400_not_cross_village_data(officer_api):
    response = officer_api.get(MONITORING_URL)
    assert response.status_code == 400


def test_worker_role_rejected(worker_api):
    response = worker_api.get(MONITORING_URL)
    assert response.status_code == 403


# ===========================================================================
# B. Counts match direct aggregation (independent of the view's own logic)
# ===========================================================================
def test_monitoring_counts_match_direct_database_aggregation(officer_a_api, village):
    scenario1 = _distinct_scenario(village, "MON-COUNTS-1", _DEFAULT_WEEKS, 1)
    scenario2 = _distinct_scenario(village, "MON-COUNTS-2", _DEFAULT_WEEKS, 2)
    scenario3 = _distinct_scenario(village, "MON-COUNTS-3", _DEFAULT_WEEKS, 3)

    session1 = _start_and_advance(officer_a_api, scenario1, 3)
    session2 = _start_and_advance(officer_a_api, scenario2, 3)
    officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario3.id}, format="json")  # never advanced

    officer_a_api.get(_investigation_url(session1))
    officer_a_api.post(_decision_url(session1), {"decision": "CONTINUE_MONITORING"}, format="json")
    officer_a_api.patch(
        _feedback_url(session1),
        {"usefulness": "USEFUL", "evidence_sufficiency": "SUFFICIENT"},
        format="json",
    )

    officer_a_api.get(_investigation_url(session2))
    officer_a_api.post(_decision_url(session2), {"decision": "VERIFY_WITH_PHC"}, format="json")
    # session2 deliberately gets NO feedback.

    response = officer_a_api.get(MONITORING_URL)
    assert response.status_code == 200
    data = response.data

    real_sessions = SimulationSession.objects.filter(village=village, health_officer__isnull=False)
    assert data["sessions"]["total"] == real_sessions.count() == 3
    assert data["sessions"]["completed"] == real_sessions.filter(status="COMPLETED").count() == 2

    assert data["investigations"]["started"] == 2
    assert data["investigations"]["decisions_recorded"] == 2
    assert data["feedback"]["submitted"] == 1
    assert data["feedback"]["response_rate"] == {
        "numerator": 1,
        "denominator": 2,
        "percentage": 50,
        "limited_sample": True,
    }

    results = SimulationResult.objects.filter(village=village, is_what_if=False)
    assert data["evidence"]["STRONG"] == results.filter(evidence_strength="STRONG").count()
    assert data["evidence"]["MODERATE"] == results.filter(evidence_strength="MODERATE").count()
    assert data["evidence"]["WEAK"] == results.filter(evidence_strength="WEAK").count()
    assert data["evidence"]["total"] == results.count()

    assert data["safety"]["PASS"] == results.filter(gate_result="PASS").count()
    assert data["safety"]["INSUFFICIENT"] == results.filter(gate_result="INSUFFICIENT").count()
    assert data["safety"]["BLOCK"] == results.filter(gate_result="BLOCK").count()
    assert data["safety"]["total"] == results.count()

    assert data["decisions"]["CONTINUE_MONITORING"] == 1
    assert data["decisions"]["VERIFY_WITH_PHC"] == 1
    assert data["decisions"]["ESCALATE_FOR_HUMAN_REVIEW"] == 0


def test_denominators_are_present_and_correct_for_every_ratio(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "MON-DENOM", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)
    officer_a_api.get(_investigation_url(session_id))
    officer_a_api.post(_decision_url(session_id), {"decision": "CONTINUE_MONITORING"}, format="json")
    officer_a_api.patch(_feedback_url(session_id), {"usefulness": "USEFUL"}, format="json")

    response = officer_a_api.get(MONITORING_URL)
    ratio = response.data["feedback"]["response_rate"]
    assert ratio["denominator"] == 1
    assert ratio["numerator"] == 1
    assert ratio["percentage"] == 100

    usefulness_ratio = response.data["feedback"]["usefulness"]["USEFUL"]
    assert usefulness_ratio["denominator"] == 1  # denominator = feedback submitted
    assert usefulness_ratio["numerator"] == 1


# ===========================================================================
# C. Limited-sample presentation (task §22)
# ===========================================================================
def test_limited_sample_flagged_below_minimum(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "MON-LIMITED", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)
    officer_a_api.get(_investigation_url(session_id))
    officer_a_api.post(_decision_url(session_id), {"decision": "CONTINUE_MONITORING"}, format="json")
    officer_a_api.patch(_feedback_url(session_id), {"usefulness": "USEFUL"}, format="json")

    response = officer_a_api.get(MONITORING_URL)
    assert response.data["feedback"]["response_rate"]["limited_sample"] is True


def test_zero_denominator_never_crashes_and_reports_limited_sample(officer_a_api, village):
    # No sessions at all for this village yet.
    response = officer_a_api.get(MONITORING_URL)
    assert response.status_code == 200
    assert response.data["sessions"]["total"] == 0
    assert response.data["feedback"]["response_rate"] == {
        "numerator": 0,
        "denominator": 0,
        "percentage": None,
        "limited_sample": True,
    }


# ===========================================================================
# D. Missing feedback never counted as negative
# ===========================================================================
def test_missing_feedback_excluded_from_usefulness_distribution(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "MON-MISSING-FB", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)
    officer_a_api.get(_investigation_url(session_id))
    officer_a_api.post(_decision_url(session_id), {"decision": "CONTINUE_MONITORING"}, format="json")
    # No feedback submitted for this investigation at all.

    response = officer_a_api.get(MONITORING_URL)
    usefulness = response.data["feedback"]["usefulness"]
    for value in ("VERY_USEFUL", "USEFUL", "PARTIALLY_USEFUL", "NOT_USEFUL"):
        assert usefulness[value]["numerator"] == 0


# ===========================================================================
# E. Source relationship tally
# ===========================================================================
def test_source_relationship_tally_reflects_persisted_correlation_output(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "MON-SOURCE-AGREE", _DEFAULT_WEEKS)
    _start_and_advance(officer_a_api, scenario, 3)

    response = officer_a_api.get(MONITORING_URL)
    tally = {entry["source"]: entry for entry in response.data["source_relationships"]}
    assert "CHW" in tally
    assert "PHC" in tally
    total_chw = sum(tally["CHW"][key] for key in ("SUPPORTING", "CONFLICTING", "INSUFFICIENT"))
    assert total_chw == 3  # one correlation run per advanced week


# ===========================================================================
# F. What-If / Replay must never contaminate metrics
# ===========================================================================
def test_what_if_does_not_contaminate_monitoring_metrics(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "MON-WHATIF", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)

    before = officer_a_api.get(MONITORING_URL).data
    officer_a_api.post(
        f"{SESSIONS_URL}{session_id}/what-if/", {"overrides": {"PHC": None}}, format="json"
    )
    after = officer_a_api.get(MONITORING_URL).data

    assert before["evidence"] == after["evidence"]
    assert before["safety"] == after["safety"]
    assert before["sessions"] == after["sessions"]


def test_replay_does_not_change_monitoring_metrics(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "MON-REPLAY", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)

    before = officer_a_api.get(MONITORING_URL).data
    officer_a_api.get(f"{SESSIONS_URL}{session_id}/replay/?week=2")
    after = officer_a_api.get(MONITORING_URL).data

    assert before == after


# ===========================================================================
# G. Operational isolation
# ===========================================================================
def test_monitoring_never_touches_operational_tables(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "MON-OPS-ISOLATION", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)
    officer_a_api.get(_investigation_url(session_id))
    officer_a_api.post(_decision_url(session_id), {"decision": "CONTINUE_MONITORING"}, format="json")
    officer_a_api.patch(_feedback_url(session_id), {"usefulness": "USEFUL"}, format="json")

    before = _operational_counts()
    officer_a_api.get(MONITORING_URL)
    after = _operational_counts()
    assert before == after


# ===========================================================================
# H. Decision alignment structure
# ===========================================================================
def test_decision_alignment_totals_are_internally_consistent(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "MON-ALIGN", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)
    officer_a_api.get(_investigation_url(session_id))
    officer_a_api.post(_decision_url(session_id), {"decision": "CONTINUE_MONITORING"}, format="json")

    response = officer_a_api.get(MONITORING_URL)
    alignment = response.data["decision_alignment"]
    assert alignment["total"] == alignment["aligned"] + alignment["differed"] + alignment["no_suggestion"]
    assert alignment["total"] == 1


# ===========================================================================
# I. No "AI confidence" / outbreak wording anywhere in the payload
# ===========================================================================
def test_no_banned_wording_in_monitoring_payload(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "MON-WORDING", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)
    officer_a_api.get(_investigation_url(session_id))
    officer_a_api.post(_decision_url(session_id), {"decision": "CONTINUE_MONITORING"}, format="json")

    response = officer_a_api.get(MONITORING_URL)
    payload_text = str(response.data).lower()
    for banned in ("ai confidence", "model confidence", "outbreak detected", "outbreak confirmed"):
        assert banned not in payload_text
