"""Pregnancy Reporting in Community Report — the Pregnancy option inside
the existing Community Report submission, distinct from the questionnaire-
based Pregnancy Assessment. Fixture shape mirrors `test_pregnancy.py`: two
villages, one worker/officer pair each, so cross-village isolation is
exercised directly.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from community.models import CommunityReport, CommunityReportType
from core.models import Village
from patients.models import Patient
from pregnancy.models import PregnancyCommunityReport, PregnancyProfile, PregnancyStatus
from pregnancy.models import PregnancyProfileEvent, PregnancyVisitAssessment

User = get_user_model()
pytestmark = pytest.mark.django_db

COMMUNITY_REPORT_URL = "/api/pregnancy/community-reports/"
GENERAL_REPORT_URL = "/api/community-reports/"
OFFICER_COMMUNITY_REPORTS_URL = "/api/officer/community-reports/"
PROFILES_URL = "/api/pregnancy/profiles/"


def api_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def village_b(db) -> Village:
    return Village.objects.create(
        code="PCR-B", name="Other Village", cluster="Cluster B", district="Madurai"
    )


@pytest.fixture
def worker_a(db, village):
    return User.objects.create_user(
        username="pcr.worker.a", password="x", role=User.Role.CHW_PHC_WORKER, village=village
    )


@pytest.fixture
def worker_b(db, village_b):
    return User.objects.create_user(
        username="pcr.worker.b", password="x", role=User.Role.CHW_PHC_WORKER, village=village_b
    )


@pytest.fixture
def officer_a(db, village):
    return User.objects.create_user(
        username="pcr.officer.a", password="x", role=User.Role.HEALTH_OFFICER, village=village
    )


@pytest.fixture
def officer_b(db, village_b):
    return User.objects.create_user(
        username="pcr.officer.b", password="x", role=User.Role.HEALTH_OFFICER, village=village_b
    )


@pytest.fixture
def patient_a(db, village, worker_a) -> Patient:
    return Patient.objects.create(
        patient_code="PCR-A-001", display_name="Patient A", age_years=26, sex="F",
        village=village, created_by=worker_a,
    )


@pytest.fixture
def profile_a(db, patient_a, village, worker_a) -> PregnancyProfile:
    return PregnancyProfile.objects.create(
        patient=patient_a, village=village, assigned_health_worker=worker_a,
        next_checkup_date=dt.date.today() - dt.timedelta(days=3),  # overdue
    )


@pytest.fixture
def patient_b(db, village_b, worker_b) -> Patient:
    return Patient.objects.create(
        patient_code="PCR-B-001", display_name="Patient B", age_years=30, sex="F",
        village=village_b, created_by=worker_b,
    )


@pytest.fixture
def profile_b(db, patient_b, village_b, worker_b) -> PregnancyProfile:
    return PregnancyProfile.objects.create(patient=patient_b, village=village_b, assigned_health_worker=worker_b)


# ---------------------------------------------------------------------------
# Submission — server-derived fields, not re-typed by the worker
# ---------------------------------------------------------------------------
def test_worker_can_submit_pregnancy_report_for_own_village_profile(worker_a, profile_a, village):
    response = api_for(worker_a).post(
        COMMUNITY_REPORT_URL,
        {"pregnancy_profile": profile_a.id, "reason": "Missed last two visits", "remarks": "Household unreachable"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["report_type"] == "PREGNANCY"
    assert response.data["village_name"] == village.name
    detail = response.data["pregnancy_detail"]
    assert detail["reason"] == "Missed last two visits"
    assert detail["remarks"] == "Household unreachable"
    # Overdue next_checkup_date fixture -> the deterministic rules layer
    # must be the one flagging follow-up, not the worker's own say-so.
    assert detail["follow_up_required"] is True
    assert detail["next_checkup_date"] == str(profile_a.next_checkup_date)
    assert detail["completed_visit_count"] == 0
    assert detail["last_checkup_date"] is None


def test_completed_visit_count_and_last_checkup_are_server_derived(worker_a, profile_a):
    PregnancyVisitAssessment.objects.create(
        pregnancy_profile=profile_a, visit_number=1, visit_date=dt.date(2026, 1, 10), worker=worker_a,
    )
    PregnancyVisitAssessment.objects.create(
        pregnancy_profile=profile_a, visit_number=2, visit_date=dt.date(2026, 2, 14), worker=worker_a,
    )

    response = api_for(worker_a).post(
        COMMUNITY_REPORT_URL,
        {"pregnancy_profile": profile_a.id, "reason": "Routine flag"},
        format="json",
    )

    assert response.status_code == 201
    detail = response.data["pregnancy_detail"]
    assert detail["completed_visit_count"] == 2
    assert detail["last_checkup_date"] == "2026-02-14"


def test_follow_up_required_false_when_no_overdue_or_urgent_flag(worker_b, profile_b):
    # No next_checkup_date, no warning signs -> ANC target / PICME flags may
    # fire, but neither is FOLLOW_UP_OVERDUE nor URGENT_CLINICAL_REVIEW.
    profile_b.next_checkup_date = dt.date.today() + dt.timedelta(days=10)
    profile_b.save(update_fields=["next_checkup_date"])

    response = api_for(worker_b).post(
        COMMUNITY_REPORT_URL,
        {"pregnancy_profile": profile_b.id, "reason": "Routine check-in"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["pregnancy_detail"]["follow_up_required"] is False


def test_reason_is_required(worker_a, profile_a):
    response = api_for(worker_a).post(
        COMMUNITY_REPORT_URL, {"pregnancy_profile": profile_a.id, "reason": "   "}, format="json"
    )
    assert response.status_code == 400


def test_worker_cannot_submit_for_a_pregnancy_in_another_village(worker_a, profile_b):
    response = api_for(worker_a).post(
        COMMUNITY_REPORT_URL,
        {"pregnancy_profile": profile_b.id, "reason": "Cross-village attempt"},
        format="json",
    )
    assert response.status_code == 404
    assert not PregnancyCommunityReport.objects.exists()


def test_officer_role_rejected(officer_a, profile_a):
    response = api_for(officer_a).post(
        COMMUNITY_REPORT_URL, {"pregnancy_profile": profile_a.id, "reason": "x"}, format="json"
    )
    assert response.status_code == 403


def test_submission_appends_a_pregnancy_profile_event(worker_a, profile_a):
    api_for(worker_a).post(
        COMMUNITY_REPORT_URL, {"pregnancy_profile": profile_a.id, "reason": "Flag it"}, format="json"
    )
    events = list(profile_a.events.all())
    assert any(e.event_type == PregnancyProfileEvent.EventType.COMMUNITY_REPORT_SUBMITTED for e in events)


# ---------------------------------------------------------------------------
# Officer visibility — clearly identified as Pregnancy, never inferred
# ---------------------------------------------------------------------------
def test_officer_sees_report_type_and_pregnancy_detail_never_patient_name(
    worker_a, officer_a, profile_a, patient_a
):
    api_for(worker_a).post(
        COMMUNITY_REPORT_URL,
        {"pregnancy_profile": profile_a.id, "reason": "Overdue check-up", "remarks": "Called twice"},
        format="json",
    )

    payload = api_for(officer_a).get(OFFICER_COMMUNITY_REPORTS_URL).data
    reports = payload["reports"]
    assert len(reports) == 1
    row = reports[0]
    assert row["report_type"] == "PREGNANCY"
    assert row["pregnancy_detail"]["reason"] == "Overdue check-up"
    assert row["pregnancy_detail"]["patient_code"] == patient_a.patient_code
    # No display name, phone, or address anywhere in the payload — privacy
    # rule already established by OfficerPregnancyListItemSerializer.
    assert "patient_name" not in row["pregnancy_detail"]
    assert patient_a.display_name not in str(row)


def test_officer_cannot_see_another_villages_pregnancy_report(worker_a, officer_b, profile_a):
    api_for(worker_a).post(
        COMMUNITY_REPORT_URL, {"pregnancy_profile": profile_a.id, "reason": "x"}, format="json"
    )
    payload = api_for(officer_b).get(OFFICER_COMMUNITY_REPORTS_URL).data
    assert payload["reports"] == []


def test_general_report_has_no_pregnancy_detail(worker_a, officer_a, village):
    api_for(worker_a).post(
        GENERAL_REPORT_URL,
        {
            "village": village.id,
            "week_label": "2026-W40",
            "period_start": "2026-09-28",
            "period_end": "2026-10-04",
            "entries": [{"category": "FEVER", "case_count": 3}],
        },
        format="json",
    )
    payload = api_for(officer_a).get(OFFICER_COMMUNITY_REPORTS_URL).data
    assert payload["reports"][0]["report_type"] == "GENERAL"
    assert payload["reports"][0]["pregnancy_detail"] is None


# ---------------------------------------------------------------------------
# Lifecycle reuse — same acknowledged_at mechanism, no second status system
# ---------------------------------------------------------------------------
def test_pregnancy_report_uses_the_same_acknowledged_lifecycle(worker_a, officer_a, profile_a):
    api_for(worker_a).post(
        COMMUNITY_REPORT_URL, {"pregnancy_profile": profile_a.id, "reason": "x"}, format="json"
    )
    officer_client = api_for(officer_a)
    dashboard_before = officer_client.get("/api/officer/dashboard/").data
    assert dashboard_before["new_reports"] == 1

    officer_client.get(OFFICER_COMMUNITY_REPORTS_URL)

    dashboard_after = officer_client.get("/api/officer/dashboard/").data
    assert dashboard_after["new_reports"] == 0
    report = CommunityReport.objects.get(report_type=CommunityReportType.PREGNANCY)
    assert report.acknowledged_at is not None


# ---------------------------------------------------------------------------
# Does not collide with the General weekly report for the same week
# ---------------------------------------------------------------------------
def test_pregnancy_report_does_not_block_or_get_overwritten_by_general_weekly_report(
    worker_a, profile_a, village
):
    pregnancy_response = api_for(worker_a).post(
        COMMUNITY_REPORT_URL, {"pregnancy_profile": profile_a.id, "reason": "x"}, format="json"
    )
    week_label = pregnancy_response.data["week_label"]

    general_response = api_for(worker_a).post(
        GENERAL_REPORT_URL,
        {
            "village": village.id,
            "week_label": week_label,
            "period_start": "2026-09-28",
            "period_end": "2026-10-04",
            "entries": [{"category": "FEVER", "case_count": 2}],
        },
        format="json",
    )

    assert general_response.status_code == 201
    assert CommunityReport.objects.filter(report_type=CommunityReportType.PREGNANCY).count() == 1
    assert CommunityReport.objects.filter(report_type=CommunityReportType.GENERAL).count() == 1


def test_worker_can_submit_more_than_one_pregnancy_report_in_the_same_week(worker_a, village, patient_a):
    profile_1 = PregnancyProfile.objects.create(patient=patient_a, village=village)
    other_patient = Patient.objects.create(
        patient_code="PCR-A-002", display_name="Patient A2", age_years=22, sex="F", village=village,
    )
    profile_2 = PregnancyProfile.objects.create(patient=other_patient, village=village)

    client = api_for(worker_a)
    first = client.post(COMMUNITY_REPORT_URL, {"pregnancy_profile": profile_1.id, "reason": "x"}, format="json")
    second = client.post(COMMUNITY_REPORT_URL, {"pregnancy_profile": profile_2.id, "reason": "y"}, format="json")

    assert first.status_code == 201
    assert second.status_code == 201
    assert CommunityReport.objects.filter(report_type=CommunityReportType.PREGNANCY).count() == 2
