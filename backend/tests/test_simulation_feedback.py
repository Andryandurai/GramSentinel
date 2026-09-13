"""Phase 10 — Officer Feedback backend tests.

Reuses the Phase 4 scenario-building helpers and village/officer fixtures
from `test_simulation.py` (see that file's own docstrings) rather than
redefining them.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from simulation.models import (
    SimulationAgentRun,
    SimulationFeedback,
    SimulationInvestigation,
    SimulationResult,
    SimulationSafetyCheck,
)

from tests.test_simulation import (
    SESSIONS_URL,
    _advance,
    _build_pipeline_scenario,
    _week,
    officer_a_api,  # noqa: F401 - reused fixture
    officer_b_api,  # noqa: F401 - reused fixture
    village_b,  # noqa: F401 - reused fixture
)

User = get_user_model()
pytestmark = pytest.mark.django_db

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


def _start_and_advance(api_client, scenario, times: int) -> int:
    response = api_client.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    session_id = response.data["session_id"]
    for _ in range(times):
        _advance(api_client, session_id)
    return session_id


def _open_investigation(api_client, session_id: int) -> None:
    response = api_client.get(_investigation_url(session_id))
    assert response.status_code == 200


# ===========================================================================
# A. Missing vs. submitted (task §23: "missing != not useful")
# ===========================================================================
def test_missing_feedback_is_distinct_from_any_negative_choice(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "FB-MISSING", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)
    _open_investigation(officer_a_api, session_id)

    response = officer_a_api.get(_feedback_url(session_id))
    assert response.status_code == 200
    assert response.data["submitted"] is False
    assert response.data["usefulness"] == ""
    assert SimulationFeedback.objects.filter(session_id=session_id).count() == 0


# ===========================================================================
# B. Creation / update / one-per-investigation
# ===========================================================================
def test_feedback_creation(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "FB-CREATE", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)
    _open_investigation(officer_a_api, session_id)

    response = officer_a_api.patch(
        _feedback_url(session_id),
        {
            "usefulness": "USEFUL",
            "evidence_sufficiency": "PARTIALLY_SUFFICIENT",
            "recommendation_helpful": "YES",
            "additional_verification_required": "YES",
            "comment": "Helpful summary of the week.",
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.data["submitted"] is True
    assert response.data["usefulness"] == "USEFUL"
    assert SimulationFeedback.objects.filter(session_id=session_id).count() == 1


def test_feedback_update_reuses_the_same_row(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "FB-UPDATE", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)
    _open_investigation(officer_a_api, session_id)

    officer_a_api.patch(_feedback_url(session_id), {"usefulness": "USEFUL"}, format="json")
    first_id = SimulationFeedback.objects.get(session_id=session_id).id

    response = officer_a_api.patch(_feedback_url(session_id), {"usefulness": "NOT_USEFUL"}, format="json")
    assert response.status_code == 200
    assert response.data["usefulness"] == "NOT_USEFUL"

    assert SimulationFeedback.objects.filter(session_id=session_id).count() == 1
    assert SimulationFeedback.objects.get(session_id=session_id).id == first_id


def test_one_feedback_per_investigation_enforced_even_with_repeated_partial_patches(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "FB-ONEROW", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)
    _open_investigation(officer_a_api, session_id)

    officer_a_api.patch(_feedback_url(session_id), {"usefulness": "USEFUL"}, format="json")
    officer_a_api.patch(_feedback_url(session_id), {"evidence_sufficiency": "SUFFICIENT"}, format="json")
    officer_a_api.patch(_feedback_url(session_id), {"comment": "Final note."}, format="json")

    assert SimulationFeedback.objects.filter(session_id=session_id).count() == 1
    feedback = SimulationFeedback.objects.get(session_id=session_id)
    assert feedback.usefulness == "USEFUL"
    assert feedback.evidence_sufficiency == "SUFFICIENT"
    assert feedback.comment == "Final note."


# ===========================================================================
# C. Validation
# ===========================================================================
def test_valid_choice_values_accepted(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "FB-VALIDCHOICE", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)
    _open_investigation(officer_a_api, session_id)

    response = officer_a_api.patch(
        _feedback_url(session_id), {"recommendation_helpful": "PARTIALLY"}, format="json"
    )
    assert response.status_code == 200


def test_invalid_choice_rejected(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "FB-INVALIDCHOICE", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)
    _open_investigation(officer_a_api, session_id)

    response = officer_a_api.patch(
        _feedback_url(session_id), {"usefulness": "EXTREMELY_USEFUL"}, format="json"
    )
    assert response.status_code == 400
    assert SimulationFeedback.objects.filter(session_id=session_id).count() == 0


def test_empty_patch_rejected(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "FB-EMPTYPATCH", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)
    _open_investigation(officer_a_api, session_id)

    response = officer_a_api.patch(_feedback_url(session_id), {}, format="json")
    assert response.status_code == 400


# ===========================================================================
# D. Attribution / authorization
# ===========================================================================
def test_officer_attribution_ignores_client_supplied_officer(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "FB-SPOOF", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)
    _open_investigation(officer_a_api, session_id)

    response = officer_a_api.patch(
        _feedback_url(session_id),
        {"usefulness": "USEFUL", "officer": 999, "officer_id": 999},
        format="json",
    )
    assert response.status_code == 200
    feedback = SimulationFeedback.objects.get(session_id=session_id)
    assert feedback.officer.username == "officer.simulation-test"


def test_officer_b_cannot_access_village_a_feedback(officer_a_api, officer_b_api, village):
    scenario = _build_pipeline_scenario(village, "FB-XVILLAGE", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)
    _open_investigation(officer_a_api, session_id)

    get_response = officer_b_api.get(_feedback_url(session_id))
    assert get_response.status_code == 403

    patch_response = officer_b_api.patch(
        _feedback_url(session_id), {"usefulness": "USEFUL"}, format="json"
    )
    assert patch_response.status_code == 403
    assert SimulationFeedback.objects.filter(session_id=session_id).count() == 0


def test_worker_role_rejected(officer_a_api, village, api):
    scenario = _build_pipeline_scenario(village, "FB-WORKER", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)
    _open_investigation(officer_a_api, session_id)

    worker = User.objects.create_user(
        username="worker.feedback-test",
        password="demo1234",
        role=User.Role.CHW_PHC_WORKER,
        village=village,
    )
    api.force_authenticate(user=worker)
    response = api.get(_feedback_url(session_id))
    assert response.status_code == 403


# ===========================================================================
# E. Isolation — feedback never touches safety/evidence/decision
# ===========================================================================
def test_feedback_never_modifies_investigation_decision(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "FB-DECISION-ISOLATION", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)
    _open_investigation(officer_a_api, session_id)
    officer_a_api.post(_decision_url(session_id), {"decision": "CONTINUE_MONITORING"}, format="json")

    officer_a_api.patch(_feedback_url(session_id), {"usefulness": "NOT_USEFUL"}, format="json")

    investigation = SimulationInvestigation.objects.get(session_id=session_id)
    assert investigation.decision == "CONTINUE_MONITORING"


def test_feedback_never_modifies_safety_or_evidence(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "FB-SAFETY-ISOLATION", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)
    _open_investigation(officer_a_api, session_id)

    safety_checks_before = list(
        SimulationSafetyCheck.objects.filter(session_id=session_id).values_list("result", flat=True)
    )
    results_before = list(
        SimulationResult.objects.filter(session_id=session_id).values_list(
            "evidence_strength", "gate_result"
        )
    )
    agent_run_outputs_before = list(
        SimulationAgentRun.objects.filter(session_id=session_id).values_list("output", flat=True)
    )

    officer_a_api.patch(
        _feedback_url(session_id),
        {"usefulness": "NOT_USEFUL", "evidence_sufficiency": "INSUFFICIENT"},
        format="json",
    )

    safety_checks_after = list(
        SimulationSafetyCheck.objects.filter(session_id=session_id).values_list("result", flat=True)
    )
    results_after = list(
        SimulationResult.objects.filter(session_id=session_id).values_list(
            "evidence_strength", "gate_result"
        )
    )
    agent_run_outputs_after = list(
        SimulationAgentRun.objects.filter(session_id=session_id).values_list("output", flat=True)
    )

    assert safety_checks_before == safety_checks_after
    assert results_before == results_after
    assert agent_run_outputs_before == agent_run_outputs_after


def test_feedback_activity_recorded_on_investigation(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "FB-ACTIVITY", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)
    _open_investigation(officer_a_api, session_id)

    officer_a_api.patch(_feedback_url(session_id), {"usefulness": "USEFUL"}, format="json")
    officer_a_api.patch(_feedback_url(session_id), {"usefulness": "NOT_USEFUL"}, format="json")

    activity_types = [
        entry["event_type"]
        for entry in SimulationInvestigation.objects.get(session_id=session_id).activity_history
    ]
    assert "feedback_submitted" in activity_types
    assert "feedback_updated" in activity_types
