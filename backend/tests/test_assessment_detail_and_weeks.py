"""The optional 'Other' symptom, optional day-wise history, and the week filter.

Three things are being protected here:

  * the new fields are stored and read back, so they are not display-only;
  * they are *supplementary* — an identical presentation must produce an
    identical triage level whether or not free text was added, which is what
    stops free text from reaching around the deterministic rules;
  * the dashboard's week filter narrows data the worker was already permitted
    to see, and never widens it.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from assessments.models import FollowUp, PatientAssessment
from assessments.weeks import build_week_options, resolve_selection
from patients.models import Patient

User = get_user_model()

pytestmark = pytest.mark.django_db


def monday_of(date: dt.date) -> dt.date:
    return date - dt.timedelta(days=date.weekday())


def week_label(date: dt.date) -> str:
    iso = date.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def record(patient, *, encounter_date, triage_level="ROUTINE", **extra):
    """A stored assessment, written directly so the date can be chosen."""

    return PatientAssessment.objects.create(
        patient=patient,
        village=patient.village,
        symptoms=["fever"],
        duration_days=2,
        primary_category="FEVER",
        triage_level=triage_level,
        encounter_date=encounter_date,
        is_draft=False,
        **extra,
    )


# ---------------------------------------------------------------------------
# 1. The optional "Other" symptom
# ---------------------------------------------------------------------------
def test_other_symptom_is_optional_and_existing_symptoms_are_unaffected(
    worker_api, patient
):
    response = worker_api.post(
        "/api/assessments/preview/",
        {
            "patient": patient.id,
            "symptoms": ["fever", "headache"],
            "duration_days": 3,
            "temperature_c": 38.4,
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["support"]["triage_level"] == "CONCERNING"
    assert (
        response.data["support"]["supplementary_context"][
            "has_supplementary_detail"
        ]
        is False
    )


def test_other_description_is_stored_and_shown_in_the_patient_history(
    worker_api, patient
):
    described = "Persistent skin irritation and swelling around the left arm."

    created = worker_api.post(
        "/api/assessments/",
        {
            "patient": patient.id,
            "symptoms": ["fever"],
            "duration_days": 2,
            "other_symptom_selected": True,
            "other_symptom_text": described,
        },
        format="json",
    )
    assert created.status_code == 201
    assert created.data["assessment"]["other_symptom_text"] == described

    stored = PatientAssessment.objects.get(pk=created.data["assessment"]["id"])
    assert stored.other_symptom_text == described

    history = worker_api.get(f"/api/patients/{patient.id}/")
    assert history.data["assessments"][0]["other_symptom_text"] == described


def test_selecting_other_without_describing_it_is_refused(worker_api, patient):
    response = worker_api.post(
        "/api/assessments/preview/",
        {
            "patient": patient.id,
            "symptoms": ["fever"],
            "duration_days": 2,
            "other_symptom_selected": True,
            "other_symptom_text": "   ",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "other_symptom_text" in str(response.data)


def test_other_alone_is_enough_to_record_an_encounter(worker_api, patient):
    response = worker_api.post(
        "/api/assessments/",
        {
            "patient": patient.id,
            "symptoms": [],
            "duration_days": 1,
            "other_symptom_selected": True,
            "other_symptom_text": "Swelling of the left ankle after a fall.",
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["assessment"]["symptoms"] == []
    assert response.data["assessment"]["other_symptom_text"].startswith("Swelling")


def test_free_text_cannot_reach_around_the_deterministic_rules(worker_api, patient):
    """The safety engine reads recorded symptoms, not prose.

    Typing red-flag words into the free-text box must not move the triage
    level: the level is decided by the structured entry, exactly as it was
    before this field existed.
    """

    payload = {
        "patient": patient.id,
        "symptoms": ["fever"],
        "duration_days": 2,
    }
    without = worker_api.post(
        "/api/assessments/preview/", payload, format="json"
    ).data["support"]
    with_text = worker_api.post(
        "/api/assessments/preview/",
        {
            **payload,
            "other_symptom_selected": True,
            "other_symptom_text": "seizure, neck stiffness, unconscious",
            "symptom_timeline": [{"day": 1, "detail": "bleeding and convulsion"}],
        },
        format="json",
    ).data["support"]

    assert with_text["triage_level"] == without["triage_level"]
    assert with_text["triage_score"] == without["triage_score"]
    assert with_text["normalised_symptoms"] == without["normalised_symptoms"]
    assert with_text["red_flags"] == without["red_flags"]
    assert with_text["supplementary_context"]["interpreted_by_triage"] is False


def test_red_flag_escalation_still_fires_alongside_the_new_fields(
    worker_api, infant
):
    response = worker_api.post(
        "/api/assessments/preview/",
        {
            "patient": infant.id,
            "symptoms": ["fever"],
            "duration_days": 1,
            "other_symptom_selected": True,
            "other_symptom_text": "Mother reports poor feeding since yesterday.",
            "symptom_timeline": [{"day": 1, "detail": "warm to touch"}],
        },
        format="json",
    )
    support = response.data["support"]

    assert support["triage_level"] == "URGENT"
    assert support["escalation_forced"] is True
    assert any(f["code"] == "RF_YOUNG_INFANT_FEVER" for f in support["red_flags"])
    # The agent handoffs are still recorded end to end.
    assert len(support["agent_trace"]) == 5


# ---------------------------------------------------------------------------
# 2. Optional day-wise symptom history
# ---------------------------------------------------------------------------
def test_day_wise_details_persist_after_submission(worker_api, patient):
    created = worker_api.post(
        "/api/assessments/",
        {
            "patient": patient.id,
            "symptoms": ["fever", "headache"],
            "duration_days": 3,
            "symptom_timeline": [
                {"day": 1, "detail": "Fever and mild headache"},
                {"day": 2, "detail": "Fever increased, headache continued"},
                {"day": 3, "detail": "Fever reduced but weakness remained"},
            ],
        },
        format="json",
    )

    assert created.status_code == 201
    assert created.data["assessment"]["duration_days"] == 3
    timeline = created.data["assessment"]["symptom_timeline"]
    assert [entry["day"] for entry in timeline] == [1, 2, 3]
    assert timeline[1]["detail"] == "Fever increased, headache continued"

    detail = worker_api.get(f"/api/assessments/{created.data['assessment']['id']}/")
    assert detail.data["symptom_timeline"] == timeline


def test_partial_day_wise_entries_are_accepted_and_blank_days_dropped(
    worker_api, patient
):
    created = worker_api.post(
        "/api/assessments/",
        {
            "patient": patient.id,
            "symptoms": ["cough"],
            "duration_days": 3,
            "symptom_timeline": [
                {"day": 1, "detail": "Dry cough at night"},
                {"day": 2, "detail": "   "},
                {"day": 3, "detail": "Cough easing"},
            ],
        },
        format="json",
    )

    assert created.status_code == 201
    assert created.data["assessment"]["symptom_timeline"] == [
        {"day": 1, "detail": "Dry cough at night"},
        {"day": 3, "detail": "Cough easing"},
    ]


def test_assessment_without_day_wise_information_still_works(worker_api, patient):
    created = worker_api.post(
        "/api/assessments/",
        {"patient": patient.id, "symptoms": ["fever"], "duration_days": 2},
        format="json",
    )

    assert created.status_code == 201
    assert created.data["assessment"]["symptom_timeline"] == []
    assert created.data["assessment"]["other_symptom_text"] == ""


def test_an_assessment_recorded_before_these_fields_existed_still_reads(
    worker_api, patient
):
    """Old rows carry neither field. They must read back as 'nothing recorded'."""

    old = record(patient, encounter_date=timezone.localdate() - dt.timedelta(days=30))

    response = worker_api.get(f"/api/assessments/{old.id}/")

    assert response.status_code == 200
    assert response.data["symptom_timeline"] == []
    assert response.data["other_symptom_text"] == ""
    assert response.data["duration_days"] == 2


def test_malformed_day_wise_entries_are_rejected_not_stored(worker_api, patient):
    response = worker_api.post(
        "/api/assessments/preview/",
        {
            "patient": patient.id,
            "symptoms": ["fever"],
            "duration_days": 2,
            "symptom_timeline": [{"day": 0, "detail": "not a real day"}],
        },
        format="json",
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 3. Week options
# ---------------------------------------------------------------------------
def test_week_options_are_numbered_chronologically_from_the_data():
    first = dt.date(2026, 8, 3)  # a Monday
    options = build_week_options([first, first + dt.timedelta(days=15), None])

    assert [o["label"] for o in options] == ["Week 1", "Week 2", "Week 3"]
    assert options[0]["value"] == "2026-W32"
    assert options[0]["range_label"] == "Aug 3 – Aug 9"
    assert options[2]["end"] == dt.date(2026, 8, 23)


def test_no_data_means_no_week_options():
    assert build_week_options([]) == []
    assert build_week_options([None, None]) == []


def test_selection_accepts_a_label_a_number_or_all():
    options = build_week_options([dt.date(2026, 8, 3), dt.date(2026, 8, 12)])

    assert resolve_selection(None, options)[0] == "all"
    assert resolve_selection("all", options)[0] == "all"
    assert resolve_selection("2026-W33", options)[0] == "2026-W33"
    assert resolve_selection("2", options)[0] == "2026-W33"

    # Unusable input falls back to all weeks with an explanation, never an error.
    selected, start, end, _option, notice = resolve_selection("banana", options)
    assert (selected, start, end) == ("all", None, None)
    assert notice


# ---------------------------------------------------------------------------
# 4. The dashboard week filter
# ---------------------------------------------------------------------------
def test_dashboard_defaults_to_all_weeks_and_preserves_today(worker_api, patient):
    today = timezone.localdate()
    record(patient, encounter_date=today)
    record(patient, encounter_date=today - dt.timedelta(days=14))

    response = worker_api.get("/api/worker/dashboard/")

    assert response.status_code == 200
    assert response.data["selected_week"] == "all"
    assert response.data["period"]["is_all_weeks"] is True
    assert response.data["period"]["assessment_count"] == 2
    assert len(response.data["recent_assessments"]) == 2
    # The pre-existing "today" block is untouched by the filter.
    assert response.data["today"]["assessment_count"] == 1
    assert len(response.data["weeks"]) == 3


def test_selecting_a_week_filters_the_underlying_data(worker_api, patient):
    today = timezone.localdate()
    this_week = record(patient, encounter_date=today)
    older = record(patient, encounter_date=monday_of(today) - dt.timedelta(days=7))

    dashboard = worker_api.get(
        f"/api/worker/dashboard/?week={week_label(older.encounter_date)}"
    )

    assert dashboard.data["period"]["assessment_count"] == 1
    ids = [a["id"] for a in dashboard.data["recent_assessments"]]
    assert ids == [older.id]
    assert this_week.id not in ids
    assert dashboard.data["period"]["has_activity"] is True

    current = worker_api.get(
        f"/api/worker/dashboard/?week={week_label(this_week.encounter_date)}"
    )
    assert [a["id"] for a in current.data["recent_assessments"]] == [this_week.id]


def test_follow_ups_are_filtered_by_the_selected_week(worker_api, patient, worker):
    today = timezone.localdate()
    record(patient, encounter_date=today)
    FollowUp.objects.create(patient=patient, due_date=today, created_by=worker)
    FollowUp.objects.create(
        patient=patient,
        due_date=monday_of(today) + dt.timedelta(days=9),
        created_by=worker,
    )

    all_weeks = worker_api.get("/api/worker/dashboard/")
    assert all_weeks.data["pending_followup_count"] == 2

    this_week = worker_api.get(f"/api/worker/dashboard/?week={week_label(today)}")
    assert this_week.data["pending_followup_count"] == 1
    assert this_week.data["period"]["followup_count"] == 1


def test_a_week_with_no_activity_is_handled_not_broken(worker_api, patient):
    today = timezone.localdate()
    record(patient, encounter_date=today)
    quiet = monday_of(today) - dt.timedelta(days=14)

    response = worker_api.get(f"/api/worker/dashboard/?week={week_label(quiet)}")

    assert response.status_code == 200
    period = response.data["period"]
    assert period["assessment_count"] == 0
    assert period["has_activity"] is False
    assert period["empty_message"] == "No activity recorded for this week."
    assert response.data["recent_assessments"] == []
    # Nothing null, undefined or NaN-shaped leaks into the counters.
    for key in ("urgent_count", "concerning_count", "followup_count"):
        assert period[key] == 0


def test_an_unreadable_week_falls_back_to_all_weeks(worker_api, patient):
    record(patient, encounter_date=timezone.localdate())

    response = worker_api.get("/api/worker/dashboard/?week=not-a-week")

    assert response.status_code == 200
    assert response.data["selected_week"] == "all"
    assert response.data["period"]["notice"]
    assert response.data["period"]["assessment_count"] == 1


def test_the_week_filter_cannot_expose_another_village(
    worker_api, patient, other_village
):
    """The village scope is applied before the week filter, not after."""

    today = timezone.localdate()
    record(patient, encounter_date=today)

    elsewhere = Patient.objects.create(
        patient_code="MLR-P-900", age_years=44, village=other_village
    )
    record(elsewhere, encounter_date=today)

    other_worker = User.objects.create_user(
        username="worker.mlr",
        password="demo1234",
        role=User.Role.CHW_PHC_WORKER,
        full_name="Melur CHW",
        village=other_village,
    )
    other_api = APIClient()
    other_api.force_authenticate(user=other_worker)

    for week in ("all", week_label(today)):
        mine = worker_api.get(f"/api/worker/dashboard/?week={week}")
        theirs = other_api.get(f"/api/worker/dashboard/?week={week}")

        assert mine.data["period"]["assessment_count"] == 1
        assert theirs.data["period"]["assessment_count"] == 1
        assert [a["patient_code"] for a in mine.data["recent_assessments"]] == [
            patient.patient_code
        ]
        assert [a["patient_code"] for a in theirs.data["recent_assessments"]] == [
            elsewhere.patient_code
        ]
