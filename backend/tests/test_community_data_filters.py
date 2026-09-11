"""Severity and health-signal filtering on Community Data → Reported cases over time.

The filters have to actually filter — a control that only changes a label would
tell an officer something untrue about a trend — and they have to stay inside
the aggregation boundary: nothing here may reach a patient record.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from alerts.models import Alert
from community.models import CommunityReport, CommunityReportEntry
from core.constants import SignalCategory

pytestmark = pytest.mark.django_db

ENDPOINT = "/api/officer/community-data/"


def monday_of(date: dt.date) -> dt.date:
    return date - dt.timedelta(days=date.weekday())


def week_label(date: dt.date) -> str:
    iso = date.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def report(village, worker, start: dt.date, entries: dict[str, int]):
    record = CommunityReport.objects.create(
        village=village,
        worker=worker,
        week_label=week_label(start),
        period_start=start,
        period_end=start + dt.timedelta(days=6),
    )
    CommunityReportEntry.objects.bulk_create(
        [
            CommunityReportEntry(report=record, category=category, case_count=count)
            for category, count in entries.items()
        ]
    )
    return record


def alert(village, start: dt.date, category: str, severity: str):
    return Alert.objects.create(
        village=village,
        cluster=village.cluster,
        category=category,
        week_label=week_label(start),
        period_start=start,
        period_end=start + dt.timedelta(days=6),
        title=f"{category} signals",
        summary="Synthetic test alert.",
        severity=severity,
    )


@pytest.fixture
def village_officer(db, village, django_user_model):
    return django_user_model.objects.create_user(
        username="officer.kvl",
        password="demo1234",
        role=django_user_model.Role.HEALTH_OFFICER,
        full_name="Dr. Test",
        village=village,
    )


@pytest.fixture
def reported_weeks(db, village, worker):
    """Three weeks of reporting; fever climbing, respiratory steady."""

    this_week = monday_of(timezone.localdate())
    weeks = [this_week - dt.timedelta(days=14 * 1), this_week - dt.timedelta(days=7), this_week]
    report(village, worker, weeks[0], {SignalCategory.FEVER: 8, SignalCategory.RESPIRATORY: 5})
    report(village, worker, weeks[1], {SignalCategory.FEVER: 12, SignalCategory.RESPIRATORY: 5})
    report(village, worker, weeks[2], {SignalCategory.FEVER: 18, SignalCategory.RESPIRATORY: 5})
    return weeks


def series(client, query: str = ""):
    response = client.get(f"{ENDPOINT}?period=14{query}")
    assert response.status_code == 200
    return response.json()["series"]


def totals(series_payload) -> dict[str, int]:
    out: dict[str, int] = {}
    for point in series_payload["points"]:
        for key in series_payload["keys"]:
            out[key] = out.get(key, 0) + int(point.get(key) or 0)
    return out


# ---------------------------------------------------------------------------
# Unfiltered behaviour is preserved
# ---------------------------------------------------------------------------
def test_the_chart_still_works_with_no_filters(api, village_officer, reported_weeks):
    api.force_authenticate(user=village_officer)
    payload = series(api)

    assert payload["is_empty"] is False
    assert "Fever / febrile illness" in payload["keys"]
    assert totals(payload)["Fever / febrile illness"] == 38


def test_filter_options_come_from_the_existing_vocabulary(
    api, village_officer, reported_weeks
):
    api.force_authenticate(user=village_officer)
    filters = api.get(f"{ENDPOINT}?period=14").json()["filters"]

    assert filters["severity"]["selected"] == "ALL"
    assert [option["value"] for option in filters["severity"]["options"]] == [
        "ALL",
        "LOW",
        "MODERATE",
        "HIGH",
    ]
    categories = {option["value"] for option in filters["category"]["options"]}
    assert {"ALL", "FEVER", "RESPIRATORY", "SKIN", "OTHER"} <= categories


# ---------------------------------------------------------------------------
# Health-signal filter
# ---------------------------------------------------------------------------
def test_selecting_one_signal_shows_only_that_signal(
    api, village_officer, reported_weeks
):
    api.force_authenticate(user=village_officer)
    payload = series(api, "&category=FEVER")

    assert payload["keys"] == ["Fever / febrile illness"]
    assert [int(point["Fever / febrile illness"]) for point in payload["points"]] == [
        8,
        12,
        18,
    ]
    assert payload["trend"]["direction"] == "INCREASING"
    assert "fever" in payload["title"].lower()


def test_a_steady_signal_reads_as_stable(api, village_officer, reported_weeks):
    api.force_authenticate(user=village_officer)
    payload = series(api, "&category=RESPIRATORY")

    assert payload["trend"]["direction"] == "STABLE"
    assert "holding steady" in payload["trend_note"]


def test_a_signal_with_no_data_is_an_empty_state_not_a_broken_chart(
    api, village_officer, reported_weeks
):
    api.force_authenticate(user=village_officer)
    payload = series(api, "&category=MATERNAL")

    assert payload["is_empty"] is True
    assert payload["points"] == []
    assert payload["empty_message"] == "Insufficient data for this selection."


# ---------------------------------------------------------------------------
# Severity filter
# ---------------------------------------------------------------------------
def test_severity_narrows_the_chart_to_the_matching_weeks(
    api, village_officer, village, reported_weeks
):
    alert(village, reported_weeks[2], SignalCategory.FEVER, Alert.Severity.HIGH)
    alert(village, reported_weeks[0], SignalCategory.FEVER, Alert.Severity.MODERATE)

    api.force_authenticate(user=village_officer)

    high = series(api, "&severity=HIGH")
    assert totals(high)["Fever / febrile illness"] == 18
    assert len(high["points"]) == 1

    moderate = series(api, "&severity=MODERATE")
    assert totals(moderate)["Fever / febrile illness"] == 8


def test_severity_and_signal_filters_work_together(
    api, village_officer, village, reported_weeks
):
    alert(village, reported_weeks[2], SignalCategory.FEVER, Alert.Severity.HIGH)
    alert(village, reported_weeks[2], SignalCategory.RESPIRATORY, Alert.Severity.LOW)

    api.force_authenticate(user=village_officer)

    payload = series(api, "&severity=HIGH&category=FEVER")
    assert payload["keys"] == ["Fever / febrile illness"]
    assert totals(payload)["Fever / febrile illness"] == 18

    mismatch = series(api, "&severity=HIGH&category=RESPIRATORY")
    assert mismatch["is_empty"] is True


def test_severity_with_no_alerts_is_an_empty_state(
    api, village_officer, reported_weeks
):
    api.force_authenticate(user=village_officer)
    payload = series(api, "&severity=LOW")

    assert payload["is_empty"] is True
    assert payload["empty_message"] == "Insufficient data for this selection."


def test_severity_does_not_cross_the_village_boundary(
    api, village_officer, village, other_village, worker, reported_weeks
):
    """An alert raised elsewhere must not unlock another village's counts."""

    alert(other_village, reported_weeks[2], SignalCategory.FEVER, Alert.Severity.HIGH)

    api.force_authenticate(user=village_officer)
    payload = series(api, "&severity=HIGH")

    assert payload["is_empty"] is True


