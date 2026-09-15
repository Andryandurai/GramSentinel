"""Field Operations — Field Visit Planner."""

from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from core.models import Village
from fieldops.models import FieldVisit

User = get_user_model()
pytestmark = pytest.mark.django_db

VISITS = "/api/officer/field-visits/"


def api_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def village_b(db) -> Village:
    return Village.objects.create(code="ARY", name="Manikkampatti", cluster="Village Cluster B", district="Madurai")


@pytest.fixture
def officer_a(db, village):
    return User.objects.create_user(username="fv.officer.a", password="x", role=User.Role.HEALTH_OFFICER, village=village)


@pytest.fixture
def officer_b(db, village_b):
    return User.objects.create_user(username="fv.officer.b", password="x", role=User.Role.HEALTH_OFFICER, village=village_b)


@pytest.fixture
def worker_a(db, village):
    return User.objects.create_user(username="fv.worker.a", password="x", role=User.Role.CHW_PHC_WORKER, village=village)


def create_visit(officer_api, village_id, officer_id, **overrides):
    payload = {
        "village": village_id, "assigned_officer": officer_id, "visit_date": "2026-09-20",
        "objective": "Routine village health inspection", "priority": "NORMAL",
    }
    payload.update(overrides)
    return officer_api.post(VISITS, payload, format="json")


# 1. Health Officer can create a field visit.
def test_officer_can_create_field_visit(officer_a, village):
    response = create_visit(api_for(officer_a), village.id, officer_a.id)
    assert response.status_code == 201
    assert response.data["status"] == "SCHEDULED"


# 2. Unauthorized role cannot create one.
def test_worker_cannot_create_field_visit(worker_a, village, officer_a):
    response = create_visit(api_for(worker_a), village.id, officer_a.id)
    assert response.status_code == 403


# 3. Officer cannot access another village's visit.
def test_officer_cannot_access_another_villages_visit(officer_a, officer_b, village):
    visit_id = create_visit(api_for(officer_a), village.id, officer_a.id).data["id"]
    response = api_for(officer_b).get(f"{VISITS}{visit_id}/")
    assert response.status_code == 404
    assert api_for(officer_b).get(VISITS).data == []


# 4. Officer can view own authorized village visits.
def test_officer_sees_own_village_visits(officer_a, village):
    create_visit(api_for(officer_a), village.id, officer_a.id)
    response = api_for(officer_a).get(VISITS)
    assert len(response.data) == 1


# 5. Visit status transitions work.
def test_visit_status_transitions(officer_a, village):
    officer_api = api_for(officer_a)
    visit_id = create_visit(officer_api, village.id, officer_a.id).data["id"]
    started = officer_api.post(f"{VISITS}{visit_id}/start/")
    assert started.data["status"] == "IN_PROGRESS"
    completed = officer_api.post(f"{VISITS}{visit_id}/complete/", {"outcome_summary": "Done"}, format="json")
    assert completed.data["status"] == "COMPLETED"


# 6. Completion records outcome.
def test_completion_records_outcome(officer_a, village):
    officer_api = api_for(officer_a)
    visit_id = create_visit(officer_api, village.id, officer_a.id).data["id"]
    officer_api.post(f"{VISITS}{visit_id}/start/")
    response = officer_api.post(
        f"{VISITS}{visit_id}/complete/",
        {
            "outcome_summary": "Visit completed successfully",
            "observations": "Water storage tank was uncovered",
            "issues_identified": "Uncovered water storage",
            "follow_up_required": True,
        },
        format="json",
    )
    assert response.data["outcome_summary"] == "Visit completed successfully"
    assert response.data["follow_up_required"] is True
    assert response.data["completed_at"] is not None


# 7. Invalid status transition rejected.
def test_invalid_status_transition_rejected(officer_a, village):
    officer_api = api_for(officer_a)
    visit_id = create_visit(officer_api, village.id, officer_a.id).data["id"]
    # Cannot complete a visit that hasn't started.
    response = officer_api.post(f"{VISITS}{visit_id}/complete/", {}, format="json")
    assert response.status_code == 400

    officer_api.post(f"{VISITS}{visit_id}/start/")
    officer_api.post(f"{VISITS}{visit_id}/complete/", {}, format="json")
    # Cannot start an already-completed visit.
    response = officer_api.post(f"{VISITS}{visit_id}/start/")
    assert response.status_code == 400


def test_assigned_officer_must_belong_to_the_visits_village(officer_a, officer_b, village):
    response = create_visit(api_for(officer_a), village.id, officer_b.id)
    assert response.status_code == 400
    assert "assigned_officer" in response.data["detail"]


def test_client_cannot_spoof_village_id(officer_a, officer_b, village, village_b):
    response = api_for(officer_a).post(
        VISITS,
        {"village": village_b.id, "assigned_officer": officer_a.id, "visit_date": "2026-09-20", "objective": "test", "priority": "NORMAL"},
        format="json",
    )
    # assigned_officer (village A) mismatched against village B is refused
    # by the serializer's own consistency check first.
    assert response.status_code == 400


def test_overdue_is_derived_not_stored(officer_a, village):
    visit = FieldVisit.objects.create(
        village=village, assigned_officer=officer_a, visit_date=dt.date(2020, 1, 1),
        objective="test", created_by=officer_a,
    )
    assert visit.is_overdue is True
    response = api_for(officer_a).get(f"{VISITS}{visit.id}/")
    assert response.data["is_overdue"] is True

    visit.status = "CANCELLED"
    visit.save()
    assert visit.is_overdue is False


def test_search_and_filters(officer_a, village):
    officer_api = api_for(officer_a)
    create_visit(officer_api, village.id, officer_a.id, objective="Drinking water assessment", priority="URGENT")
    create_visit(officer_api, village.id, officer_a.id, objective="School health inspection", priority="NORMAL")

    by_search = officer_api.get(f"{VISITS}?q=water").data
    assert len(by_search) == 1
    by_priority = officer_api.get(f"{VISITS}?priority=URGENT").data
    assert len(by_priority) == 1
