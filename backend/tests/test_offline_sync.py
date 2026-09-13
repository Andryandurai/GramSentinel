"""Offline reporting and automatic synchronisation.

The properties under test are the ones a worker's data depends on:

  - a report redelivered by an unstable connection is stored exactly once;
  - a redelivery does not run the pipeline again, so one observation cannot
    produce two alerts;
  - the worker's original creation time survives the delay before syncing;
  - alerts are still produced only by the backend pipeline, never by the fact
    that a report was captured offline.
"""

from __future__ import annotations

import datetime as dt
import uuid

from django.utils import timezone

from alerts.models import Alert
from community.models import CommunityReport, OfflineSubmission
from core.constants import SignalCategory

from .conftest import WEEK_END, WEEK_LABEL, WEEK_START


def payload(**overrides) -> dict:
    body = {
        "week_label": WEEK_LABEL,
        "period_start": WEEK_START.isoformat(),
        "period_end": WEEK_END.isoformat(),
        "entries": [{"category": SignalCategory.FEVER, "case_count": 6}],
        "unusual_observation": False,
        "notes": "",
    }
    body.update(overrides)
    return body


def test_online_submission_still_works_without_sync_fields(
    worker_api, village, sources
):
    """The pre-existing path is untouched: no uid, no client time, no change."""

    response = worker_api.post(
        "/api/community-reports/",
        payload(village=village.id),
        format="json",
    )
    assert response.status_code == 201

    body = response.json()
    assert body["duplicate"] is False
    assert body["sync"] is None
    assert CommunityReport.objects.count() == 1


def test_the_same_report_delivered_twice_is_stored_once(
    worker_api, village, sources
):
    """The central guarantee. An unstable connection retries; the uid is the
    device's statement that this is the same report, not a second one."""

    uid = str(uuid.uuid4())
    created = timezone.now() - dt.timedelta(hours=3)
    body = payload(
        village=village.id,
        client_report_uid=uid,
        client_created_at=created.isoformat(),
        captured_offline=True,
    )

    first = worker_api.post("/api/community-reports/", body, format="json")
    assert first.status_code == 201
    assert first.json()["duplicate"] is False

    second = worker_api.post("/api/community-reports/", body, format="json")
    # A success, not a conflict: the device's goal is met and it should stop
    # retrying.
    assert second.status_code == 200
    assert second.json()["duplicate"] is True

    assert CommunityReport.objects.count() == 1
    assert OfflineSubmission.objects.count() == 1
    assert OfflineSubmission.objects.get(client_report_uid=uid).retry_count == 1


def test_repeated_retries_are_all_absorbed(worker_api, village, sources):
    uid = str(uuid.uuid4())
    body = payload(
        village=village.id,
        client_report_uid=uid,
        client_created_at=timezone.now().isoformat(),
        captured_offline=True,
    )

    for _ in range(5):
        worker_api.post("/api/community-reports/", body, format="json")

    assert CommunityReport.objects.count() == 1
    assert OfflineSubmission.objects.get(client_report_uid=uid).retry_count == 4


def test_a_redelivery_does_not_run_the_pipeline_again(
    worker_api, village, sources
):
    """One observation must not be able to raise two alerts."""

    uid = str(uuid.uuid4())
    body = payload(
        village=village.id,
        client_report_uid=uid,
        client_created_at=timezone.now().isoformat(),
        captured_offline=True,
        entries=[{"category": SignalCategory.FEVER, "case_count": 40}],
    )

    worker_api.post("/api/community-reports/", body, format="json")
    alerts_after_first = Alert.objects.count()

    duplicate = worker_api.post("/api/community-reports/", body, format="json")
    assert duplicate.json()["pipeline"] == []
    assert Alert.objects.count() == alerts_after_first


