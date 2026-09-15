"""Field Operations — Action Plan Management, cross-feature integration,
and regression (existing GramSentinel/RuralCare/Worker Portal features
remain unaffected).
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from core.models import Village
from fieldops.models import ActionPlan, Department

User = get_user_model()
pytestmark = pytest.mark.django_db

VISITS = "/api/officer/field-visits/"
INSPECTIONS = "/api/officer/inspections/"
ACTION_PLANS = "/api/officer/action-plans/"


def api_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def village_b(db) -> Village:
    return Village.objects.create(code="ARY", name="Manikkampatti", cluster="Village Cluster B", district="Madurai")


@pytest.fixture
def officer_a(db, village):
    return User.objects.create_user(username="ap.officer.a", password="x", role=User.Role.HEALTH_OFFICER, village=village)


@pytest.fixture
def officer_b(db, village_b):
    return User.objects.create_user(username="ap.officer.b", password="x", role=User.Role.HEALTH_OFFICER, village=village_b)


@pytest.fixture
def department(db) -> Department:
    return Department.objects.create(name="Water & Sanitation (test)")


def create_plan(officer_api, village_id, department_id, **overrides):
    payload = {
        "title": "Fix drainage", "problem_finding": "Blocked drainage near water point",
        "village": village_id, "source_type": "OTHER", "department": department_id,
        "deadline": "2026-10-15", "priority": "NORMAL", "progress_percentage": 0,
    }
    payload.update(overrides)
    return officer_api.post(ACTION_PLANS, payload, format="json")


# 17. Health Officer can create action plan.
def test_officer_can_create_action_plan(officer_a, village, department):
    response = create_plan(api_for(officer_a), village.id, department.id)
    assert response.status_code == 201
    assert response.data["status"] == "PENDING"


# 18. Department assignment works.
def test_department_assignment_works(officer_a, village, department):
    response = create_plan(api_for(officer_a), village.id, department.id)
    assert response.data["department_name"] == department.name


# 19. Deadline stored correctly.
def test_deadline_stored_correctly(officer_a, village, department):
    response = create_plan(api_for(officer_a), village.id, department.id, deadline="2026-12-25")
    assert response.data["deadline"] == "2026-12-25"


# 20. Progress accepts 0-100.
@pytest.mark.parametrize("value", [0, 1, 50, 99, 100])
def test_progress_accepts_valid_range(officer_a, village, department, value):
    plan_id = create_plan(api_for(officer_a), village.id, department.id).data["id"]
    response = api_for(officer_a).post(f"{ACTION_PLANS}{plan_id}/progress/", {"new_percentage": value}, format="json")
    assert response.status_code == 200
    assert response.data["progress_percentage"] == value


# 21. Progress below 0 rejected.
def test_progress_below_zero_rejected(officer_a, village, department):
    plan_id = create_plan(api_for(officer_a), village.id, department.id).data["id"]
    response = api_for(officer_a).post(f"{ACTION_PLANS}{plan_id}/progress/", {"new_percentage": -1}, format="json")
    assert response.status_code == 400


# 22. Progress above 100 rejected.
def test_progress_above_100_rejected(officer_a, village, department):
    plan_id = create_plan(api_for(officer_a), village.id, department.id).data["id"]
    response = api_for(officer_a).post(f"{ACTION_PLANS}{plan_id}/progress/", {"new_percentage": 101}, format="json")
    assert response.status_code == 400


# 23. Progress updates preserve history.
def test_progress_updates_preserve_history(officer_a, village, department):
    officer_api = api_for(officer_a)
    plan_id = create_plan(officer_api, village.id, department.id).data["id"]
    officer_api.post(f"{ACTION_PLANS}{plan_id}/progress/", {"new_percentage": 20}, format="json")
    officer_api.post(f"{ACTION_PLANS}{plan_id}/progress/", {"new_percentage": 40}, format="json")
    response = officer_api.post(f"{ACTION_PLANS}{plan_id}/progress/", {"new_percentage": 70}, format="json")

    history = [(u["previous_percentage"], u["new_percentage"]) for u in response.data["progress_updates"]]
    assert history == [(0, 20), (20, 40), (40, 70)]


# 24. Completion works.
def test_completion_via_progress_100(officer_a, village, department):
    officer_api = api_for(officer_a)
    plan_id = create_plan(officer_api, village.id, department.id).data["id"]
    response = officer_api.post(f"{ACTION_PLANS}{plan_id}/progress/", {"new_percentage": 100}, format="json")
    assert response.data["status"] == "COMPLETED"
    assert response.data["completed_at"] is not None


# 25. Overdue is correctly derived.
def test_overdue_is_derived(officer_a, village, department):
    plan = ActionPlan.objects.create(
        village=village, title="test", problem_finding="test", department=department,
        deadline=dt.date(2020, 1, 1), created_by=officer_a,
    )
    assert plan.is_overdue is True
    plan.status = "COMPLETED"
    plan.save()
    assert plan.is_overdue is False


# 26. Unauthorized village access rejected.
def test_unauthorized_village_access_rejected(officer_a, officer_b, village, department):
    plan_id = create_plan(api_for(officer_a), village.id, department.id).data["id"]
    assert api_for(officer_b).get(f"{ACTION_PLANS}{plan_id}/").status_code == 404
    assert api_for(officer_b).get(ACTION_PLANS).data == []


# 27. Inspection finding can create linked action plan.
def test_inspection_finding_creates_linked_action_plan(officer_a, village, department):
    officer_api = api_for(officer_a)
    inspection = officer_api.post(INSPECTIONS, {"village": village.id, "inspection_type": "WASTE_MANAGEMENT"}, format="json").data
    officer_api.post(f"{INSPECTIONS}{inspection['id']}/start/")
    item_id = inspection["responses"][0]["id"]
    officer_api.post(
        f"{INSPECTIONS}{inspection['id']}/responses/{item_id}/",
        {"status": "FAILED", "remarks": "Waste not segregated"}, format="json",
    )

    response = create_plan(
        officer_api, village.id, department.id,
        source_type="INSPECTION", source_inspection=inspection["id"], source_checklist_item=item_id,
        problem_finding="Waste not segregated",
    )
    assert response.status_code == 201
    assert response.data["source_inspection"] == inspection["id"]
    assert response.data["source_checklist_item"] == item_id


# 28. Field visit issue can create linked action plan.
def test_field_visit_issue_creates_linked_action_plan(officer_a, village, department):
    officer_api = api_for(officer_a)
    visit = officer_api.post(
        VISITS, {"village": village.id, "assigned_officer": officer_a.id, "visit_date": "2026-09-20", "objective": "test", "priority": "NORMAL"},
        format="json",
    ).data
    officer_api.post(f"{VISITS}{visit['id']}/start/")
    officer_api.post(f"{VISITS}{visit['id']}/complete/", {"issues_identified": "Uncovered water storage"}, format="json")

    response = create_plan(
        officer_api, village.id, department.id,
        source_type="FIELD_VISIT", source_field_visit=visit["id"], problem_finding="Uncovered water storage",
    )
    assert response.status_code == 201
    assert response.data["source_field_visit"] == visit["id"]


# 29. Cross-village source linking rejected.
def test_cross_village_source_linking_rejected(officer_a, officer_b, village, village_b, department):
    inspection_id = api_for(officer_a).post(
        INSPECTIONS, {"village": village.id, "inspection_type": "WASTE_MANAGEMENT"}, format="json"
    ).data["id"]

    response = create_plan(
        api_for(officer_a), village_b.id, department.id,
        source_type="INSPECTION", source_inspection=inspection_id,
    )
    assert response.status_code == 400
    assert "source_inspection" in response.data["detail"]


def test_worker_cannot_approve_progress_or_create_plans(village, department, officer_a):
    worker = User.objects.create_user(username="ap.worker.a", password="x", role=User.Role.CHW_PHC_WORKER, village=village)
    response = create_plan(api_for(worker), village.id, department.id)
    assert response.status_code == 403


# --- Regression: existing features unaffected --------------------------
# 30. Existing Community Intelligence remains unaffected.
def test_existing_community_reports_endpoint_unaffected(officer_a, village):
    worker = User.objects.create_user(username="ap.worker.ci", password="x", role=User.Role.CHW_PHC_WORKER, village=village)
    response = api_for(worker).post(
        "/api/community-reports/",
        {
            "village": village.id, "week_label": "2026-W38", "period_start": "2026-09-15", "period_end": "2026-09-21",
            "entries": [{"category": "FEVER", "case_count": 2}],
        },
        format="json",
    )
    assert response.status_code == 201


# 31. Existing Active Alerts / Alert history remain unaffected.
def test_existing_alert_list_endpoint_unaffected(officer_a):
    response = api_for(officer_a).get("/api/alerts/")
    assert response.status_code == 200


# 32. Existing Simulation Lab remains unaffected.
def test_existing_simulation_scenarios_endpoint_unaffected(officer_a):
    response = api_for(officer_a).get("/api/simulation/scenarios/")
    assert response.status_code == 200


# 33. Existing Worker Portal (Work & Communication) remains unaffected.
def test_existing_work_communication_endpoint_unaffected(officer_a):
    response = api_for(officer_a).get("/api/officer/work/threads/")
    assert response.status_code == 200
