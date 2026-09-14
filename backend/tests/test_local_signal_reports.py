"""'Report to Health Officer' — a worker's flag on one above-baseline local
signal (`community.models.LocalSignalReport`), and its officer-facing
surfaces (dashboard unread count/popup data, and the Community reports
page's own persistent list).

Fixture shape mirrors `test_community_data.py`: two villages, one
village-scoped officer and one village-scoped worker per village, so
cross-village isolation is exercised directly rather than assumed.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from community.models import CommunitySignal, DataSource, LocalSignalReport
from core.constants import SignalCategory
from core.models import Village

User = get_user_model()
pytestmark = pytest.mark.django_db

REPORT_URL = "/api/local-signal-reports/"
DASHBOARD_URL = "/api/officer/dashboard/"
COMMUNITY_REPORTS_URL = "/api/officer/community-reports/"


@pytest.fixture
def villages(db):
    return {
        code: Village.objects.create(code=code, name=name, cluster="Village Cluster A")
        for code, name in (("KVL", "Kovilur"), ("ARY", "Manikkampatti"))
    }


@pytest.fixture
def officers(villages):
    return {
        code: User.objects.create_user(
            username=f"officer.{code.lower()}",
            password="demo1234",
            role=User.Role.HEALTH_OFFICER,
            village=village,
        )
        for code, village in villages.items()
    }


@pytest.fixture
def workers(villages):
    return {
        code: User.objects.create_user(
            username=f"worker.{code.lower()}",
            password="demo1234",
            role=User.Role.CHW_PHC_WORKER,
            village=village,
        )
        for code, village in villages.items()
    }


def api_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def add_signal(
    village: Village,
    category: str = SignalCategory.FEVER,
    week_label: str = "2026-W35",
    value: float = 18.0,
    baseline: float = 10.0,
    is_reported: bool = True,
    source_kind: str = "CHW",
) -> CommunitySignal:
    source, _ = DataSource.objects.get_or_create(
        code=f"CHW-{village.code}",
        defaults={
            "name": f"CHW reports — {village.name}",
            "kind": source_kind,
            "village": village,
        },
    )
    return CommunitySignal.objects.create(
        source=source,
        village=village,
        category=category,
        week_label=week_label,
        period_start="2026-08-24",
        period_end="2026-08-30",
        value=value,
        baseline=baseline,
        unit="reports",
        is_reported=is_reported,
    )


# ---------------------------------------------------------------------------
# 1 & 5 — worker can report their own village's signal, with correct values
# ---------------------------------------------------------------------------
def test_worker_can_report_own_village_signal_with_correct_values(villages, workers):
    village = villages["ARY"]
    signal = add_signal(village, value=18.0, baseline=10.0)

    response = api_for(workers["ARY"]).post(
        REPORT_URL, {"signal": signal.id, "note": "Households near the well."}
    )

    assert response.status_code == 201
    report = response.data["report"]
    assert response.data["created"] is True
    assert response.data["message"] == "Report sent to the Health Officer."
    assert report["village_name"] == "Manikkampatti"
    assert report["category"] == SignalCategory.FEVER
    assert report["source_kind"] == "CHW"
    assert report["week_label"] == "2026-W35"
    assert report["baseline"] == 10.0
    assert report["value"] == 18.0
    assert report["change_pct"] == pytest.approx(80.0)
    assert report["note"] == "Households near the well."
    assert report["acknowledged"] is False


def test_worker_cannot_report_a_signal_that_is_not_above_baseline(villages, workers):
    village = villages["ARY"]
    signal = add_signal(village, value=10.5, baseline=10.0)  # +5%, below the 30% bar

    response = api_for(workers["ARY"]).post(REPORT_URL, {"signal": signal.id})

    assert response.status_code == 400
    assert LocalSignalReport.objects.count() == 0


def test_worker_cannot_report_a_not_submitted_signal(villages, workers):
    village = villages["ARY"]
    signal = add_signal(village, value=None, baseline=10.0, is_reported=False)

    response = api_for(workers["ARY"]).post(REPORT_URL, {"signal": signal.id})

    assert response.status_code == 400
    assert LocalSignalReport.objects.count() == 0


# ---------------------------------------------------------------------------
# 2 — worker cannot report to (i.e. about) another village's signal
# ---------------------------------------------------------------------------
def test_worker_cannot_report_another_villages_signal(villages, workers):
    other_signal = add_signal(villages["KVL"], value=18.0, baseline=10.0)

    response = api_for(workers["ARY"]).post(REPORT_URL, {"signal": other_signal.id})

    assert response.status_code == 403
    assert LocalSignalReport.objects.count() == 0


def test_worker_cannot_impersonate_another_worker():
    """The serializer has no field to accept one; attribution is always
    `request.user` — this asserts the input shape enforces that, not a
    behaviour that could silently regress if a field were ever added."""

    from community.serializers import LocalSignalReportCreateSerializer

    assert "worker" not in LocalSignalReportCreateSerializer().fields


# ---------------------------------------------------------------------------
# 3 & 4 — officer sees only, and can only reach, their own village's reports
# ---------------------------------------------------------------------------
def test_officer_receives_only_own_village_reports(villages, workers, officers):
    signal_a = add_signal(villages["KVL"], week_label="2026-W35")
    signal_b = add_signal(villages["ARY"], week_label="2026-W36")
    api_for(workers["KVL"]).post(REPORT_URL, {"signal": signal_a.id})
    api_for(workers["ARY"]).post(REPORT_URL, {"signal": signal_b.id})

    officer_b_reports = api_for(officers["ARY"]).get(COMMUNITY_REPORTS_URL).data[
        "local_signal_reports"
    ]
    assert len(officer_b_reports) == 1
    assert officer_b_reports[0]["village_name"] == "Manikkampatti"

    officer_a_reports = api_for(officers["KVL"]).get(COMMUNITY_REPORTS_URL).data[
        "local_signal_reports"
    ]
    assert len(officer_a_reports) == 1
    assert officer_a_reports[0]["village_name"] == "Kovilur"


def test_officer_cannot_reach_another_villages_report_via_dashboard_or_list(
    villages, workers, officers
):
    signal_b = add_signal(villages["ARY"])
    api_for(workers["ARY"]).post(REPORT_URL, {"signal": signal_b.id})

    # No by-id detail endpoint exists for this model at all — every read is
    # the village-scoped list, so there is no URL/id an officer could probe.
    officer_a_dashboard = api_for(officers["KVL"]).get(DASHBOARD_URL).data
    assert officer_a_dashboard["new_local_signal_reports"] == 0
    assert officer_a_dashboard["recent_local_signal_reports"] == []


def test_worker_role_rejected_from_officer_endpoints(villages, workers):
    response = api_for(workers["ARY"]).get(DASHBOARD_URL)
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 6 — duplicate submission is idempotent, a new period is never blocked
# ---------------------------------------------------------------------------
def test_duplicate_submission_does_not_create_a_second_row(villages, workers):
    village = villages["ARY"]
    signal = add_signal(village, week_label="2026-W35")
    client = api_for(workers["ARY"])

    first = client.post(REPORT_URL, {"signal": signal.id, "note": "first"})
    second = client.post(REPORT_URL, {"signal": signal.id, "note": "second, ignored"})

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.data["report"]["id"] == second.data["report"]["id"]
    assert second.data["created"] is False
    assert LocalSignalReport.objects.count() == 1
    # The first submission's note wins — a retry never silently overwrites it.
    assert LocalSignalReport.objects.get().note == "first"


def test_a_new_reporting_period_is_a_new_report(villages, workers):
    village = villages["ARY"]
    week_1 = add_signal(village, week_label="2026-W35")
    week_2 = add_signal(village, week_label="2026-W36")
    client = api_for(workers["ARY"])

    client.post(REPORT_URL, {"signal": week_1.id})
    response = client.post(REPORT_URL, {"signal": week_2.id})

    assert response.status_code == 201
    assert LocalSignalReport.objects.count() == 2


# ---------------------------------------------------------------------------
# 7, 8 & 9 — unread on the dashboard, view-acknowledges, stays listed after
# ---------------------------------------------------------------------------
def test_unread_report_appears_on_officer_dashboard(villages, workers, officers):
    signal = add_signal(villages["ARY"])
    api_for(workers["ARY"]).post(REPORT_URL, {"signal": signal.id, "note": "note"})

    dashboard = api_for(officers["ARY"]).get(DASHBOARD_URL).data
    assert dashboard["new_local_signal_reports"] == 1
    assert len(dashboard["recent_local_signal_reports"]) == 1
    assert dashboard["recent_local_signal_reports"][0]["acknowledged"] is False


def test_opening_community_reports_acknowledges_and_clears_the_dashboard_count(
    villages, workers, officers
):
    signal = add_signal(villages["ARY"])
    api_for(workers["ARY"]).post(REPORT_URL, {"signal": signal.id})
    officer_client = api_for(officers["ARY"])
    assert officer_client.get(DASHBOARD_URL).data["new_local_signal_reports"] == 1

    payload = officer_client.get(COMMUNITY_REPORTS_URL).data
    # The response for this same call still shows it as it was: new.
    assert payload["local_signal_reports"][0]["acknowledged"] is False

    # But it is acknowledged now, and stays visible — never removed.
    assert officer_client.get(DASHBOARD_URL).data["new_local_signal_reports"] == 0
    second_view = officer_client.get(COMMUNITY_REPORTS_URL).data
    assert len(second_view["local_signal_reports"]) == 1
    assert second_view["local_signal_reports"][0]["acknowledged"] is True


def test_dismissing_without_opening_the_list_leaves_it_unread(villages, workers, officers):
    """The dashboard read alone (what a 'Dismiss' click leaves behind) must
    never itself acknowledge anything — only opening the persistent list
    does, exactly like the sibling CommunityReport indicator."""

    signal = add_signal(villages["ARY"])
    api_for(workers["ARY"]).post(REPORT_URL, {"signal": signal.id})
    officer_client = api_for(officers["ARY"])

    officer_client.get(DASHBOARD_URL)
    officer_client.get(DASHBOARD_URL)

    assert officer_client.get(DASHBOARD_URL).data["new_local_signal_reports"] == 1
    assert LocalSignalReport.objects.get().acknowledged_at is None
