"""Officer alert popup fix — backend supplement to `test_local_signal_reports
.py` (which already covers persistence, cross-village isolation, unread
count, acknowledge-on-list-open, dismiss-leaves-unread, and duplicate
prevention). This file covers the remaining scenarios specific to a Health
Officer receiving several unread reports at once, since the frontend fix
(`Dashboard.tsx`) now tracks *which* report IDs it has shown, not just
whether *any* popup has ever fired — so the backend's own "every unread
report is present, none lost" guarantee is what that fix actually depends
on.
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


def api_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def village(db) -> Village:
    return Village.objects.create(code="POP", name="Popupville", cluster="Village Cluster A")


@pytest.fixture
def officer(db, village):
    return User.objects.create_user(
        username="popup.officer", password="x", role=User.Role.HEALTH_OFFICER, village=village
    )


@pytest.fixture
def worker(db, village):
    return User.objects.create_user(
        username="popup.worker", password="x", role=User.Role.CHW_PHC_WORKER, village=village
    )


def add_signal(village: Village, week_label: str, value: float = 18.0, baseline: float = 10.0) -> CommunitySignal:
    source, _ = DataSource.objects.get_or_create(
        code=f"CHW-{village.code}", defaults={"name": "CHW", "kind": "CHW", "village": village},
    )
    return CommunitySignal.objects.create(
        source=source, village=village, category=SignalCategory.FEVER, week_label=week_label,
        period_start="2026-08-24", period_end="2026-08-30", value=value, baseline=baseline,
        unit="reports", is_reported=True,
    )


def test_multiple_unread_reports_are_all_present_not_lost(village, worker, officer):
    for i in range(3):
        signal = add_signal(village, week_label=f"2026-W3{i}")
        api_for(worker).post(REPORT_URL, {"signal": signal.id, "note": f"report {i}"})

    dashboard = api_for(officer).get(DASHBOARD_URL).data
    assert dashboard["new_local_signal_reports"] == 3
    returned_notes = {r["note"] for r in dashboard["recent_local_signal_reports"]}
    assert returned_notes == {"report 0", "report 1", "report 2"}


def test_recent_reports_capped_but_unread_count_reflects_true_total(village, worker, officer):
    for i in range(7):
        signal = add_signal(village, week_label=f"2026-W{i:02d}")
        api_for(worker).post(REPORT_URL, {"signal": signal.id})

    dashboard = api_for(officer).get(DASHBOARD_URL).data
    assert dashboard["new_local_signal_reports"] == 7
    assert len(dashboard["recent_local_signal_reports"]) == 5


def test_unread_count_is_a_live_query_not_cached_across_requests(village, worker, officer):
    """Two 'overlapping' dashboard reads (simulating a race between a stale
    request and a fresh one) must each independently reflect the true
    database state at the moment they ran — neither can serve a stale
    in-process cached count."""

    officer_client = api_for(officer)
    assert officer_client.get(DASHBOARD_URL).data["new_local_signal_reports"] == 0

    signal = add_signal(village, week_label="2026-W41")
    api_for(worker).post(REPORT_URL, {"signal": signal.id})

    # A second, independent client instance (a different in-flight request)
    # must see the same fresh state — nothing is memoised per-process.
    assert api_for(officer).get(DASHBOARD_URL).data["new_local_signal_reports"] == 1
    assert officer_client.get(DASHBOARD_URL).data["new_local_signal_reports"] == 1


def test_each_report_id_is_stable_across_repeated_dashboard_reads(village, worker, officer):
    """The frontend fix tracks *which* report ids it has already shown in a
    `Set<reportId>` — this only works if the same report keeps the same id
    across repeated, non-mutating dashboard reads."""

    signal = add_signal(village, week_label="2026-W42")
    api_for(worker).post(REPORT_URL, {"signal": signal.id})
    officer_client = api_for(officer)

    first_id = officer_client.get(DASHBOARD_URL).data["recent_local_signal_reports"][0]["id"]
    second_id = officer_client.get(DASHBOARD_URL).data["recent_local_signal_reports"][0]["id"]
    assert first_id == second_id
    assert LocalSignalReport.objects.get().id == first_id
