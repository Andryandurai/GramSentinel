"""Pending follow-ups: priority order, status, patient filtering and detail.

The ordering must come from the stored due dates, not from a fixed list, so
these tests create follow-ups out of order and assert the response puts them
back in urgency order.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from assessments.followups import (
    DUE_TODAY,
    OVERDUE,
    UPCOMING,
    resolve_status,
)
from assessments.models import FollowUp, PatientAssessment
from patients.models import Patient

pytestmark = pytest.mark.django_db

DASHBOARD = "/api/worker/dashboard/"


def make_patient(village, code, name):
    return Patient.objects.create(
        patient_code=code, display_name=name, age_years=30, village=village
    )


def followup(patient, days, *, status=FollowUp.Status.PENDING, notes=""):
    return FollowUp.objects.create(
        patient=patient,
        due_date=timezone.localdate() + dt.timedelta(days=days),
        status=status,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Status derivation
# ---------------------------------------------------------------------------
def test_status_is_derived_from_the_stored_date():
    today = dt.date(2026, 8, 14)

    assert resolve_status(dt.date(2026, 8, 11), "PENDING", today) == OVERDUE
    assert resolve_status(dt.date(2026, 8, 14), "PENDING", today) == DUE_TODAY
    assert resolve_status(dt.date(2026, 8, 19), "PENDING", today) == UPCOMING


def test_a_recorded_decision_outranks_the_date():
    """Completed and missed are human decisions; a date cannot override them."""

    today = dt.date(2026, 8, 14)

    assert resolve_status(dt.date(2026, 8, 1), "COMPLETED", today) == "COMPLETED"
    assert resolve_status(dt.date(2026, 8, 1), "MISSED", today) == "MISSED"


def test_a_missing_date_is_handled_rather_than_crashing():
    assert resolve_status(None, "PENDING", dt.date(2026, 8, 14)) == "UNSCHEDULED"


# ---------------------------------------------------------------------------
# On the dashboard
# ---------------------------------------------------------------------------
def test_pending_followups_are_ordered_by_urgency(worker_api, village):
    later = make_patient(village, "KVL-P-011", "Later")
    overdue = make_patient(village, "KVL-P-012", "Overdue")
    today_patient = make_patient(village, "KVL-P-013", "Today")
    soon = make_patient(village, "KVL-P-014", "Soon")

    # Deliberately created out of order.
    followup(later, 9)
    followup(today_patient, 0)
    followup(soon, 2)
    followup(overdue, -3)

    rows = worker_api.get(DASHBOARD).json()["pending_followups"]

    assert [row["patient_code"] for row in rows] == [
        "KVL-P-012",
        "KVL-P-013",
        "KVL-P-014",
        "KVL-P-011",
    ]
    assert [row["followup_status"] for row in rows] == [
        OVERDUE,
        DUE_TODAY,
        UPCOMING,
        UPCOMING,
    ]
    assert rows[0]["due_description"] == "Overdue by 3 days"
    assert rows[1]["due_description"] == "Due today"


def test_same_date_falls_back_to_a_stable_secondary_order(worker_api, village):
    b = make_patient(village, "KVL-P-021", "Beta")
    a = make_patient(village, "KVL-P-022", "Alpha")
    followup(b, 3)
    followup(a, 3)

    rows = worker_api.get(DASHBOARD).json()["pending_followups"]

    assert [row["patient_name"] for row in rows] == ["Alpha", "Beta"]


def test_completed_followups_are_not_in_the_pending_card(worker_api, patient):
    followup(patient, -4, status=FollowUp.Status.COMPLETED)

    payload = worker_api.get(DASHBOARD).json()

    assert payload["pending_followups"] == []
    assert payload["followup_summary"]["empty_message"] == "No pending follow-ups."


def test_summary_counts_and_patient_options_match_the_list(worker_api, village):
    one = make_patient(village, "KVL-P-031", "One")
    two = make_patient(village, "KVL-P-032", "Two")
    followup(one, -1)
    followup(one, 4)
    followup(two, 0)

    summary = worker_api.get(DASHBOARD).json()["followup_summary"]

    assert summary["counts"] == {
        "total": 3,
        "shown": 3,
        "overdue": 1,
        "due_today": 1,
        "upcoming": 1,
        "undated": 0,
    }
    options = {p["patient_code"]: p["pending_count"] for p in summary["patients"]}
    assert options == {"KVL-P-031": 2, "KVL-P-032": 1}


def test_overdue_outside_the_selected_week_is_reported_not_hidden(
    worker_api, patient, village
):
    today = timezone.localdate()
    monday = today - dt.timedelta(days=today.weekday())
    PatientAssessment.objects.create(
        patient=patient,
        village=village,
        symptoms=["fever"],
        duration_days=1,
        primary_category="FEVER",
        triage_level="ROUTINE",
        encounter_date=monday - dt.timedelta(days=7),
        is_draft=False,
    )
    followup(patient, -9)   # an earlier week
    followup(patient, 1)    # this week

    payload = worker_api.get(DASHBOARD).json()
    weeks = {option["label"]: option for option in payload["weeks"]}
    current = [o for o in weeks.values() if o["is_current_week"]][0]

    filtered = worker_api.get(f"{DASHBOARD}?week={current['value']}").json()
    summary = filtered["followup_summary"]

    assert summary["overdue_outside_period"] == 1
    assert "All weeks" in summary["overdue_outside_message"]


def test_village_isolation_holds_for_followups(api, worker, other_village):
    outsider = make_patient(other_village, "MLR-P-009", "Elsewhere")
    followup(outsider, -1)

    api.force_authenticate(user=worker)
    payload = api.get(DASHBOARD).json()

    assert payload["pending_followups"] == []
    assert payload["followup_summary"]["patients"] == []


# ---------------------------------------------------------------------------
# Filtering and patient detail
# ---------------------------------------------------------------------------
def test_followup_list_can_be_narrowed_to_one_patient(worker_api, village):
    one = make_patient(village, "KVL-P-041", "One")
    two = make_patient(village, "KVL-P-042", "Two")
    followup(one, 1)
    followup(two, 2)

    rows = worker_api.get(f"/api/followups/?pending=1&patient={one.id}").json()

    assert [row["patient_code"] for row in rows] == ["KVL-P-041"]


def test_patient_filter_cannot_reach_another_village(worker_api, other_village):
    outsider = make_patient(other_village, "MLR-P-010", "Elsewhere")
    followup(outsider, 1)

    rows = worker_api.get(f"/api/followups/?patient={outsider.id}").json()

    assert rows == []


def test_patient_detail_carries_the_followups(worker_api, patient):
    followup(patient, -2, notes="Recheck temperature.")
    followup(patient, 5, notes="Second review.")
    followup(patient, -20, status=FollowUp.Status.COMPLETED, notes="Recovered.")

    payload = worker_api.get(f"/api/patients/{patient.id}/").json()

    assert [row["followup_status"] for row in payload["followups"]] == [
        OVERDUE,
        UPCOMING,
        "COMPLETED",
    ]
    assert payload["followup_summary"]["pending_count"] == 2
    assert payload["followups"][0]["notes"] == "Recheck temperature."


def test_patient_detail_without_followups_is_not_an_error(worker_api, patient):
    payload = worker_api.get(f"/api/patients/{patient.id}/").json()

    assert payload["followups"] == []
    assert payload["followup_summary"]["pending_count"] == 0
    assert payload["followup_summary"]["next_due_date"] is None
    assert payload["followup_summary"]["empty_message"]
