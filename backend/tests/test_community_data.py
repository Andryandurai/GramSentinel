"""Officer Community Data view and the trend calculation behind it."""

from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from community.models import CommunityReport, CommunityReportEntry
from core.constants import SignalCategory
from core.models import Village
from core.trends import (
    DECREASING,
    INCREASING,
    INSUFFICIENT_DATA,
    STABLE,
    compute_trend,
    period_windows,
)

User = get_user_model()
pytestmark = pytest.mark.django_db

ENDPOINT = "/api/officer/community-data/"


# ---------------------------------------------------------------------------
# Trend maths — pure, no database
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "current,previous,direction,pct",
    [
        (15, 10, INCREASING, 50.0),   # spec example
        (10, 15, DECREASING, -33.3),  # spec example
        (10, 10, STABLE, 0.0),        # spec example
        (8, 9, DECREASING, -11.1),    # spec example: -11% reads as decreasing
        (18, 12, INCREASING, 50.0),
        (5, 5, STABLE, 0.0),
        (0, 4, DECREASING, -100.0),
        (105, 100, STABLE, 5.0),      # below the noise threshold
    ],
)
def test_trend_matches_the_specified_examples(current, previous, direction, pct):
    trend = compute_trend(current, previous)
    assert trend.direction == direction
    assert trend.change_pct == pytest.approx(pct, abs=0.1)


def test_no_previous_period_is_insufficient_data_not_a_trend():
    trend = compute_trend(12, None, has_previous_period_data=False)
    assert trend.direction == INSUFFICIENT_DATA
    assert trend.change_pct is None
    assert trend.previous is None
    assert trend.label == "Insufficient data"


def test_growth_from_zero_reports_new_activity_rather_than_infinity():
    """A percentage change from zero is undefined; say so."""

    trend = compute_trend(7, 0)
    assert trend.direction == INCREASING
    assert trend.change_pct is None
    assert trend.is_new_activity is True


def test_zero_to_zero_is_stable_not_a_division_error():
    trend = compute_trend(0, 0)
    assert trend.direction == STABLE
    assert trend.change_pct == 0.0