# ---------------------------------------------------------------------------
# Bad input and privacy
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "query",
    [
        "&severity=EXTREME",
        "&category=NOT_A_CATEGORY",
        "&severity=&category=",
        "&severity=%20%20",
    ],
)
def test_unusable_filter_values_fall_back_instead_of_failing(
    api, village_officer, reported_weeks, query
):
    api.force_authenticate(user=village_officer)
    response = api.get(f"{ENDPOINT}?period=14{query}")

    assert response.status_code == 200
    assert response.json()["series"]["is_empty"] is False


def test_medium_is_accepted_as_a_word_for_moderate(
    api, village_officer, village, reported_weeks
):
    alert(village, reported_weeks[2], SignalCategory.FEVER, Alert.Severity.MODERATE)

    api.force_authenticate(user=village_officer)
    payload = series(api, "&severity=MEDIUM")

    assert payload["is_empty"] is False
    assert payload["applied"]["severity"] == Alert.Severity.MODERATE


def test_the_filtered_chart_stays_aggregated(
    api, village_officer, village, reported_weeks, patient
):
    """No patient identifier may appear anywhere in the filtered payload."""

    alert(village, reported_weeks[2], SignalCategory.FEVER, Alert.Severity.HIGH)

    api.force_authenticate(user=village_officer)
    body = api.get(f"{ENDPOINT}?period=14&severity=HIGH&category=FEVER").content.decode()

    assert patient.patient_code not in body
    assert patient.display_name not in body
