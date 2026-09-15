"""Work & Communication — Report Approval Tracker.

Covers the task's Report Approval test items (10-19), reusing the real
`community-reports` submission endpoint (never a second submission path)
so `ReportApproval` rows are created exactly the way `workspace.services
.record_report_submission` actually creates them in production.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from core.models import Village

User = get_user_model()
pytestmark = pytest.mark.django_db

COMMUNITY_REPORTS = "/api/community-reports/"
WORKER_APPROVALS = "/api/work/report-approvals/"
OFFICER_APPROVALS = "/api/officer/work/report-approvals/"


def api_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def village_b(db) -> Village:
    return Village.objects.create(code="ARY", name="Manikkampatti", cluster="Village Cluster B", district="Madurai")


@pytest.fixture
def officer_a(db, village):
    return User.objects.create_user(
        username="ra.officer.a", password="x", role=User.Role.HEALTH_OFFICER, village=village
    )


@pytest.fixture
def officer_b(db, village_b):
    return User.objects.create_user(
        username="ra.officer.b", password="x", role=User.Role.HEALTH_OFFICER, village=village_b
    )


@pytest.fixture
def worker_a(db, village):
    return User.objects.create_user(
        username="ra.worker.a", password="x", role=User.Role.CHW_PHC_WORKER, village=village
    )


def submit_report(worker_api, village, week_label="2026-W37", fever=3):
    return worker_api.post(
        COMMUNITY_REPORTS,
        {
            "village": village.id,
            "week_label": week_label,
            "period_start": "2026-09-08",
            "period_end": "2026-09-14",
            "entries": [{"category": "FEVER", "case_count": fever}],
        },
        format="json",
    )


# 10-11. Worker sees own eligible reports, with the correct status.
def test_worker_sees_own_report_with_submitted_status(worker_a, officer_a, village):
    submit_report(api_for(worker_a), village)
    approvals = api_for(worker_a).get(WORKER_APPROVALS).data["approvals"]
    assert len(approvals) == 1
    assert approvals[0]["status"] == "SUBMITTED"
    assert approvals[0]["week_label"] == "2026-W37"


# 12. Officer can move Submitted -> Under Review.
def test_officer_can_move_to_under_review(worker_a, officer_a, village):
    submit_report(api_for(worker_a), village)
    approval_id = api_for(worker_a).get(WORKER_APPROVALS).data["approvals"][0]["id"]

    response = api_for(officer_a).post(f"{OFFICER_APPROVALS}{approval_id}/transition/", {"status": "UNDER_REVIEW"}, format="json")
    assert response.status_code == 200
    assert response.data["status"] == "UNDER_REVIEW"


# 13. Officer can Approve.
def test_officer_can_approve(worker_a, officer_a, village):
    submit_report(api_for(worker_a), village)
    approval_id = api_for(worker_a).get(WORKER_APPROVALS).data["approvals"][0]["id"]
    officer_api = api_for(officer_a)
    officer_api.post(f"{OFFICER_APPROVALS}{approval_id}/transition/", {"status": "UNDER_REVIEW"}, format="json")

    response = officer_api.post(f"{OFFICER_APPROVALS}{approval_id}/transition/", {"status": "APPROVED"}, format="json")
    assert response.status_code == 200
    assert response.data["status"] == "APPROVED"


# 14. Officer can Return for Correction.
# 18. Supervisor comments are visible to the worker.
def test_officer_can_return_for_correction_with_a_comment_visible_to_worker(worker_a, officer_a, village):
    submit_report(api_for(worker_a), village)
    approval_id = api_for(worker_a).get(WORKER_APPROVALS).data["approvals"][0]["id"]
    officer_api = api_for(officer_a)
    officer_api.post(f"{OFFICER_APPROVALS}{approval_id}/transition/", {"status": "UNDER_REVIEW"}, format="json")
    officer_api.post(
        f"{OFFICER_APPROVALS}{approval_id}/transition/",
        {"status": "RETURNED_FOR_CORRECTION", "comment": "Please verify the fever count."},
        format="json",
    )

    worker_view = api_for(worker_a).get(WORKER_APPROVALS).data["approvals"][0]
    assert worker_view["status"] == "RETURNED_FOR_CORRECTION"
    assert worker_view["supervisor_comment"] == "Please verify the fever count."


# 15. Officer can Reject.
def test_officer_can_reject(worker_a, officer_a, village):
    submit_report(api_for(worker_a), village)
    approval_id = api_for(worker_a).get(WORKER_APPROVALS).data["approvals"][0]["id"]
    officer_api = api_for(officer_a)
    officer_api.post(f"{OFFICER_APPROVALS}{approval_id}/transition/", {"status": "UNDER_REVIEW"}, format="json")
    response = officer_api.post(f"{OFFICER_APPROVALS}{approval_id}/transition/", {"status": "REJECTED"}, format="json")
    assert response.data["status"] == "REJECTED"


# 16. Worker can Resubmit a returned report.
def test_worker_can_resubmit_a_returned_report(worker_a, officer_a, village):
    worker_api = api_for(worker_a)
    submit_report(worker_api, village)
    approval_id = worker_api.get(WORKER_APPROVALS).data["approvals"][0]["id"]
    officer_api = api_for(officer_a)
    officer_api.post(f"{OFFICER_APPROVALS}{approval_id}/transition/", {"status": "UNDER_REVIEW"}, format="json")
    officer_api.post(f"{OFFICER_APPROVALS}{approval_id}/transition/", {"status": "RETURNED_FOR_CORRECTION"}, format="json")

    submit_report(worker_api, village, fever=5)  # same village+week -> resubmission
    approval = worker_api.get(WORKER_APPROVALS).data["approvals"][0]
    assert approval["status"] == "RESUBMITTED"
    assert [e["to_status"] for e in approval["events"]] == [
        "SUBMITTED", "UNDER_REVIEW", "RETURNED_FOR_CORRECTION", "RESUBMITTED",
    ]


# 17. Worker cannot approve/reject own report.
def test_worker_cannot_transition_own_report(worker_a, officer_a, village):
    submit_report(api_for(worker_a), village)
    approval_id = api_for(worker_a).get(WORKER_APPROVALS).data["approvals"][0]["id"]

    response = api_for(worker_a).post(f"{OFFICER_APPROVALS}{approval_id}/transition/", {"status": "APPROVED"}, format="json")
    assert response.status_code == 403


def test_officer_cannot_skip_straight_from_submitted_to_approved(worker_a, officer_a, village):
    submit_report(api_for(worker_a), village)
    approval_id = api_for(worker_a).get(WORKER_APPROVALS).data["approvals"][0]["id"]

    response = api_for(officer_a).post(f"{OFFICER_APPROVALS}{approval_id}/transition/", {"status": "APPROVED"}, format="json")
    assert response.status_code == 400


# 19. Cross-village access is rejected.
def test_cross_village_report_approval_access_is_rejected(worker_a, officer_a, officer_b, village):
    submit_report(api_for(worker_a), village)
    approval_id = api_for(worker_a).get(WORKER_APPROVALS).data["approvals"][0]["id"]

    listing = api_for(officer_b).get(OFFICER_APPROVALS).data["approvals"]
    assert listing == []

    response = api_for(officer_b).post(f"{OFFICER_APPROVALS}{approval_id}/transition/", {"status": "UNDER_REVIEW"}, format="json")
    assert response.status_code == 404


def test_original_community_report_is_not_created_twice_by_the_hook(worker_a, village):
    from community.models import CommunityReport
    from workspace.models import ReportApproval

    submit_report(api_for(worker_a), village)
    assert CommunityReport.objects.count() == 1
    assert ReportApproval.objects.count() == 1
