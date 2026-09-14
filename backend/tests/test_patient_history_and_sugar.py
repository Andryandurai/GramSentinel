"""New Assessment: Previous Assessments history, and the Sugar measurement.

Previous Assessments reuses the existing `GET /api/patients/<id>/` read
(`patients.views.PatientDetailView`, already village-scoped and already
returning `assessments` most-recent-first) — no new endpoint was added.
Sugar (`sugar_mg_dl`) is a seventh field on `PatientAssessment`, alongside
the six pre-existing ones, following the exact same optional/nullable
pattern; it is never sent to the RuralCare orchestrator (see
`assessments.views._run_agents`'s fixed payload) and — like every other
assessment field — never read by `community.aggregation`, which only ever
selects `primary_category` and a count (see
`tests/test_privacy_and_pipeline.py::test_aggregate_payload_contains_only_permitted_fields`
for the existing, exhaustive proof of that boundary).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from agents.orchestration import RuralCareOrchestrator
from assessments.models import PatientAssessment
from patients.models import Patient

User = get_user_model()
pytestmark = pytest.mark.django_db

ASSESSMENTS_URL = "/api/assessments/"


def _patient_url(pk: int) -> str:
    return f"/api/patients/{pk}/"


def api_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def worker_b(other_village):
    return User.objects.create_user(
        username="worker.other-village",
        password="demo1234",
        role=User.Role.CHW_PHC_WORKER,
        village=other_village,
    )


def _create_assessment(
    worker_api,
    patient_id: int,
    *,
    symptoms=("fever",),
    duration_days=1,
    encounter_date=None,
    sugar_mg_dl=None,
    blood_sugar_measurement_type=None,
):
    body = {
        "patient": patient_id,
        "symptoms": list(symptoms),
        "duration_days": duration_days,
    }
    if encounter_date:
        body["encounter_date"] = encounter_date
    if sugar_mg_dl is not None:
        body["sugar_mg_dl"] = sugar_mg_dl
    if blood_sugar_measurement_type is not None:
        body["blood_sugar_measurement_type"] = blood_sugar_measurement_type
    response = worker_api.post(ASSESSMENTS_URL, body, format="json")
    assert response.status_code == 201, response.data
    return response


# ---------------------------------------------------------------------------
# 2-4. Patient-specific history, empty state
# ---------------------------------------------------------------------------
def test_patient_detail_returns_only_that_patients_assessments(worker_api, patient, village):
    other_patient = Patient.objects.create(
        patient_code="KVL-P-OTHER", display_name="Someone Else", age_years=50, village=village
    )
    _create_assessment(worker_api, patient.id, symptoms=["fever"])
    _create_assessment(worker_api, other_patient.id, symptoms=["cough"])

    response = worker_api.get(_patient_url(patient.id))

    assert response.status_code == 200
    assert len(response.data["assessments"]) == 1
    assert response.data["assessments"][0]["symptoms"] == ["fever"]


def test_patient_with_no_assessments_returns_an_empty_list(worker_api, patient):
    response = worker_api.get(_patient_url(patient.id))
    assert response.status_code == 200
    assert response.data["assessments"] == []


# ---------------------------------------------------------------------------
# 3. Most recent assessment first
# ---------------------------------------------------------------------------
def test_most_recent_assessment_appears_first(worker_api, patient):
    _create_assessment(worker_api, patient.id, symptoms=["cough"], encounter_date="2026-09-01")
    _create_assessment(worker_api, patient.id, symptoms=["fever"], encounter_date="2026-09-10")
    _create_assessment(worker_api, patient.id, symptoms=["headache"], encounter_date="2026-09-05")

    response = worker_api.get(_patient_url(patient.id))
    dates = [a["encounter_date"] for a in response.data["assessments"]]

    assert dates == sorted(dates, reverse=True)
    assert response.data["assessments"][0]["symptoms"] == ["fever"]


# ---------------------------------------------------------------------------
# 5, 6. Cross-patient and cross-village isolation
# ---------------------------------------------------------------------------
def test_patient_a_history_never_appears_under_patient_b(worker_api, patient, village):
    patient_b = Patient.objects.create(
        patient_code="KVL-P-B", display_name="Patient B", age_years=22, village=village
    )
    _create_assessment(worker_api, patient.id, symptoms=["fever"])

    response = worker_api.get(_patient_url(patient_b.id))

    assert response.data["assessments"] == []


def test_cross_village_worker_cannot_read_patient_history(worker_b, patient, worker_api):
    _create_assessment(worker_api, patient.id, symptoms=["fever"])

    response = api_for(worker_b).get(_patient_url(patient.id))

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 7-9. Sugar can be created, persists, and is returned
# ---------------------------------------------------------------------------
def test_assessment_can_be_created_with_sugar(worker_api, patient):
    response = _create_assessment(
        worker_api, patient.id, sugar_mg_dl=104, blood_sugar_measurement_type="fasting"
    )

    assessment_id = response.data["assessment"]["id"]
    stored = PatientAssessment.objects.get(id=assessment_id)
    assert stored.sugar_mg_dl == 104

    detail = worker_api.get(_patient_url(patient.id))
    assert detail.data["assessments"][0]["sugar_mg_dl"] == 104


# ---------------------------------------------------------------------------
# 10. Sugar appears in the history listing specifically
# ---------------------------------------------------------------------------
def test_sugar_appears_in_previous_assessments_history(worker_api, patient):
    _create_assessment(
        worker_api,
        patient.id,
        sugar_mg_dl=90,
        blood_sugar_measurement_type="fasting",
        encounter_date="2026-09-01",
    )
    _create_assessment(
        worker_api,
        patient.id,
        sugar_mg_dl=130,
        blood_sugar_measurement_type="random",
        encounter_date="2026-09-10",
    )

    history = worker_api.get(_patient_url(patient.id)).data["assessments"]

    assert history[0]["sugar_mg_dl"] == 130
    assert history[1]["sugar_mg_dl"] == 90


# ---------------------------------------------------------------------------
# 11, 12. Sugar is optional; omitted sugar is null, never zero
# ---------------------------------------------------------------------------
def test_sugar_can_be_omitted_and_is_stored_as_null_not_zero(worker_api, patient):
    response = _create_assessment(worker_api, patient.id)

    assessment_id = response.data["assessment"]["id"]
    stored = PatientAssessment.objects.get(id=assessment_id)
    assert stored.sugar_mg_dl is None

    detail = worker_api.get(_patient_url(patient.id))
    assert detail.data["assessments"][0]["sugar_mg_dl"] is None


# ---------------------------------------------------------------------------
# 13. Invalid sugar is rejected server-side
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sugar", [-5, 0, 5, 50000])
def test_invalid_sugar_is_rejected(worker_api, patient, sugar):
    response = worker_api.post(
        ASSESSMENTS_URL,
        {"patient": patient.id, "symptoms": ["fever"], "duration_days": 1, "sugar_mg_dl": sugar},
        format="json",
    )
    assert response.status_code == 400
    assert "sugar_mg_dl" in response.data["detail"]


# ---------------------------------------------------------------------------
# 14, 15. Old assessments without sugar remain valid; creation still works
# ---------------------------------------------------------------------------
def test_pre_existing_assessment_without_sugar_serializes_safely(worker_api, patient, village):
    """Simulates an assessment recorded before this field existed."""

    old = PatientAssessment.objects.create(
        patient=patient,
        village=village,
        symptoms=["fever"],
        duration_days=2,
        encounter_date="2026-01-01",
        is_draft=False,
    )
    assert old.sugar_mg_dl is None

    response = worker_api.get(_patient_url(patient.id))
    assert response.status_code == 200
    row = next(a for a in response.data["assessments"] if a["id"] == old.id)
    assert row["sugar_mg_dl"] is None


def test_assessment_creation_without_sugar_still_works(worker_api, patient):
    response = worker_api.post(
        ASSESSMENTS_URL,
        {"patient": patient.id, "symptoms": ["cough"], "duration_days": 1},
        format="json",
    )
    assert response.status_code == 201


# ---------------------------------------------------------------------------
# 16, 17. GramSentinel boundary — sugar and individual history never leak
# ---------------------------------------------------------------------------
def test_sugar_and_history_never_reach_community_or_alert_endpoints(worker, officer, patient):
    # `worker_api`/`officer_api` share one underlying `APIClient` fixture, so
    # requesting both in one test silently re-authenticates the same client
    # out from under the first — independent clients avoid that entirely.
    worker_client = api_for(worker)
    officer_client = api_for(officer)

    _create_assessment(
        worker_client,
        patient.id,
        symptoms=["fever"],
        sugar_mg_dl=277,
        blood_sugar_measurement_type="fasting",
        encounter_date="2026-09-10",
    )

    for url, client in [
        ("/api/local-signals/", worker_client),
        ("/api/officer/dashboard/", officer_client),
        ("/api/officer/community-data/", officer_client),
        ("/api/alerts/", officer_client),
    ]:
        response = client.get(url)
        body = json.dumps(response.data, default=str)
        assert "277" not in body, f"sugar value leaked via {url}"
        assert patient.patient_code not in body, f"patient identifier leaked via {url}"


# ===========================================================================
# Blood sugar measurement type (fasting / random / 2-hour post-meal)
# ===========================================================================

# ---------------------------------------------------------------------------
# 1-3. Sugar + each measurement type saves correctly
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value,measurement_type",
    [(120, "fasting"), (145, "random"), (180, "2_hour_post_meal")],
)
def test_sugar_with_each_measurement_type_saves_correctly(
    worker_api, patient, value, measurement_type
):
    response = _create_assessment(
        worker_api, patient.id, sugar_mg_dl=value, blood_sugar_measurement_type=measurement_type
    )

    stored = PatientAssessment.objects.get(id=response.data["assessment"]["id"])
    assert stored.sugar_mg_dl == value
    assert stored.blood_sugar_measurement_type == measurement_type

    history = worker_api.get(_patient_url(patient.id)).data["assessments"][0]
    assert history["sugar_mg_dl"] == value
    assert history["blood_sugar_measurement_type"] == measurement_type


# ---------------------------------------------------------------------------
# 4, 8. Sugar omitted -> measurement type stays blank, sugar stays null
# ---------------------------------------------------------------------------
def test_sugar_omitted_measurement_type_remains_blank(worker_api, patient):
    response = _create_assessment(worker_api, patient.id)

    stored = PatientAssessment.objects.get(id=response.data["assessment"]["id"])
    assert stored.sugar_mg_dl is None
    assert stored.blood_sugar_measurement_type == ""

    history = worker_api.get(_patient_url(patient.id)).data["assessments"][0]
    assert history["sugar_mg_dl"] is None
    assert history["blood_sugar_measurement_type"] == ""


# ---------------------------------------------------------------------------
# 5. Sugar provided without measurement type is rejected explicitly
# ---------------------------------------------------------------------------
def test_sugar_without_measurement_type_is_rejected(worker_api, patient):
    response = worker_api.post(
        ASSESSMENTS_URL,
        {"patient": patient.id, "symptoms": ["fever"], "duration_days": 1, "sugar_mg_dl": 100},
        format="json",
    )
    assert response.status_code == 400
    assert "blood_sugar_measurement_type" in response.data["detail"]


def test_measurement_type_without_sugar_is_rejected(worker_api, patient):
    response = worker_api.post(
        ASSESSMENTS_URL,
        {
            "patient": patient.id,
            "symptoms": ["fever"],
            "duration_days": 1,
            "blood_sugar_measurement_type": "fasting",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "sugar_mg_dl" in response.data["detail"]


# ---------------------------------------------------------------------------
# 6. Invalid measurement type is rejected
# ---------------------------------------------------------------------------
def test_invalid_measurement_type_is_rejected(worker_api, patient):
    response = worker_api.post(
        ASSESSMENTS_URL,
        {
            "patient": patient.id,
            "symptoms": ["fever"],
            "duration_days": 1,
            "sugar_mg_dl": 100,
            "blood_sugar_measurement_type": "before_breakfast",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "blood_sugar_measurement_type" in response.data["detail"]


# ---------------------------------------------------------------------------
# 7. Old assessment with sugar but no measurement type serializes safely
# ---------------------------------------------------------------------------
def test_old_assessment_with_sugar_but_no_measurement_type_serializes_safely(
    worker_api, patient, village
):
    """Simulates an assessment recorded after Sugar existed but before this
    measurement-type field did — sugar_mg_dl is set, the new field defaults
    to blank. The frontend, not this API, is responsible for turning that
    blank into "Not recorded"; this test only proves the API never guesses
    a value for it."""

    old = PatientAssessment.objects.create(
        patient=patient,
        village=village,
        symptoms=["fever"],
        duration_days=2,
        encounter_date="2026-01-01",
        is_draft=False,
        sugar_mg_dl=110,
    )
    assert old.blood_sugar_measurement_type == ""

    response = worker_api.get(_patient_url(patient.id))
    row = next(a for a in response.data["assessments"] if a["id"] == old.id)
    assert row["sugar_mg_dl"] == 110
    assert row["blood_sugar_measurement_type"] == ""


# ---------------------------------------------------------------------------
# 9. Sugar and measurement type are still excluded from the orchestrator
# ---------------------------------------------------------------------------
def test_sugar_and_measurement_type_excluded_from_orchestrator_payload(worker_api, patient):
    captured: dict = {}
    original_run = RuralCareOrchestrator.run

    def spy_run(self, payload):
        captured.update(payload)
        return original_run(self, payload)

    with patch("assessments.views.RuralCareOrchestrator.run", spy_run):
        _create_assessment(
            worker_api, patient.id, sugar_mg_dl=150, blood_sugar_measurement_type="fasting"
        )

    assert captured, "the orchestrator was never called"
    assert "sugar_mg_dl" not in captured
    assert "blood_sugar_measurement_type" not in captured


# ---------------------------------------------------------------------------
# 10-14. Measurement type, like sugar, never reaches community/alert surfaces
# ---------------------------------------------------------------------------
def test_measurement_type_never_reaches_community_or_alert_endpoints(worker, officer, patient):
    worker_client = api_for(worker)
    officer_client = api_for(officer)

    _create_assessment(
        worker_client,
        patient.id,
        symptoms=["fever"],
        sugar_mg_dl=199,
        blood_sugar_measurement_type="2_hour_post_meal",
        encounter_date="2026-09-11",
    )

    for url, client in [
        ("/api/local-signals/", worker_client),
        ("/api/officer/dashboard/", officer_client),
        ("/api/officer/community-data/", officer_client),
        ("/api/alerts/", officer_client),
    ]:
        response = client.get(url)
        body = json.dumps(response.data, default=str)
        assert "199" not in body, f"sugar value leaked via {url}"
        assert "2_hour_post_meal" not in body, f"measurement type leaked via {url}"
        assert patient.patient_code not in body, f"patient identifier leaked via {url}"


# ---------------------------------------------------------------------------
# 15. Village-scope security remains intact with the new field present
# ---------------------------------------------------------------------------
def test_cross_village_worker_cannot_read_sugar_or_measurement_type(worker_b, patient, worker_api):
    _create_assessment(
        worker_api, patient.id, sugar_mg_dl=140, blood_sugar_measurement_type="random"
    )

    response = api_for(worker_b).get(_patient_url(patient.id))

    assert response.status_code == 404
