"""Phase 9 — Investigation Notebook backend tests.

Reuses the Phase 4 scenario-building helpers and village/officer fixtures
from `test_simulation.py` (see that file's own docstrings) rather than
redefining them.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from agents.llm import LLMUnavailable
from simulation.models import (
    InvestigationStatus,
    SafetyGateResult,
    SimulationAgentRun,
    SimulationInvestigation,
    SimulationResult,
    SimulationSafetyCheck,
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


def _observations_url(session_id: int) -> str:
    return f"{SESSIONS_URL}{session_id}/investigation/observations/"


def _report_url(session_id: int) -> str:
    return f"{SESSIONS_URL}{session_id}/investigation/report/"


def _start_and_advance(api_client, scenario, times: int) -> int:
    response = api_client.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    session_id = response.data["session_id"]
    for _ in range(times):
        _advance(api_client, session_id)
    return session_id


# ===========================================================================
# A. Access / authorization
# ===========================================================================
def test_get_investigation_creates_it_and_is_idempotent(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "INV-CREATE", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 2)

    first = officer_a_api.get(_investigation_url(session_id))
    assert first.status_code == 200
    assert first.data["status"] == InvestigationStatus.IN_PROGRESS
    assert first.data["overview"]["investigation_id"] is not None

    second = officer_a_api.get(_investigation_url(session_id))
    assert second.status_code == 200
    assert second.data["overview"]["investigation_id"] == first.data["overview"]["investigation_id"]

    assert SimulationInvestigation.objects.filter(session_id=session_id).count() == 1


def test_officer_b_cannot_access_village_a_investigation(officer_a_api, officer_b_api, village):
    scenario = _build_pipeline_scenario(village, "INV-XVILLAGE", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)

    response = officer_b_api.get(_investigation_url(session_id))
    assert response.status_code == 403


def test_worker_role_rejected(officer_a_api, village, api):
    scenario = _build_pipeline_scenario(village, "INV-ROLE", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)

    worker = User.objects.create_user(
        username="worker.investigation-test",
        password="demo1234",
        role=User.Role.CHW_PHC_WORKER,
        village=village,
    )
    api.force_authenticate(user=worker)
    response = api.get(_investigation_url(session_id))
    assert response.status_code == 403


def test_unauthenticated_rejected(village, officer_a_api):
    from rest_framework.test import APIClient

    scenario = _build_pipeline_scenario(village, "INV-UNAUTH", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)

    anonymous = APIClient()
    response = anonymous.get(_investigation_url(session_id))
    assert response.status_code == 401


# ===========================================================================
# B. Notes / checklist
# ===========================================================================
def test_notes_save_and_update(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "INV-NOTES", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)
    officer_a_api.get(_investigation_url(session_id))

    first = officer_a_api.patch(_investigation_url(session_id), {"notes": "Initial note."}, format="json")
    assert first.status_code == 200
    assert first.data["notes"] == "Initial note."

    second = officer_a_api.patch(_investigation_url(session_id), {"notes": "Updated note."}, format="json")
    assert second.status_code == 200
    assert second.data["notes"] == "Updated note."
    assert SimulationInvestigation.objects.get(session_id=session_id).officer_notes == "Updated note."


def test_checklist_only_lists_sources_the_session_actually_has(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "INV-CHECKLIST-SOURCES", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)

    response = officer_a_api.get(_investigation_url(session_id))
    item_keys = {item["key"] for item in response.data["checklist"]["items"]}

    assert "source_CHW" in item_keys
    assert "source_PHC" in item_keys
    # This scenario never has a pharmacy/lab source — never claim one was
    # reviewed (task §18).
    assert "source_PHARMACY" not in item_keys
    assert "source_LAB" not in item_keys
    assert "timeline_reviewed" in item_keys
    assert "human_verification_completed" in item_keys


def test_checklist_ignores_unknown_keys(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "INV-CHECKLIST-UNKNOWN", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)
    officer_a_api.get(_investigation_url(session_id))

    response = officer_a_api.patch(
        _investigation_url(session_id),
        {"checklist": {"timeline_reviewed": True, "not_a_real_item": True}},
        format="json",
    )
    assert response.status_code == 200
    assert "not_a_real_item" not in response.data["checklist"]["values"]
    assert response.data["checklist"]["values"]["timeline_reviewed"] is True


def test_full_checklist_transitions_status_to_ready_for_decision(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "INV-CHECKLIST-COMPLETE", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)

    initial = officer_a_api.get(_investigation_url(session_id))
    all_keys = [item["key"] for item in initial.data["checklist"]["items"]]

    response = officer_a_api.patch(
        _investigation_url(session_id),
        {"checklist": {key: True for key in all_keys}},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["checklist"]["progress"] == {
        "checked": len(all_keys),
        "total": len(all_keys),
        "percent": 100,
    }
    assert response.data["status"] == InvestigationStatus.READY_FOR_DECISION


# ===========================================================================
# C. Decision
# ===========================================================================
def test_decision_recorded_and_attributed_to_authenticated_officer(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "INV-DECISION", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)
    officer_a_api.get(_investigation_url(session_id))

    response = officer_a_api.post(
        _decision_url(session_id),
        {"decision": "CONTINUE_MONITORING", "reason": "Evidence not yet strong enough."},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["decision"]["value"] == "CONTINUE_MONITORING"
    assert response.data["decision"]["decided_by"] == "officer.simulation-test"
    assert response.data["status"] == InvestigationStatus.DECISION_RECORDED

    investigation = SimulationInvestigation.objects.get(session_id=session_id)
    assert investigation.decided_by.username == "officer.simulation-test"
    assert investigation.decided_at is not None


def test_decision_rejects_unknown_value(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "INV-DECISION-INVALID", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)
    officer_a_api.get(_investigation_url(session_id))

    response = officer_a_api.post(
        _decision_url(session_id), {"decision": "DECLARE_OUTBREAK"}, format="json"
    )
    assert response.status_code == 400


def test_decision_ignores_client_supplied_officer_id(officer_a_api, village):
    """The input serializer has no id field to accept in the first place —
    this proves a client attempt to smuggle one through has no effect
    (task §39/§41: never trust an id from the frontend)."""

    scenario = _build_pipeline_scenario(village, "INV-DECISION-SPOOF", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)
    officer_a_api.get(_investigation_url(session_id))

    response = officer_a_api.post(
        _decision_url(session_id),
        {"decision": "CONTINUE_MONITORING", "decided_by": 999, "officer_id": 999},
        format="json",
    )
    assert response.status_code == 200
    investigation = SimulationInvestigation.objects.get(session_id=session_id)
    assert investigation.decided_by.username == "officer.simulation-test"


def test_safety_block_prevents_decision_recording(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "INV-BLOCK", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)
    officer_a_api.get(_investigation_url(session_id))

    with patch(
        "simulation.safety.engine.SafetyEngine.evaluate_latest",
        return_value={
            "checks": [],
            "gate_result": SafetyGateResult.BLOCK,
            "human_review_required": True,
            "evidence_strength": "WEAK",
        },
    ):
        response = officer_a_api.post(
            _decision_url(session_id), {"decision": "CONTINUE_MONITORING"}, format="json"
        )
    assert response.status_code == 403
    investigation = SimulationInvestigation.objects.get(session_id=session_id)
    assert investigation.decision == ""
    assert investigation.status == InvestigationStatus.IN_PROGRESS


def test_insufficient_safety_allows_decision(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "INV-INSUFFICIENT",
        [_week(1, {"FEVER": 5}, {"CHW": (5, True), "PHC": (9, True)})],
    )
    session_id = _start_and_advance(officer_a_api, scenario, 0)
    officer_a_api.get(_investigation_url(session_id))

    with patch(
        "simulation.safety.engine.SafetyEngine.evaluate_latest",
        return_value={
            "checks": [],
            "gate_result": SafetyGateResult.INSUFFICIENT,
            "human_review_required": True,
            "evidence_strength": "WEAK",
        },
    ):
        response = officer_a_api.post(
            _decision_url(session_id), {"decision": "REQUEST_MORE_DATA"}, format="json"
        )
    assert response.status_code == 200
    assert response.data["decision"]["value"] == "REQUEST_MORE_DATA"


def test_pass_safety_allows_decision(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "INV-PASS", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)
    officer_a_api.get(_investigation_url(session_id))

    response = officer_a_api.post(
        _decision_url(session_id), {"decision": "CONDUCT_FIELD_VERIFICATION"}, format="json"
    )
    assert response.status_code == 200


# ===========================================================================
# D. Observations
# ===========================================================================
def test_observation_persistence_and_incrementing_ids(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "INV-OBSERVATIONS", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)
    officer_a_api.get(_investigation_url(session_id))

    first = officer_a_api.post(
        _observations_url(session_id),
        {"week": 1, "source": "CHW", "notes": "Stagnant water observed near community tank."},
        format="json",
    )
    assert first.status_code == 201
    assert len(first.data["observations"]) == 1
    assert first.data["observations"][0]["id"] == 1

    second = officer_a_api.post(
        _observations_url(session_id),
        {"week": 1, "source": "PHC", "notes": "Second observation."},
        format="json",
    )
    assert second.status_code == 201
    assert len(second.data["observations"]) == 2
    assert second.data["observations"][1]["id"] == 2


# ===========================================================================
# E. Replay / What-If remain unaffected
# ===========================================================================
def test_replay_read_only_after_investigation_activity(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "INV-REPLAY-COMPAT", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)
    officer_a_api.get(_investigation_url(session_id))
    officer_a_api.patch(_investigation_url(session_id), {"notes": "Some notes."}, format="json")

    run_count_before = SimulationAgentRun.objects.filter(session_id=session_id).count()
    safety_count_before = SimulationSafetyCheck.objects.filter(session_id=session_id).count()

    response = officer_a_api.get(f"{SESSIONS_URL}{session_id}/replay/?week=2")
    assert response.status_code == 200

    assert SimulationAgentRun.objects.filter(session_id=session_id).count() == run_count_before
    assert SimulationSafetyCheck.objects.filter(session_id=session_id).count() == safety_count_before


def test_what_if_does_not_overwrite_investigation(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "INV-WHATIF-COMPAT", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)
    officer_a_api.get(_investigation_url(session_id))
    officer_a_api.patch(_investigation_url(session_id), {"notes": "Original notes."}, format="json")

    response = officer_a_api.post(
        f"{SESSIONS_URL}{session_id}/what-if/", {"overrides": {"PHC": None}}, format="json"
    )
    assert response.status_code == 200

    investigation = SimulationInvestigation.objects.get(session_id=session_id)
    assert investigation.officer_notes == "Original notes."
    assert SimulationInvestigation.objects.filter(session_id=session_id).count() == 1


# ===========================================================================
# F. Operational isolation
# ===========================================================================
def test_investigation_workflow_never_touches_operational_tables(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "INV-OPS-ISOLATION", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)

    before = _operational_counts()

    officer_a_api.get(_investigation_url(session_id))
    officer_a_api.patch(_investigation_url(session_id), {"notes": "Notes."}, format="json")
    officer_a_api.post(
        _observations_url(session_id),
        {"week": 1, "source": "CHW", "notes": "Observation."},
        format="json",
    )
    officer_a_api.post(_decision_url(session_id), {"decision": "CONTINUE_MONITORING"}, format="json")
    officer_a_api.get(_report_url(session_id))

    after = _operational_counts()
    assert before == after


# ===========================================================================
# G. PDF export
# ===========================================================================
def test_report_export_returns_a_pdf(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "INV-REPORT", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)
    officer_a_api.get(_investigation_url(session_id))
    officer_a_api.patch(_investigation_url(session_id), {"notes": "Investigation notes here."}, format="json")
    officer_a_api.post(_decision_url(session_id), {"decision": "CONTINUE_MONITORING"}, format="json")

    response = officer_a_api.get(_report_url(session_id))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    content = b"".join(response.streaming_content) if response.streaming else response.content
    assert content.startswith(b"%PDF")


def test_report_export_leaves_exactly_one_investigation_row(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "INV-REPORT-NODUP", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 1)
    officer_a_api.get(_investigation_url(session_id))
    officer_a_api.get(_report_url(session_id))
    officer_a_api.get(_report_url(session_id))

    assert SimulationInvestigation.objects.filter(session_id=session_id).count() == 1
    activity_types = [
        entry["event_type"]
        for entry in SimulationInvestigation.objects.get(session_id=session_id).activity_history
    ]
    assert activity_types.count("report_exported") == 2


# ===========================================================================
# H. Investigation priority (SimulationResult) and safety-vocabulary checks
# ===========================================================================
def test_investigation_priority_populated_after_advance(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "INV-PRIORITY", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)

    latest_result = SimulationResult.objects.filter(session_id=session_id).order_by("-created_at").first()
    assert latest_result is not None
    assert latest_result.investigation_priority in {"LOW", "MODERATE", "HIGH"}


def test_no_ai_confidence_or_outbreak_wording_in_investigation_payload(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "INV-WORDING", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)
    officer_a_api.get(_investigation_url(session_id))
    officer_a_api.patch(_investigation_url(session_id), {"notes": "Routine notes."}, format="json")
    response = officer_a_api.post(_decision_url(session_id), {"decision": "CONTINUE_MONITORING"}, format="json")

    payload_text = str(response.data).lower()
    for banned in ("ai confidence", "model confidence", "outbreak detected", "outbreak confirmed"):
        assert banned not in payload_text
