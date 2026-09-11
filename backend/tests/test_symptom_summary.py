"""The Community Symptom Summary on the worker dashboard.

Three properties are protected here:

  * the counts are of *people*, so one patient with two symptoms adds one to
    each symptom row but only one to the total;
  * the summary is derived from the assessments already recorded, respects the
    week filter, and is village-scoped before it is aggregated;
  * an "Other" symptom the worker typed in their own words is represented.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from assessments.models import PatientAssessment
from assessments.symptom_summary import summarise_assessments
from patients.models import Patient

User = get_user_model()
pytestmark = pytest.mark.django_db

DASHBOARD = "/api/worker/dashboard/"


def monday_of(date: dt.date) -> dt.date:
    return date - dt.timedelta(days=date.weekday())


def record(patient, *, symptoms, encounter_date, other_symptom_text=""):
    return PatientAssessment.objects.create(
        patient=patient,
        village=patient.village,
        symptoms=symptoms,
        other_symptom_text=other_symptom_text,
        duration_days=2,
        primary_category="FEVER",
        triage_level="ROUTINE",
        encounter_date=encounter_date,
        is_draft=False,
    )


def counts(summary) -> dict[str, int]:
    return {row["label"]: row["count"] for row in summary["rows"]}


# ---------------------------------------------------------------------------
# Pure aggregation
# ---------------------------------------------------------------------------
def test_one_person_with_two_symptoms_counts_once_in_each_group():
    summary = summarise_assessments([(1, ["fever", "headache"], "")])

    assert counts(summary) == {"Fever": 1, "Headache": 1}
    assert summary["total_people_assessed"] == 1


def test_the_same_person_assessed_twice_is_still_one_person():
    summary = summarise_assessments(
        [(1, ["fever"], ""), (1, ["fever", "cough"], ""), (2, ["fever"], "")]
    )

    assert counts(summary) == {"Fever": 2, "Respiratory symptoms": 1}
    assert summary["total_people_assessed"] == 2
    assert summary["assessment_count"] == 3


def test_symptoms_map_onto_the_expected_groups():
    summary = summarise_assessments(
        [
            (1, ["fever", "chills"], ""),
            (2, ["cough", "breathlessness"], ""),
            (3, ["headache"], ""),
            (4, ["diarrhoea", "vomiting"], ""),
            (5, ["rash"], ""),
            (6, ["jaundice"], ""),
        ]
    )

    assert counts(summary) == {
        "Fever": 1,
        "Respiratory symptoms": 1,
        "Headache": 1,
        "Diarrhoeal symptoms": 1,
        "Skin-related symptoms": 1,
        "Other": 1,
    }
    assert summary["total_people_assessed"] == 6


def test_a_free_text_other_symptom_is_represented():
    summary = summarise_assessments(
        [(1, ["fever"], "swelling of the ankles for two days")]
    )

    assert counts(summary) == {"Fever": 1, "Other": 1}
    assert summary["described_other_count"] == 1


def test_unusable_symptom_data_does_not_break_the_summary():
    summary = summarise_assessments(
        [(1, None, ""), (2, "fever", ""), (3, {}, "note"), (4, ["", "  "], "")]
    )

    assert summary["total_people_assessed"] == 4
    assert summary["is_empty"] is False
    assert counts(summary).get("Fever") == 1


def test_no_assessments_gives_an_explicit_empty_state():
    summary = summarise_assessments([])

    assert summary["is_empty"] is True
    assert summary["rows"] == []
    assert summary["total_people_assessed"] == 0
    assert summary["empty_message"]


def test_summary_never_claims_a_diagnosis():
    summary = summarise_assessments([(1, ["fever"], "")])
    lowered = summary["note"].lower()

    assert "reported" in lowered
    assert "confirmed" not in lowered.replace("not confirmed", "")
    assert "diagnos" not in lowered.replace("not confirmed cases or diagnoses", "")


# ---------------------------------------------------------------------------
# On the dashboard
# ---------------------------------------------------------------------------
def test_dashboard_summary_counts_people_not_assessments(worker_api, patient, village):
    other = Patient.objects.create(
        patient_code="KVL-P-002", display_name="Second", age_years=20, village=village
    )
    today = timezone.localdate()
    record(patient, symptoms=["fever", "headache"], encounter_date=today)
    record(patient, symptoms=["fever"], encounter_date=today)
    record(other, symptoms=["cough"], encounter_date=today)

    summary = worker_api.get(DASHBOARD).json()["symptom_summary"]

    assert summary["total_people_assessed"] == 2
    assert counts(summary) == {
        "Fever": 1,
        "Headache": 1,
        "Respiratory symptoms": 1,
    }


def test_week_filter_actually_narrows_the_summary(worker_api, patient):
    this_week = monday_of(timezone.localdate())
    last_week = this_week - dt.timedelta(days=7)
    record(patient, symptoms=["fever"], encounter_date=this_week)
    record(patient, symptoms=["diarrhoea"], encounter_date=last_week)

    payload = worker_api.get(DASHBOARD).json()
    weeks = {option["label"]: option["value"] for option in payload["weeks"]}

    all_weeks = payload["symptom_summary"]
    assert counts(all_weeks) == {"Fever": 1, "Diarrhoeal symptoms": 1}
    assert all_weeks["total_people_assessed"] == 1

    first = worker_api.get(f"{DASHBOARD}?week={weeks['Week 1']}").json()
    assert counts(first["symptom_summary"]) == {"Diarrhoeal symptoms": 1}

    second = worker_api.get(f"{DASHBOARD}?week={weeks['Week 2']}").json()
    assert counts(second["symptom_summary"]) == {"Fever": 1}


def test_an_unreadable_week_falls_back_rather_than_failing(worker_api, patient):
    record(patient, symptoms=["fever"], encounter_date=timezone.localdate())

    payload = worker_api.get(f"{DASHBOARD}?week=not-a-week").json()

    assert payload["symptom_summary"]["total_people_assessed"] == 1
    assert payload["period"]["notice"]


def test_summary_is_scoped_to_the_workers_own_village(
    api, worker, patient, other_village
):
    """A neighbouring village's assessments never reach this worker's summary."""

    outsider = Patient.objects.create(
        patient_code="MLR-P-001",
        display_name="Other village",
        age_years=30,
        village=other_village,
    )
    today = timezone.localdate()
    record(patient, symptoms=["fever"], encounter_date=today)
    record(outsider, symptoms=["rash"], encounter_date=today)

    api.force_authenticate(user=worker)
    summary = api.get(DASHBOARD).json()["symptom_summary"]

    assert summary["total_people_assessed"] == 1
    assert "Skin-related symptoms" not in counts(summary)


def test_prefill_offers_only_categories_the_report_form_accepts(
    worker_api, patient
):
    record(patient, symptoms=["fever", "headache"], encounter_date=timezone.localdate())

    summary = worker_api.get(DASHBOARD).json()["symptom_summary"]
    prefill = {row["category"]: row["case_count"] for row in summary["report_prefill"]}

    assert prefill == {"FEVER": 1}  # headache has no community category