def test_period_windows_do_not_overlap():
    (c_start, c_end), (p_start, p_end) = period_windows(7, dt.date(2026, 8, 20))
    assert (c_end - c_start).days == 6
    assert (p_end - p_start).days == 6
    assert p_end < c_start


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def villages(db):
    return {
        code: Village.objects.create(
            code=code, name=name, cluster="Village Cluster A"
        )
        for code, name in (("KVL", "Kovilur"), ("ARY", "Ariyanur"))
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


def api_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def add_report(village, days_ago: int, entries: dict, worker=None, unusual=False):
    start = timezone.localdate() - dt.timedelta(days=days_ago)
    report = CommunityReport.objects.create(
        village=village,
        worker=worker,
        week_label=f"W-{days_ago}",
        period_start=start,
        period_end=start + dt.timedelta(days=6),
        unusual_observation=unusual,
    )
    CommunityReportEntry.objects.bulk_create(
        [
            CommunityReportEntry(
                report=report,
                category=category,
                case_count=count,
                description=description,
            )
            for category, (count, description) in entries.items()
        ]
    )
    return report


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------
def test_endpoint_requires_officer_role(villages, db):
    worker = User.objects.create_user(
        username="w", password="x", role=User.Role.CHW_PHC_WORKER
    )
    assert api_for(worker).get(ENDPOINT).status_code == 403
    assert APIClient().get(ENDPOINT).status_code == 401


def test_categories_report_current_previous_and_direction(villages, officers):
    village = villages["KVL"]
    add_report(village, 20, {SignalCategory.FEVER: (12, "")})
    add_report(village, 3, {SignalCategory.FEVER: (18, "")})

    data = api_for(officers["KVL"]).get(f"{ENDPOINT}?period=14").data
    fever = next(c for c in data["categories"] if c["category"] == "FEVER")

    assert fever["current"] == 18
    assert fever["previous"] == 12
    assert fever["change_pct"] == pytest.approx(50.0)
    assert fever["direction"] == INCREASING
    assert fever["label"] == "Fever / febrile illness"


def test_decrease_and_stable_are_reported_correctly(villages, officers):
    village = villages["KVL"]
    add_report(
        village,
        20,
        {SignalCategory.RESPIRATORY: (9, ""), SignalCategory.SKIN: (5, "")},
    )
    add_report(
        village,
        3,
        {SignalCategory.RESPIRATORY: (8, ""), SignalCategory.SKIN: (5, "")},
    )

    rows = {
        c["category"]: c
        for c in api_for(officers["KVL"]).get(f"{ENDPOINT}?period=14").data[
            "categories"
        ]
    }
    assert rows["RESPIRATORY"]["direction"] == DECREASING
    assert rows["SKIN"]["direction"] == STABLE


def test_category_with_no_previous_history_shows_insufficient_data(
    villages, officers
):
    village = villages["KVL"]
    add_report(village, 20, {SignalCategory.FEVER: (10, "")})
    # SKIN appears only in the current period.
    add_report(
        village,
        3,
        {SignalCategory.FEVER: (11, ""), SignalCategory.SKIN: (4, "")},
    )

    rows = {
        c["category"]: c
        for c in api_for(officers["KVL"]).get(f"{ENDPOINT}?period=14").data[
            "categories"
        ]
    }
    assert rows["SKIN"]["direction"] == INSUFFICIENT_DATA
    assert rows["SKIN"]["previous"] is None
    assert rows["SKIN"]["change_pct"] is None


def test_summary_counts_directions(villages, officers):
    village = villages["KVL"]
    add_report(
        village,
        20,
        {
            SignalCategory.FEVER: (10, ""),
            SignalCategory.RESPIRATORY: (10, ""),
            SignalCategory.DIARRHOEAL: (10, ""),
        },
    )
    add_report(
        village,
        3,
        {
            SignalCategory.FEVER: (20, ""),
            SignalCategory.RESPIRATORY: (5, ""),
            SignalCategory.DIARRHOEAL: (10, ""),
        },
    )

    summary = api_for(officers["KVL"]).get(f"{ENDPOINT}?period=14").data["summary"]
    assert summary["increasing"] == 1
    assert summary["decreasing"] == 1
    assert summary["stable"] == 1
    assert summary["total_current_cases"] == 35


def test_expanded_categories_are_supported(villages, officers):
    add_report(
        villages["KVL"],
        3,
        {
            SignalCategory.MATERNAL: (2, ""),
            SignalCategory.HEAT_RELATED: (1, ""),
            SignalCategory.MENTAL_HEALTH: (1, ""),
        },
    )
    labels = {
        c["label"]
        for c in api_for(officers["KVL"]).get(ENDPOINT).data["categories"]
    }
    assert "Maternal health concerns" in labels
    assert "Heat-related illness" in labels
    assert "Mental health concerns" in labels


def test_written_observations_are_surfaced(villages, officers):
    add_report(
        villages["KVL"],
        3,
        {SignalCategory.SKIN: (6, "Itchy lesions near the tank.")},
        unusual=True,
    )
    data = api_for(officers["KVL"]).get(ENDPOINT).data
    observation = data["recent_observations"][0]

    assert "Itchy lesions" in observation["description"]
    assert observation["unusual_observation"] is True


# ---------------------------------------------------------------------------
# Aggregation only — no individual records
# ---------------------------------------------------------------------------
def test_response_contains_no_patient_information(villages, officers):
    from patients.models import Patient
    from assessments.models import PatientAssessment

    patient = Patient.objects.create(
        patient_code="KVL-P-777",
        display_name="Identifiable Person",
        age_years=41,
        village=villages["KVL"],
    )
    PatientAssessment.objects.create(
        patient=patient,
        village=villages["KVL"],
        symptoms=["fever"],
        primary_category=SignalCategory.FEVER,
        triage_level="URGENT",
        is_draft=False,
        encounter_date=timezone.localdate(),
    )
    add_report(villages["KVL"], 3, {SignalCategory.FEVER: (5, "")})

    flat = str(api_for(officers["KVL"]).get(ENDPOINT).data)
    assert patient.patient_code not in flat
    assert patient.display_name not in flat
    assert "triage" not in flat.lower()


# ---------------------------------------------------------------------------
# Village isolation
# ---------------------------------------------------------------------------
def test_officer_sees_only_their_own_village_data(villages, officers):
    add_report(villages["KVL"], 3, {SignalCategory.FEVER: (18, "")})
    add_report(villages["ARY"], 3, {SignalCategory.SKIN: (9, "")})

    a = api_for(officers["KVL"]).get(ENDPOINT).data
    b = api_for(officers["ARY"]).get(ENDPOINT).data

    assert {c["category"] for c in a["categories"]} == {"FEVER"}
    assert {c["category"] for c in b["categories"]} == {"SKIN"}
    assert a["scope"]["village_name"] == "Kovilur"
    assert b["scope"]["village_name"] == "Ariyanur"


def test_district_officer_without_a_village_sees_everything(villages, db):
    district = User.objects.create_user(
        username="officer", password="demo1234", role=User.Role.HEALTH_OFFICER
    )
    add_report(villages["KVL"], 3, {SignalCategory.FEVER: (18, "")})
    add_report(villages["ARY"], 3, {SignalCategory.SKIN: (9, "")})

    data = api_for(district).get(ENDPOINT).data
    assert {c["category"] for c in data["categories"]} == {"FEVER", "SKIN"}
    assert data["scope"]["is_district_wide"] is True


# ---------------------------------------------------------------------------
# Period filter and error handling
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("days", [7, 14, 21])
def test_each_period_option_works(villages, officers, days):
    add_report(villages["KVL"], 2, {SignalCategory.FEVER: (5, "")})
    response = api_for(officers["KVL"]).get(f"{ENDPOINT}?period={days}")

    assert response.status_code == 200
    assert response.data["period"]["days"] == days


@pytest.mark.parametrize("value", ["999", "-3", "abc", "", "null"])
def test_invalid_period_falls_back_to_the_default(villages, officers, value):
    response = api_for(officers["KVL"]).get(f"{ENDPOINT}?period={value}")
    assert response.status_code == 200
    assert response.data["period"]["days"] == 14


def test_period_filter_actually_changes_the_window(villages, officers):
    village = villages["KVL"]
    add_report(village, 18, {SignalCategory.FEVER: (100, "")})
    add_report(village, 2, {SignalCategory.FEVER: (5, "")})

    week = api_for(officers["KVL"]).get(f"{ENDPOINT}?period=7").data
    three_weeks = api_for(officers["KVL"]).get(f"{ENDPOINT}?period=21").data

    week_fever = next(c for c in week["categories"] if c["category"] == "FEVER")
    long_fever = next(
        c for c in three_weeks["categories"] if c["category"] == "FEVER"
    )
    assert week_fever["current"] == 5
    assert long_fever["current"] == 105


def test_empty_village_returns_a_clean_empty_state(villages, officers):
    data = api_for(officers["KVL"]).get(ENDPOINT).data

    assert data["is_empty"] is True
    assert data["categories"] == []
    assert data["series"]["points"] == []
    assert data["recent_observations"] == []
    assert data["summary"]["total_current_cases"] == 0
    assert data["summary"]["increasing"] == 0


def test_no_values_are_null_or_nan_in_a_populated_response(villages, officers):
    add_report(villages["KVL"], 20, {SignalCategory.FEVER: (10, "")})
    add_report(
        villages["KVL"],
        3,
        {SignalCategory.FEVER: (12, ""), SignalCategory.EYE: (2, "")},
    )

    for row in api_for(officers["KVL"]).get(ENDPOINT).data["categories"]:
        assert isinstance(row["current"], int)
        assert row["direction_label"]
        # previous/change may be null, but only when insufficient data says so.
        if row["direction"] != INSUFFICIENT_DATA and not row["is_new_activity"]:
            assert row["previous"] is not None
            assert row["change_pct"] is not None


# ---------------------------------------------------------------------------
# Existing alert workflow untouched
# ---------------------------------------------------------------------------
def test_community_data_does_not_disturb_the_alert_endpoints(villages, officers):
    add_report(villages["KVL"], 3, {SignalCategory.FEVER: (18, "")})
    client = api_for(officers["KVL"])

    assert client.get(ENDPOINT).status_code == 200
    assert client.get("/api/alerts/").status_code == 200
    assert client.get("/api/officer/dashboard/").status_code == 200
    assert client.get("/api/officer/community-reports/").status_code == 200
