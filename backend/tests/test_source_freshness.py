"""Source Freshness Indicator.

Covers the two properties the feature exists to guarantee:

  - a missing source is reported as missing and never as zero;
  - freshness is informational and changes no safety or severity outcome.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from community.freshness import classify, freshness_report, humanise_age, summarise
from community.models import CommunitySignal, DataSource
from core.constants import FreshnessStatus, SignalCategory, SourceKind

from .conftest import WEEK_END, WEEK_LABEL, WEEK_START


def ago(**kwargs) -> dt.datetime:
    return timezone.now() - dt.timedelta(**kwargs)


# --- classification --------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "delta", "reported", "expected"),
    [
        # The worked examples from the feature specification, in order.
        (SourceKind.CHW, dt.timedelta(minutes=20), True, FreshnessStatus.FRESH),
        (SourceKind.PHC, dt.timedelta(hours=3), True, FreshnessStatus.FRESH),
        (SourceKind.PHARMACY, dt.timedelta(days=2), True, FreshnessStatus.AGING),
        (SourceKind.SCHOOL, dt.timedelta(days=1), False, FreshnessStatus.MISSING),
        (SourceKind.LAB, dt.timedelta(days=4), True, FreshnessStatus.STALE),
        # A CHW offline for five hours — the combined-feature example.
        (SourceKind.CHW, dt.timedelta(hours=5), True, FreshnessStatus.AGING),
    ],
)
def test_classification_matches_specification(kind, delta, reported, expected):
    now = timezone.now()
    status, _ = classify(
        now - delta, source_kind=kind, reported_this_period=reported, now=now
    )
    assert status == expected


def test_never_reported_source_is_missing():
    status, explanation = classify(
        None, source_kind=SourceKind.LAB, reported_this_period=False
    )
    assert status == FreshnessStatus.MISSING
    assert "has ever been received" in explanation


def test_missing_wins_over_age_for_a_recently_updated_source():
    """A source can have delivered an hour ago and still owe this period.

    "Nothing for the current period" is the statement an officer must not
    misread, so it takes precedence over the age comparison.
    """

    status, explanation = classify(
        ago(hours=1),
        source_kind=SourceKind.PHC,
        reported_this_period=False,
    )
    assert status == FreshnessStatus.MISSING
    assert "No report this period" in explanation


def test_clock_skew_does_not_produce_a_negative_age():
    """A device clock ahead of the server must not read as 'in 3 hours'."""

    assert humanise_age(dt.timedelta(minutes=-30)) == "just now"


def test_missing_source_never_carries_a_numeric_value(db, village, sources):
    """Safety Rule 8, at the presentation layer.

    A missing source is the single easiest thing in a surveillance system to
    render as a zero. The payload carries no number at all so it cannot be.
    """

    rows = freshness_report(list(sources.values()), week_label=WEEK_LABEL)
    missing = [r for r in rows if r["status"] == FreshnessStatus.MISSING]

    assert missing, "expected sources with nothing reported to be missing"
    for row in missing:
        assert row["value"] is None
        assert row["reported_this_period"] is False
        assert "0" not in row["explanation"].replace("R8", "")


def test_worst_sources_are_listed_first(db, village, sources):
    fresh = sources[SourceKind.CHW]
    fresh.last_report_at = timezone.now()
    fresh.save(update_fields=["last_report_at"])
    CommunitySignal.objects.create(
        source=fresh,
        village=village,
        category=SignalCategory.FEVER,
        week_label=WEEK_LABEL,
        period_start=WEEK_START,
        period_end=WEEK_END,
        value=4.0,
        is_reported=True,
    )

    rows = freshness_report(list(sources.values()), week_label=WEEK_LABEL)
    assert rows[0]["status"] == FreshnessStatus.MISSING
    assert rows[-1]["source_kind"] == SourceKind.CHW
    assert rows[-1]["status"] == FreshnessStatus.FRESH


def test_summary_counts_every_source_once(db, village, sources):
    rows = freshness_report(list(sources.values()), week_label=WEEK_LABEL)
    summary = summarise(rows)
    assert summary["total_sources"] == len(rows)
    assert (
        summary["fresh"] + summary["aging"] + summary["stale"] + summary["missing"]
        == len(rows)
    )


# --- the endpoint ----------------------------------------------------------


def test_officer_sees_freshness_for_registered_sources(officer_api, village, sources):
    response = officer_api.get("/api/officer/source-freshness/")
    assert response.status_code == 200

    body = response.json()
    assert len(body["sources"]) == len(sources)
    assert body["summary"]["total_sources"] == len(sources)
    # The safety position is stated in the payload, not left to the reader.
    assert "does not change alert severity" in body["safety_note"]
    assert "never counted as zero" in body["interpretation_note"]


def test_worker_cannot_read_the_officer_freshness_view(worker_api, sources):
    assert worker_api.get("/api/officer/source-freshness/").status_code == 403


def test_freshness_is_scoped_to_the_officers_village(
    db, api, village, other_village, sources
):
    """Village isolation holds for freshness as it does for every other view."""

    from django.contrib.auth import get_user_model

    User = get_user_model()
    scoped = User.objects.create_user(
        username="officer.kvl",
        password="demo1234",
        role=User.Role.HEALTH_OFFICER,
        full_name="Scoped Officer",
        village=village,
    )
    DataSource.objects.create(
        code="LAB-MLR",
        name="Lab — Village C",
        kind=SourceKind.LAB,
        village=other_village,
    )

    api.force_authenticate(user=scoped)
    body = api.get("/api/officer/source-freshness/").json()

    codes = {row["source_code"] for row in body["sources"]}
    assert "LAB-MLR" not in codes
    assert all(row["village_code"] == village.code for row in body["sources"])


# --- the link to ingestion -------------------------------------------------


def test_accepted_ingestion_marks_a_source_fresh(db, village, sources):
    """The mechanism behind "worker reconnects -> officer sees Fresh"."""

    from integrations.ingestion import ingest_batch

    source = sources[SourceKind.CHW]
    source.last_report_at = ago(days=3)
    source.save(update_fields=["last_report_at"])

    assert (
        classify(
            source.last_report_at,
            source_kind=source.kind,
            reported_this_period=True,
        )[0]
        == FreshnessStatus.STALE
    )

    ingest_batch(
        [
            {
                "source_code": source.code,
                "category": SignalCategory.FEVER,
                "week_label": WEEK_LABEL,
                "value": 7,
                "baseline": 2,
                "is_reported": True,
            }
        ],
        week_label=WEEK_LABEL,
    )

    source.refresh_from_db()
    assert classify(
        source.last_report_at, source_kind=source.kind, reported_this_period=True
    )[0] == FreshnessStatus.FRESH


def test_a_not_reported_record_does_not_make_a_source_look_fresh(
    db, village, sources
):
    """A source saying "I have nothing" is not a source delivering data."""

    from integrations.ingestion import ingest_batch

    source = sources[SourceKind.SCHOOL]
    assert source.last_report_at is None

    ingest_batch(
        [
            {
                "source_code": source.code,
                "category": SignalCategory.FEVER,
                "week_label": WEEK_LABEL,
                "value": None,
                "is_reported": False,
            }
        ],
        week_label=WEEK_LABEL,
    )

    source.refresh_from_db()
    assert source.last_report_at is None
