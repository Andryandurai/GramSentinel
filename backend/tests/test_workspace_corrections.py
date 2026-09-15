"""Work & Communication — Correction Request System.

Covers the task's Corrections test items (20-30) plus the Security items
that apply to corrections (32-33).
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from assessments.models import PatientAssessment
from core.models import Village
from patients.models import Patient

User = get_user_model()
pytestmark = pytest.mark.django_db

CORRECTIONS = "/api/work/corrections/"
CORRECTABLE_RECORDS = "/api/work/correctable-records/"
OFFICER_CORRECTIONS = "/api/officer/work/corrections/"


def api_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def village_b(db) -> Village:
    return Village.objects.create(code="ARY", name="Manikkampatti", cluster="Village Cluster B", district="Madurai")


@pytest.fixture
def officer_a(db, village):
    return User.objects.create_user(username="cr.officer.a", password="x", role=User.Role.HEALTH_OFFICER, village=village)


@pytest.fixture
def officer_b(db, village_b):
    return User.objects.create_user(username="cr.officer.b", password="x", role=User.Role.HEALTH_OFFICER, village=village_b)


@pytest.fixture
def worker_a(db, village):
    return User.objects.create_user(username="cr.worker.a", password="x", role=User.Role.CHW_PHC_WORKER, village=village)


@pytest.fixture
def worker_other(db, village):
    """A second worker IN THE SAME village — for "cannot correct a
    colleague's record" ownership checks that are not about village scope
    at all."""
    return User.objects.create_user(username="cr.worker.other", password="x", role=User.Role.CHW_PHC_WORKER, village=village)


@pytest.fixture
def patient_a(db, village) -> Patient:
    return Patient.objects.create(patient_code="CR-P-001", display_name="Synthetic Patient", age_years=40, sex="F", village=village)


@pytest.fixture
def assessment_a(db, patient_a, worker_a, village) -> PatientAssessment:
    return PatientAssessment.objects.create(
        patient=patient_a, worker=worker_a, village=village,
        temperature_c=33.6, encounter_date=dt.date(2026, 9, 15),
    )


def submit_correction(worker_api, *, record_type="assessment", record_id):
    return worker_api.post(
        CORRECTIONS,
        {
            "record_type": record_type,
            "record_id": record_id,
            "mistake_description": "Temperature was entered incorrectly.",
            "proposed_correction": "Temperature should be 38.6, not 33.6.",
        },
        format="json",
    )


# 20. Worker can request correction for eligible submitted record.
def test_worker_can_request_correction_for_own_assessment(worker_a, assessment_a):
    response = submit_correction(api_for(worker_a), record_id=assessment_a.id)
    assert response.status_code == 201
    assert response.data["status"] == "SUBMITTED"
    assert response.data["record_label"].startswith("Assessment #")


# 21. Worker cannot directly edit locked submitted record — there is no
#     edit endpoint at all; asserting the assessment itself is untouched
#     by the correction-request submission is the structural proof.
def test_correction_request_never_touches_the_original_record(worker_a, assessment_a):
    submit_correction(api_for(worker_a), record_id=assessment_a.id)
    assessment_a.refresh_from_db()
    assert assessment_a.temperature_c == 33.6


# 22. Correction contains mistake + proposed correction.
def test_correction_captures_mistake_and_proposed_correction(worker_a, assessment_a):
    response = submit_correction(api_for(worker_a), record_id=assessment_a.id)
    assert response.data["mistake_description"] == "Temperature was entered incorrectly."
    assert response.data["proposed_correction"] == "Temperature should be 38.6, not 33.6."
    assert response.data["original_snapshot"]["Temperature (C)"] == "33.6"


# 23. Worker can track status.
def test_worker_can_track_correction_status(worker_a, assessment_a):
    submit_correction(api_for(worker_a), record_id=assessment_a.id)
    corrections = api_for(worker_a).get(CORRECTIONS).data["corrections"]
    assert len(corrections) == 1
    assert corrections[0]["status"] == "SUBMITTED"


# 24. Officer can review.
def test_officer_can_review_a_correction_request(worker_a, officer_a, assessment_a):
    response = submit_correction(api_for(worker_a), record_id=assessment_a.id)
    correction_id = response.data["id"]

    visible = api_for(officer_a).get(OFFICER_CORRECTIONS).data["corrections"]
    assert any(c["id"] == correction_id for c in visible)

    detail = api_for(officer_a).get(f"{CORRECTIONS}{correction_id}/").data
    assert detail["original_snapshot"]["Temperature (C)"] == "33.6"
    assert detail["proposed_correction"] == "Temperature should be 38.6, not 33.6."


# 25. Officer can approve.
# 29. Approved correction preserves history.
def test_officer_can_approve_and_history_is_preserved(worker_a, officer_a, assessment_a):
    correction_id = submit_correction(api_for(worker_a), record_id=assessment_a.id).data["id"]
    officer_api = api_for(officer_a)
    officer_api.post(f"{OFFICER_CORRECTIONS}{correction_id}/transition/", {"status": "UNDER_REVIEW"}, format="json")
    response = officer_api.post(
        f"{OFFICER_CORRECTIONS}{correction_id}/transition/",
        {"status": "APPROVED", "comment": "Verified against the paper record."},
        format="json",
    )
    assert response.data["status"] == "APPROVED"
    assert response.data["applied_at"] is not None
    assert [e["to_status"] for e in response.data["events"]] == ["SUBMITTED", "UNDER_REVIEW", "APPROVED"]
    assert response.data["events"][-1]["comment"] == "Verified against the paper record."


# 26. Officer can return/reject.
def test_officer_can_return_or_reject_a_correction(worker_a, officer_a, assessment_a):
    correction_id = submit_correction(api_for(worker_a), record_id=assessment_a.id).data["id"]
    officer_api = api_for(officer_a)
    officer_api.post(f"{OFFICER_CORRECTIONS}{correction_id}/transition/", {"status": "UNDER_REVIEW"}, format="json")
    response = officer_api.post(
        f"{OFFICER_CORRECTIONS}{correction_id}/transition/", {"status": "REJECTED", "comment": "Not enough evidence."}, format="json"
    )
    assert response.data["status"] == "REJECTED"
    assert response.data["applied_at"] is None


# 27. Worker cannot approve own correction.
def test_worker_cannot_approve_own_correction(worker_a, assessment_a):
    correction_id = submit_correction(api_for(worker_a), record_id=assessment_a.id).data["id"]
    response = api_for(worker_a).post(f"{OFFICER_CORRECTIONS}{correction_id}/transition/", {"status": "APPROVED"}, format="json")
    assert response.status_code == 403


# 28. Original record remains auditable (unchanged even after approval —
#     see model docstring: approval never rewrites clinical history).
def test_original_record_remains_unchanged_even_after_approval(worker_a, officer_a, assessment_a):
    correction_id = submit_correction(api_for(worker_a), record_id=assessment_a.id).data["id"]
    officer_api = api_for(officer_a)
    officer_api.post(f"{OFFICER_CORRECTIONS}{correction_id}/transition/", {"status": "UNDER_REVIEW"}, format="json")
    officer_api.post(f"{OFFICER_CORRECTIONS}{correction_id}/transition/", {"status": "APPROVED"}, format="json")

    assessment_a.refresh_from_db()
    assert assessment_a.temperature_c == 33.6


# 30 / 33. Cross-village access is rejected.
def test_cross_village_correction_access_is_rejected(worker_a, officer_b, assessment_a):
    correction_id = submit_correction(api_for(worker_a), record_id=assessment_a.id).data["id"]

    listing = api_for(officer_b).get(OFFICER_CORRECTIONS).data["corrections"]
    assert listing == []

    response = api_for(officer_b).post(f"{OFFICER_CORRECTIONS}{correction_id}/transition/", {"status": "UNDER_REVIEW"}, format="json")
    assert response.status_code == 404

    detail = api_for(officer_b).get(f"{CORRECTIONS}{correction_id}/")
    assert detail.status_code == 404


# 32. Worker A cannot access Worker B correction requests (same village,
#     different owner — an ownership check, not merely a village check).
def test_worker_cannot_access_a_colleagues_correction_request(worker_a, worker_other, assessment_a):
    correction_id = submit_correction(api_for(worker_a), record_id=assessment_a.id).data["id"]
    response = api_for(worker_other).get(f"{CORRECTIONS}{correction_id}/")
    assert response.status_code == 404


def test_worker_cannot_request_correction_against_a_colleagues_record(worker_other, assessment_a):
    response = submit_correction(api_for(worker_other), record_id=assessment_a.id)
    assert response.status_code == 404


def test_worker_sees_own_assessments_and_reports_as_correctable_records(worker_a, assessment_a):
    records = api_for(worker_a).get(CORRECTABLE_RECORDS).data["records"]
    assert any(r["record_type"] == "assessment" and r["record_id"] == assessment_a.id for r in records)


def test_an_unrecognised_record_type_is_rejected(worker_a):
    response = api_for(worker_a).post(
        CORRECTIONS,
        {"record_type": "alert", "record_id": 1, "mistake_description": "x", "proposed_correction": "y"},
        format="json",
    )
    assert response.status_code == 400
