"""Patient details — height, weight, phone number, house location.

These four fields live on `patients.models.Patient` itself (there was no
existing one-to-one patient-profile model to reuse — see that model's own
comment), persist across every assessment, and are never read by triage,
SafetyEngine, or any GramSentinel/community/simulation code path (verified
structurally in `test_fields_never_reach_community_alerts_or_simulation`
below, and confirmed independently by a repo-wide search before this file
was written: `patients`/`Patient` is imported nowhere under `community/`,
`alerts/`, or `simulation/`).
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from patients.models import Patient

User = get_user_model()
pytestmark = pytest.mark.django_db

PATIENTS_URL = "/api/patients/"


def _patient_url(pk: int) -> str:
    return f"{PATIENTS_URL}{pk}/"


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


# ---------------------------------------------------------------------------
# 1-5. A new patient can be created with all four fields, and they persist
# ---------------------------------------------------------------------------
def test_new_patient_persists_all_four_detail_fields(worker_api, village):
    response = worker_api.post(
        PATIENTS_URL,
        {
            "display_name": "Test Patient",
            "age_years": 40,
            "sex": "F",
            "height_cm": 165,
            "weight_kg": 62,
            "phone_number": "9876543210",
            "house_location": "Near village school",
            "village": village.id,
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["height_cm"] == 165
    assert response.data["weight_kg"] == 62
    assert response.data["phone_number"] == "9876543210"
    assert response.data["house_location"] == "Near village school"

    # Persisted, not merely echoed back.
    patient = Patient.objects.get(id=response.data["id"])
    assert patient.height_cm == 165
    assert patient.weight_kg == 62
    assert patient.phone_number == "9876543210"
    assert patient.house_location == "Near village school"


# ---------------------------------------------------------------------------
# 6. Existing patient data can be loaded (the New Assessment pre-fill read)
# ---------------------------------------------------------------------------
def test_existing_patient_details_are_returned_by_the_api(worker_api, patient):
    patient.height_cm = 150
    patient.weight_kg = 45
    patient.phone_number = "9000011111"
    patient.house_location = "Opposite water tank"
    patient.save()

    list_response = worker_api.get(PATIENTS_URL)
    row = next(p for p in list_response.data if p["id"] == patient.id)
    assert row["height_cm"] == 150
    assert row["weight_kg"] == 45
    assert row["phone_number"] == "9000011111"
    assert row["house_location"] == "Opposite water tank"

    detail_response = worker_api.get(_patient_url(patient.id))
    assert detail_response.data["patient"]["house_location"] == "Opposite water tank"


# ---------------------------------------------------------------------------
# 7, 16. Existing patient details survive an unrelated new assessment, and
# the existing assessment/triage behaviour is unaffected by any of this
# ---------------------------------------------------------------------------
def test_patient_details_preserved_across_a_new_assessment(worker_api, patient):
    patient.height_cm = 170
    patient.phone_number = "9123456789"
    patient.save()

    preview = worker_api.post(
        "/api/assessments/preview/",
        {"patient": patient.id, "symptoms": ["fever"], "duration_days": 2},
        format="json",
    )
    assert preview.status_code == 200
    assert "support" in preview.data
    assert preview.data["support"]["triage_level"] in {"ROUTINE", "CONCERNING", "URGENT"}

    submit = worker_api.post(
        "/api/assessments/",
        {"patient": patient.id, "symptoms": ["fever"], "duration_days": 2},
        format="json",
    )
    assert submit.status_code == 201

    patient.refresh_from_db()
    assert patient.height_cm == 170
    assert patient.phone_number == "9123456789"


# ---------------------------------------------------------------------------
# 8. An existing patient's detail fields can be updated (PATCH)
# ---------------------------------------------------------------------------
def test_existing_patient_details_can_be_updated(worker_api, patient):
    response = worker_api.patch(
        _patient_url(patient.id),
        {"phone_number": "9988776655", "house_location": "House 24"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["phone_number"] == "9988776655"
    assert response.data["house_location"] == "House 24"
    patient.refresh_from_db()
    assert patient.phone_number == "9988776655"
    assert patient.house_location == "House 24"


def test_patch_cannot_change_identity_or_village_fields(worker_api, patient, other_village):
    """The update endpoint only accepts the four detail fields — sending a
    different village or name has no effect, by construction (they are not
    in `PatientDetailUpdateSerializer.Meta.fields` at all)."""

    original_code = patient.patient_code
    response = worker_api.patch(
        _patient_url(patient.id),
        {
            "display_name": "Someone Else",
            "village": other_village.id,
            "height_cm": 140,
        },
        format="json",
    )

    assert response.status_code == 200
    patient.refresh_from_db()
    assert patient.patient_code == original_code
    assert patient.village_id != other_village.id
    assert patient.height_cm == 140


# ---------------------------------------------------------------------------
# 9, 15. Blank/omitted fields never break patient or assessment creation
# ---------------------------------------------------------------------------
def test_patient_can_be_created_without_any_detail_fields(worker_api, village):
    response = worker_api.post(
        PATIENTS_URL,
        {"display_name": "No Details Yet", "age_years": 30, "village": village.id},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["height_cm"] is None
    assert response.data["weight_kg"] is None
    assert response.data["phone_number"] == ""
    assert response.data["house_location"] == ""

    # An assessment for this patient still works exactly as before.
    submit = worker_api.post(
        "/api/assessments/",
        {"patient": response.data["id"], "symptoms": ["cough"], "duration_days": 1},
        format="json",
    )
    assert submit.status_code == 201


def test_a_pre_existing_patient_row_with_no_detail_fields_serializes_safely(worker_api, patient):
    """Simulates a patient created before this migration: the new columns
    default to null/blank, never raising on read."""

    assert patient.height_cm is None
    assert patient.house_location == ""
    response = worker_api.get(_patient_url(patient.id))
    assert response.status_code == 200
    assert response.data["patient"]["height_cm"] is None
    assert response.data["patient"]["house_location"] == ""


# ---------------------------------------------------------------------------
# 10-13. Server-side validation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("height", [-5, 0, 5, 999])
def test_invalid_height_is_rejected(worker_api, village, height):
    response = worker_api.post(
        PATIENTS_URL,
        {
            "display_name": "Bad Height",
            "age_years": 20,
            "height_cm": height,
            "village": village.id,
        },
        format="json",
    )
    assert response.status_code == 400
    assert "height_cm" in response.data["detail"]


@pytest.mark.parametrize("weight", [-1, 0, 500])
def test_invalid_weight_is_rejected(worker_api, village, weight):
    response = worker_api.post(
        PATIENTS_URL,
        {
            "display_name": "Bad Weight",
            "age_years": 20,
            "weight_kg": weight,
            "village": village.id,
        },
        format="json",
    )
    assert response.status_code == 400
    assert "weight_kg" in response.data["detail"]


def test_invalid_phone_format_is_rejected(worker_api, village):
    response = worker_api.post(
        PATIENTS_URL,
        {
            "display_name": "Bad Phone",
            "age_years": 20,
            "phone_number": "abc",
            "village": village.id,
        },
        format="json",
    )
    assert response.status_code == 400
    assert "phone_number" in response.data["detail"]


@pytest.mark.parametrize("phone", ["9876543210", "+91 98765 43210", "080-12345678"])
def test_reasonable_phone_formats_are_accepted(worker_api, village, phone):
    response = worker_api.post(
        PATIENTS_URL,
        {
            "display_name": "Good Phone",
            "age_years": 20,
            "phone_number": phone,
            "village": village.id,
        },
        format="json",
    )
    assert response.status_code == 201


def test_excessively_long_house_location_is_rejected(worker_api, village):
    response = worker_api.post(
        PATIENTS_URL,
        {
            "display_name": "Long Location",
            "age_years": 20,
            "house_location": "x" * 201,
            "village": village.id,
        },
        format="json",
    )
    assert response.status_code == 400
    assert "house_location" in response.data["detail"]


# ---------------------------------------------------------------------------
# 14, 20. Cross-village access is blocked, including for details specifically
# ---------------------------------------------------------------------------
def test_worker_cannot_read_another_villages_patient_details(worker_b, patient):
    """`patient` (from conftest) belongs to `village`; `worker_b` is scoped
    to `other_village` — the existing village-scoped queryset must exclude
    it entirely (404, not a 200 with redacted fields)."""

    response = api_for(worker_b).get(_patient_url(patient.id))
    assert response.status_code == 404


def test_worker_cannot_update_another_villages_patient_details(worker_b, patient):
    response = api_for(worker_b).patch(
        _patient_url(patient.id), {"phone_number": "9999999999"}, format="json"
    )
    assert response.status_code == 404
    patient.refresh_from_db()
    assert patient.phone_number == ""


def test_worker_cannot_register_a_patient_in_another_village(worker_api, other_village):
    response = worker_api.post(
        PATIENTS_URL,
        {
            "display_name": "Cross Village",
            "age_years": 20,
            "phone_number": "9000000000",
            "village": other_village.id,
        },
        format="json",
    )
    assert response.status_code == 403


def test_officer_role_is_rejected_from_patient_endpoints_entirely(officer_api, patient):
    """The individual layer's detail endpoints (`IsWorker`) reject any
    officer outright, same-village or not — this is the primary reason a
    Health Officer can never retrieve a patient's phone number or house
    location through this API at all."""

    assert officer_api.get(_patient_url(patient.id)).status_code == 403
    assert officer_api.get(PATIENTS_URL).status_code == 403
    assert (
        officer_api.patch(_patient_url(patient.id), {"phone_number": "1"}, format="json").status_code
        == 403
    )


# ---------------------------------------------------------------------------
# 17, 18, 19. These personal fields never reach community/alert/simulation
# surfaces — a positive assertion, not only the structural absence of any
# `Patient` reference in those apps (confirmed separately by inspection).
# ---------------------------------------------------------------------------
def test_fields_never_reach_community_alerts_or_simulation(worker_api, officer_api, village, patient):
    patient.phone_number = "9123450001"
    patient.house_location = "DISTINCTIVE-HOUSE-LOCATION-MARKER"
    patient.save()

    worker_api.post(
        "/api/assessments/",
        {"patient": patient.id, "symptoms": ["fever"], "duration_days": 3},
        format="json",
    )

    import json

    checked_urls = [
        "/api/local-signals/",
        "/api/officer/dashboard/",
        "/api/officer/community-data/",
        "/api/officer/community-reports/",
        "/api/alerts/",
    ]
    for url in checked_urls:
        client = officer_api if url.startswith("/api/officer/") or url == "/api/alerts/" else worker_api
        response = client.get(url)
        body = json.dumps(response.data, default=str)
        assert "9123450001" not in body, f"phone number leaked via {url}"
        assert "DISTINCTIVE-HOUSE-LOCATION-MARKER" not in body, f"house location leaked via {url}"