def test_creation_time_and_sync_time_are_kept_distinct(
    worker_api, village, sources
):
    """'Report created 10:15, report synced 13:30' — both times survive."""

    created = timezone.now() - dt.timedelta(hours=3, minutes=15)
    response = worker_api.post(
        "/api/community-reports/",
        payload(
            village=village.id,
            client_report_uid=str(uuid.uuid4()),
            client_created_at=created.isoformat(),
            captured_offline=True,
        ),
        format="json",
    )
    assert response.status_code == 201

    report = CommunityReport.objects.get()
    assert report.captured_offline is True
    # The device's time is preserved, not replaced by arrival time.
    assert abs((report.client_created_at - created).total_seconds()) < 2
    assert report.submitted_at > report.client_created_at

    sync = response.json()["sync"]
    assert sync["delayed_seconds"] > 3 * 3600


def test_two_distinct_offline_reports_both_arrive(worker_api, village, sources):
    """Distinct uids are distinct reports, even from one worker."""

    first = worker_api.post(
        "/api/community-reports/",
        payload(
            village=village.id,
            client_report_uid=str(uuid.uuid4()),
            client_created_at=timezone.now().isoformat(),
            captured_offline=True,
        ),
        format="json",
    )
    second = worker_api.post(
        "/api/community-reports/",
        payload(
            village=village.id,
            week_label="2026-W33",
            period_start="2026-08-10",
            period_end="2026-08-16",
            client_report_uid=str(uuid.uuid4()),
            client_created_at=timezone.now().isoformat(),
            captured_offline=True,
        ),
        format="json",
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert OfflineSubmission.objects.count() == 2
    assert CommunityReport.objects.count() == 2


def test_a_synced_offline_report_goes_through_the_normal_pipeline(
    worker_api, village, sources
):
    """Offline capture changes when a report arrives, not how it is handled.

    The response still carries the pipeline outcome with its safety verdict,
    which is the evidence that the deterministic engine ran.
    """

    response = worker_api.post(
        "/api/community-reports/",
        payload(
            village=village.id,
            client_report_uid=str(uuid.uuid4()),
            client_created_at=timezone.now().isoformat(),
            captured_offline=True,
        ),
        format="json",
    )
    outcomes = response.json()["pipeline"]

    assert outcomes, "a synced report must still be analysed by the backend"
    for outcome in outcomes:
        assert outcome["safety_verdict"] in {"PASS", "DOWNGRADE", "BLOCK"}


def test_offline_report_cannot_be_filed_for_another_village(
    worker_api, other_village, sources
):
    """Village isolation is not weakened by the sync path."""

    response = worker_api.post(
        "/api/community-reports/",
        payload(
            village=other_village.id,
            client_report_uid=str(uuid.uuid4()),
            client_created_at=timezone.now().isoformat(),
            captured_offline=True,
        ),
        format="json",
    )
    assert response.status_code == 403
    assert CommunityReport.objects.count() == 0


def test_a_rejected_report_leaves_no_receipt_to_block_a_corrected_retry(
    worker_api, village, sources
):
    """A validation failure must not consume the uid.

    If it did, the worker's corrected resubmission would be answered with
    "already received" and their report would never arrive.
    """

    uid = str(uuid.uuid4())
    bad = worker_api.post(
        "/api/community-reports/",
        payload(
            village=village.id,
            client_report_uid=uid,
            client_created_at=timezone.now().isoformat(),
            entries=[{"category": SignalCategory.OTHER, "case_count": 3}],
        ),
        format="json",
    )
    assert bad.status_code == 400  # 'Other' requires a description
    assert OfflineSubmission.objects.count() == 0

    good = worker_api.post(
        "/api/community-reports/",
        payload(
            village=village.id,
            client_report_uid=uid,
            client_created_at=timezone.now().isoformat(),
            entries=[
                {
                    "category": SignalCategory.OTHER,
                    "case_count": 3,
                    "description": "Three households reporting unusual rash.",
                }
            ],
        ),
        format="json",
    )
    assert good.status_code == 201
    assert CommunityReport.objects.count() == 1
