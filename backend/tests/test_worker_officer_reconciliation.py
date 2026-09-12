"""One source of truth: a Health Worker's submitted count must reconcile
exactly with what the Health Officer's aggregated views show, for the same
village/period/category. This is Part 11's "no situation where Worker says 5
and Officer says 8" requirement, checked at the API/database level rather
than by eye.

Also covers idempotent re-seeding: running `seed_demo` twice must not create
duplicate Alert / CommunityReport rows for the demo villages.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.management import call_command
from django.utils import timezone

from alerts.models import Alert
from community.models import CommunityReport, CommunitySignal
from core.constants import SignalCategory, SourceKind

pytestmark = pytest.mark.django_db


def _this_week() -> tuple[str, dt.date, dt.date]:
    today = timezone.localdate()
    monday = today - dt.timedelta(days=today.weekday())
    sunday = monday + dt.timedelta(days=6)
    iso = monday.isocalendar()
    return f"{iso.year}-W{iso.week:02d}", monday, sunday


def test_worker_submission_reconciles_with_officer_views(worker_api, officer, village):
    officer.village = village
    officer.save(update_fields=["village"])

    from rest_framework.test import APIClient

    officer_api = APIClient()
    officer_api.force_authenticate(user=officer)

    week_label, period_start, period_end = _this_week()
    response = worker_api.post(
        "/api/community-reports/",
        {
            "village": village.id,
            "week_label": week_label,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "unusual_observation": False,
            "notes": "",
            "entries": [
                {"category": "FEVER", "case_count": 5, "description": ""},
            ],
        },
        format="json",
    )
    assert response.status_code == 201

    # 1. The CommunitySignal the Worker's own Local Signals reads.
    signal = CommunitySignal.objects.get(
        source__kind=SourceKind.CHW,
        source__village=village,
        category=SignalCategory.FEVER,
        week_label=week_label,
    )
    assert signal.value == 5

    local_signals = worker_api.get("/api/local-signals/")
    assert local_signals.status_code == 200
    fever_rows = [
        s
        for s in local_signals.data["signals"]
        if s["category"] == SignalCategory.FEVER
        and s["week_label"] == week_label
        and s["source_kind"] == SourceKind.CHW
    ]
    assert len(fever_rows) == 1
    assert fever_rows[0]["value"] == 5

    # 2. Officer Community Data — the "reported community health signals" table.
    community_data = officer_api.get("/api/officer/community-data/?period=7")
    assert community_data.status_code == 200
    fever_category = next(
        c for c in community_data.data["categories"] if c["category"] == "FEVER"
    )
    assert fever_category["current"] == 5

    # 3. Officer Dashboard — the "Community reported signals over time" chart.
    dashboard = officer_api.get("/api/officer/dashboard/")
    assert dashboard.status_code == 200
    trend = dashboard.data["community_trend"]
    fever_label = SignalCategory.FEVER.label
    week_point = next(
        (p for p in trend["points"] if p.get("week") == week_label), None
    )
    if fever_label in trend["keys"]:
        assert week_point is not None
        assert week_point[fever_label] == 5


def test_reseeding_the_demo_does_not_duplicate_alerts_or_reports():
    call_command("seed_demo")
    first_alerts = Alert.objects.count()
    first_reports = CommunityReport.objects.count()

    call_command("seed_demo")
    second_alerts = Alert.objects.count()
    second_reports = CommunityReport.objects.count()

    assert second_alerts == first_alerts
    assert second_reports == first_reports
