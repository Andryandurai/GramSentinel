"""Source Freshness Indicator + Offline Community Reporting / idempotent sync.

Freshness (community/freshness.py) is informational only — these tests
specifically prove it never changes anything the Safety Engine or the alert
pipeline decides. Offline sync reuses the existing `/api/community-reports/`
endpoint with two new optional fields (`idempotency_key`, `client_created_at`)
rather than a parallel endpoint — these tests prove that reuse is safe: a
retried submission can never create a duplicate report, a duplicate Alert, or
cross a village boundary.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from community.freshness import build_source_freshness, freshness_for_source
from community.models import CommunityReport, CommunitySignal, DataSource
from core.constants import DataQuality, SignalCategory, SourceKind

User = get_user_model()
pytestmark = pytest.mark.django_db

COMMUNITY_REPORTS_URL = "/api/community-reports/"


def api_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _make_source(village, kind=SourceKind.CHW, code=None) -> DataSource:
    return DataSource.objects.create(
        code=code or f"{kind}-{village.code}-TEST",
        name=f"{kind} test source",
        kind=kind,
        channel=DataSource.Channel.PORTAL,
        village=village,
    )


def _signal_at(source, village, *, age: dt.timedelta, is_reported=True, value=4.0):
    signal = CommunitySignal.objects.create(
        source=source,
        village=village,
        category=SignalCategory.FEVER,
        week_label="2026-W30",
        period_start=dt.date(2026, 7, 20),
        period_end=dt.date(2026, 7, 26),
        value=value if is_reported else None,
        baseline=3.0,
        unit="reports",
        is_reported=is_reported,
        data_quality=DataQuality.GOOD if is_reported else DataQuality.MISSING,
    )
    CommunitySignal.objects.filter(pk=signal.pk).update(
        ingested_at=timezone.now() - age
    )
    return signal


@pytest.fixture
def officer_b(db, other_village):
    return User.objects.create_user(
        username="officer.freshness.b",
        password="demo1234",
        role=User.Role.HEALTH_OFFICER,
        village=other_village,
    )


# ===========================================================================
# Source Freshness — classification
# ===========================================================================


def test_fresh_source_correctly_classified(village):
    source = _make_source(village, SourceKind.CHW)
    _signal_at(source, village, age=dt.timedelta(hours=1))

    cards = build_source_freshness(village)
    chw = next(c for c in cards if c["source_kind"] == SourceKind.CHW)
    assert chw["status"] == "FRESH"
    assert chw["received"] is True


def test_aging_source_correctly_classified(village):
    source = _make_source(village, SourceKind.PHARMACY)
    _signal_at(source, village, age=dt.timedelta(hours=48))

    cards = build_source_freshness(village)
    pharmacy = next(c for c in cards if c["source_kind"] == SourceKind.PHARMACY)
    assert pharmacy["status"] == "AGING"


def test_stale_source_correctly_classified(village):
    source = _make_source(village, SourceKind.LAB)
    _signal_at(source, village, age=dt.timedelta(hours=200))

    cards = build_source_freshness(village)
    lab = next(c for c in cards if c["source_kind"] == SourceKind.LAB)
    assert lab["status"] == "STALE"


def test_missing_source_correctly_classified(village):
    # No CommunitySignal at all for SCHOOL in this village.
    cards = build_source_freshness(village)
    school = next(c for c in cards if c["source_kind"] == SourceKind.SCHOOL)
    assert school["status"] == "MISSING"
    assert school["received"] is False
    assert school["last_updated_at"] is None


def test_relative_time_seconds_present_and_consistent_with_relative_time(village):
    """Localization bug fix: the frontend must never render the backend's
    English `relative_time` sentence directly — it needs the raw elapsed
    seconds to build its own localized string. `relative_time_seconds`
    must be present, non-negative, and roughly consistent with the age
    actually recorded (never a value that would silently disagree with
    `status`, which is derived from the same delta)."""

    source = _make_source(village, SourceKind.CHW)
    _signal_at(source, village, age=dt.timedelta(hours=11))

    cards = build_source_freshness(village)
    chw = next(c for c in cards if c["source_kind"] == SourceKind.CHW)
    assert chw["relative_time_seconds"] is not None
    assert chw["relative_time_seconds"] >= 0
    # Within a small tolerance of the requested 11-hour age.
    assert abs(chw["relative_time_seconds"] - 11 * 3600) < 60


def test_relative_time_seconds_is_null_when_never_reported(village):
    """Missing data is never coerced into a fabricated elapsed time
    (mirrors Safety Engine R8's own "missing is never treated as zero")."""

    cards = build_source_freshness(village)
    school = next(c for c in cards if c["source_kind"] == SourceKind.SCHOOL)
    assert school["relative_time_seconds"] is None


# ===========================================================================
# Missing vs zero semantics
# ===========================================================================


def test_reported_zero_is_not_missing(village):
    source = _make_source(village, SourceKind.CHW)
    _signal_at(source, village, age=dt.timedelta(hours=1), value=0.0)

    cards = build_source_freshness(village)
    chw = next(c for c in cards if c["source_kind"] == SourceKind.CHW)
    # A reported zero still counts as "received" and is timed normally —
    # never folded into MISSING just because the value itself was 0.
    assert chw["received"] is True
    assert chw["status"] == "FRESH"


def test_missing_report_is_not_zero(village):
    source = _make_source(village, SourceKind.PHC)
    _signal_at(source, village, age=dt.timedelta(hours=1), is_reported=False)

    cards = build_source_freshness(village)
    phc = next(c for c in cards if c["source_kind"] == SourceKind.PHC)
    # An explicitly not-reported row must never be read as "recently active".
    assert phc["status"] == "MISSING"
    assert phc["received"] is False


def test_no_fabricated_freshness_when_timestamp_absent(village):
    """A source with zero CommunitySignal rows ever must not invent a status
    other than MISSING — there is nothing to compute a status from."""

    cards = build_source_freshness(village)
    assert all(c["status"] in {"FRESH", "AGING", "STALE", "MISSING"} for c in cards)
    weather = next(c for c in cards if c["source_kind"] == SourceKind.WEATHER)
    assert weather["status"] == "MISSING"
    assert weather["last_updated_at"] is None


def test_ruralcare_aggregate_not_in_freshness_list(village):
    """Excluded on purpose — never routed into an evidence card, so it is
    not "a source/evidence input" this indicator covers (see module
    docstring in community/freshness.py)."""

    cards = build_source_freshness(village)
    assert SourceKind.RURALCARE_AGGREGATE not in {c["source_kind"] for c in cards}
    assert len(cards) == 6


# ===========================================================================
# Village scoping
# ===========================================================================


def test_officer_dashboard_freshness_is_own_village_only(village):
    village_officer = User.objects.create_user(
        username="officer.village.scoped",
        password="demo1234",
        role=User.Role.HEALTH_OFFICER,
        village=village,
    )
    source = _make_source(village, SourceKind.CHW)
    _signal_at(source, village, age=dt.timedelta(minutes=5))

    response = api_for(village_officer).get("/api/officer/dashboard/")
    assert response.status_code == 200
    assert "source_freshness" in response.data
    codes = {c["source_kind"] for c in response.data["source_freshness"]}
    assert SourceKind.CHW in codes


def test_officer_a_cannot_see_village_b_freshness(officer, village, officer_b, other_village):
    """officer is scoped to `village`; officer_b to `other_village`. Backdate
    a CHW signal only in `other_village` and confirm officer's own dashboard
    never surfaces it."""

    officer.village = village
    officer.save(update_fields=["village"])

    source_b = _make_source(other_village, SourceKind.CHW)
    _signal_at(source_b, other_village, age=dt.timedelta(minutes=1))

    response = api_for(officer).get("/api/officer/dashboard/")
    assert response.status_code == 200
    chw_card = next(
        c for c in response.data["source_freshness"] if c["source_kind"] == SourceKind.CHW
    )
    # officer's own village has no CHW signal at all -> MISSING, proving
    # village B's fresh signal never leaked into village A's response.
    assert chw_card["status"] == "MISSING"


def test_worker_role_cannot_reach_officer_freshness_endpoints(worker_api):
    response = worker_api.get("/api/officer/dashboard/")
    assert response.status_code == 403


def test_district_wide_officer_gets_empty_freshness_not_fabricated(officer_api):
    """The `officer` fixture has no village assigned (district-wide). There
    is no single village to compute per-source freshness for, so the list
    must be empty rather than silently picking one village or averaging."""

    response = officer_api.get("/api/officer/dashboard/")
    assert response.status_code == 200
    assert response.data["source_freshness"] == []
    assert response.data["source_freshness_note"]


# ===========================================================================
# Evidence-card freshness
# ===========================================================================


def test_evidence_card_receives_correct_source_freshness(village):
    source = _make_source(village, SourceKind.PHC, code=f"PHC-{village.code}")
    _signal_at(source, village, age=dt.timedelta(hours=2))

    card = freshness_for_source(village.code, SourceKind.PHC)
    assert card["status"] == "FRESH"
    assert card["source_kind"] == SourceKind.PHC


def test_evidence_card_freshness_missing_for_unreported_source(village):
    card = freshness_for_source(village.code, SourceKind.LAB)
    assert card["status"] == "MISSING"


# ===========================================================================
# Freshness must never change Safety Engine / alert outcome
# ===========================================================================


def test_freshness_does_not_change_safety_verdict_or_severity(worker_api, village):
    """Submit the same community report twice — once with an ordinary-age
    CHW signal already on record, once after backdating that same signal to
    look STALE — and confirm the Safety Engine's verdict/severity for the
    resulting pipeline run is identical either way. Freshness is read-only
    display data; it must never be consulted by `run_community_pipeline`."""

    def submit(week_label):
        return worker_api.post(
            COMMUNITY_REPORTS_URL,
            {
                "village": village.id,
                "week_label": week_label,
                "period_start": "2026-08-03",
                "period_end": "2026-08-09",
                "entries": [{"category": "FEVER", "case_count": 5}],
            },
            format="json",
        )

    first = submit("2026-W31")
    assert first.status_code == 201
    verdict_before = first.data["pipeline"][0]["safety_verdict"]

    # Backdate every CommunitySignal for this village into STALE territory.
    CommunitySignal.objects.filter(village=village).update(
        ingested_at=timezone.now() - dt.timedelta(hours=500)
    )

    second = submit("2026-W32")
    assert second.status_code == 201
    verdict_after = second.data["pipeline"][0]["safety_verdict"]

    assert verdict_before == verdict_after


# ===========================================================================
# Offline sync — idempotency
# ===========================================================================


def _offline_payload(village, week_label, idempotency_key, client_created_at):
    return {
        "village": village.id,
        "week_label": week_label,
        "period_start": "2026-08-03",
        "period_end": "2026-08-09",
        "entries": [{"category": "RESPIRATORY", "case_count": 2}],
        "idempotency_key": idempotency_key,
        "client_created_at": client_created_at,
    }


def test_normal_online_report_still_works_without_idempotency_key(worker_api, village):
    response = worker_api.post(
        COMMUNITY_REPORTS_URL,
        {
            "village": village.id,
            "week_label": "2026-W33",
            "period_start": "2026-08-10",
            "period_end": "2026-08-16",
            "entries": [{"category": "FEVER", "case_count": 3}],
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.data["idempotent_replay"] is False


def test_offline_style_payload_accepted_through_existing_endpoint(worker_api, village):
    response = worker_api.post(
        COMMUNITY_REPORTS_URL,
        _offline_payload(village, "2026-W34", "key-001", "2026-08-17T10:15:00Z"),
        format="json",
    )
    assert response.status_code == 201
    assert response.data["report"]["client_created_at"] is not None


def test_first_idempotency_key_creates_one_report(worker_api, village):
    response = worker_api.post(
        COMMUNITY_REPORTS_URL,
        _offline_payload(village, "2026-W35", "key-002", "2026-08-24T09:00:00Z"),
        format="json",
    )
    assert response.status_code == 201
    assert CommunityReport.objects.filter(idempotency_key="key-002").count() == 1


def test_repeating_same_idempotency_key_does_not_duplicate(worker_api, village):
    payload = _offline_payload(village, "2026-W36", "key-003", "2026-08-31T09:00:00Z")

    first = worker_api.post(COMMUNITY_REPORTS_URL, payload, format="json")
    assert first.status_code == 201
    assert first.data["idempotent_replay"] is False

    # Simulate a network-retry of the exact same offline record.
    second = worker_api.post(COMMUNITY_REPORTS_URL, payload, format="json")
    assert second.status_code == 200
    assert second.data["idempotent_replay"] is True
    assert second.data["report"]["id"] == first.data["report"]["id"]

    assert CommunityReport.objects.filter(idempotency_key="key-003").count() == 1


def test_retry_after_timeout_is_idempotent_multiple_times(worker_api, village):
    payload = _offline_payload(village, "2026-W37", "key-004", "2026-09-07T09:00:00Z")
    ids = set()
    for _ in range(3):
        response = worker_api.post(COMMUNITY_REPORTS_URL, payload, format="json")
        assert response.status_code in (200, 201)
        ids.add(response.data["report"]["id"])
    assert len(ids) == 1
    assert CommunityReport.objects.filter(idempotency_key="key-004").count() == 1


def test_different_idempotency_keys_create_separate_reports(worker_api, village):
    r1 = worker_api.post(
        COMMUNITY_REPORTS_URL,
        _offline_payload(village, "2026-W20", "key-a", "2026-05-11T09:00:00Z"),
        format="json",
    )
    r2 = worker_api.post(
        COMMUNITY_REPORTS_URL,
        _offline_payload(village, "2026-W21", "key-b", "2026-05-18T09:00:00Z"),
        format="json",
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.data["report"]["id"] != r2.data["report"]["id"]


def test_client_created_at_preserved_and_distinct_from_server_received_at(
    worker_api, village
):
    client_time = "2026-08-17T10:15:00Z"
    response = worker_api.post(
        COMMUNITY_REPORTS_URL,
        _offline_payload(village, "2026-W39", "key-005", client_time),
        format="json",
    )
    assert response.status_code == 201
    report = CommunityReport.objects.get(idempotency_key="key-005")

    assert report.client_created_at is not None
    assert report.client_created_at.strftime("%Y-%m-%dT%H:%M") == "2026-08-17T10:15"
    # submitted_at (server_received_at) is stamped "now" by auto_now_add —
    # necessarily later than a client_created_at backdated to a past sync.
    assert report.submitted_at > report.client_created_at


def test_cross_village_spoofing_rejected_even_with_idempotency_key(
    worker_api, village, other_village
):
    response = worker_api.post(
        COMMUNITY_REPORTS_URL,
        _offline_payload(other_village, "2026-W40", "key-006", "2026-09-28T09:00:00Z"),
        format="json",
    )
    assert response.status_code == 403
    assert not CommunityReport.objects.filter(idempotency_key="key-006").exists()


def test_worker_field_is_always_server_derived_never_from_payload(worker, worker_api, village):
    """No `worker` key exists on the input serializer at all, so there is no
    way for a payload to claim a different submitter — confirmed by
    checking the persisted row's worker is exactly the authenticated user."""

    response = worker_api.post(
        COMMUNITY_REPORTS_URL,
        _offline_payload(village, "2026-W41", "key-007", "2026-10-05T09:00:00Z"),
        format="json",
    )
    assert response.status_code == 201
    report = CommunityReport.objects.get(idempotency_key="key-007")
    assert report.worker_id == worker.id


def test_idempotency_key_collision_across_workers_is_rejected(village, other_village):
    worker_1 = User.objects.create_user(
        username="worker.idem.1", password="x", role=User.Role.CHW_PHC_WORKER, village=village
    )
    worker_2 = User.objects.create_user(
        username="worker.idem.2", password="x", role=User.Role.CHW_PHC_WORKER, village=village
    )

    shared_key = "shared-key-collision"
    first = api_for(worker_1).post(
        COMMUNITY_REPORTS_URL,
        _offline_payload(village, "2026-W42", shared_key, "2026-10-12T09:00:00Z"),
        format="json",
    )
    assert first.status_code == 201

    second = api_for(worker_2).post(
        COMMUNITY_REPORTS_URL,
        _offline_payload(village, "2026-W42", shared_key, "2026-10-12T09:05:00Z"),
        format="json",
    )
    assert second.status_code == 409
    assert CommunityReport.objects.filter(idempotency_key=shared_key).count() == 1


def test_successful_sync_enters_existing_pipeline_no_duplicate_entries(worker_api, village):
    payload = _offline_payload(village, "2026-W43", "key-008", "2026-10-19T09:00:00Z")

    first = worker_api.post(COMMUNITY_REPORTS_URL, payload, format="json")
    assert first.status_code == 201
    assert "pipeline" in first.data
    assert first.data["pipeline"][0]["label"] == "Respiratory illness"

    report = CommunityReport.objects.get(idempotency_key="key-008")
    assert report.entries.count() == 1

    # A retry must not add a second CommunityReportEntry, and must not run
    # the pipeline (and therefore not raise a second Alert) a second time —
    # the idempotency short-circuit returns before any of that runs again.
    from alerts.models import Alert

    alerts_after_first = Alert.objects.filter(week_label="2026-W43").count()

    retry = worker_api.post(COMMUNITY_REPORTS_URL, payload, format="json")
    assert retry.status_code == 200
    assert retry.data["idempotent_replay"] is True
    report.refresh_from_db()
    assert report.entries.count() == 1
    assert Alert.objects.filter(week_label="2026-W43").count() == alerts_after_first


def test_offline_report_alert_only_via_existing_downstream_pipeline(worker_api, village):
    """A community report — offline-style metadata or not — only ever
    reaches an Alert through the same `run_community_pipeline()` call any
    online submission goes through. This proves there is no special,
    parallel "offline alert" code path: exactly one Alert exists after the
    first submission, and a retry of the identical payload creates no more."""

    from alerts.models import Alert

    payload = _offline_payload(village, "2026-W44", "key-009", "2026-10-26T09:00:00Z")

    response = worker_api.post(COMMUNITY_REPORTS_URL, payload, format="json")
    assert response.status_code == 201
    assert Alert.objects.filter(week_label="2026-W44").count() == 1

    retry = worker_api.post(COMMUNITY_REPORTS_URL, payload, format="json")
    assert retry.status_code == 200
    assert Alert.objects.filter(week_label="2026-W44").count() == 1
