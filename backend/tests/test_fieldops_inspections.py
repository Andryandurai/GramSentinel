"""Field Operations — Inspection Checklist System."""

from __future__ import annotations

import base64

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from core.models import Village
from fieldops.models import Inspection, InspectionStatus

User = get_user_model()
pytestmark = pytest.mark.django_db

INSPECTIONS = "/api/officer/inspections/"
PDF_B64 = base64.b64encode(b"%PDF-1.4\ntest").decode()
JPG_B64 = base64.b64encode(b"\xff\xd8\xfftest").decode()


def api_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def village_b(db) -> Village:
    return Village.objects.create(code="ARY", name="Manikkampatti", cluster="Village Cluster B", district="Madurai")


@pytest.fixture
def officer_a(db, village):
    return User.objects.create_user(username="ins.officer.a", password="x", role=User.Role.HEALTH_OFFICER, village=village)


@pytest.fixture
def officer_b(db, village_b):
    return User.objects.create_user(username="ins.officer.b", password="x", role=User.Role.HEALTH_OFFICER, village=village_b)


def create_inspection(officer_api, village_id, inspection_type="DRINKING_WATER_SANITATION"):
    return officer_api.post(INSPECTIONS, {"village": village_id, "inspection_type": inspection_type}, format="json")


# 8. Health Officer can create inspection.
def test_officer_can_create_inspection(officer_a, village):
    response = create_inspection(api_for(officer_a), village.id)
    assert response.status_code == 201
    assert response.data["status"] == "DRAFT"
    assert len(response.data["responses"]) > 0


# 9. All four inspection types are available.
@pytest.mark.parametrize(
    "inspection_type",
    ["DRINKING_WATER_SANITATION", "SCHOOL_ANGANWADI", "PUBLIC_PLACE_HYGIENE", "WASTE_MANAGEMENT"],
)
def test_all_four_inspection_types_are_available(officer_a, village, inspection_type):
    response = create_inspection(api_for(officer_a), village.id, inspection_type)
    assert response.status_code == 201
    assert response.data["inspection_type"] == inspection_type
    assert all(r["item_text"] for r in response.data["responses"])


def _first_two_response_ids(inspection_data):
    return inspection_data["responses"][0]["id"], inspection_data["responses"][1]["id"]


# 10-12. Checklist supports Passed / Failed / Needs Action.
@pytest.mark.parametrize("value", ["PASSED", "FAILED", "NEEDS_ACTION"])
def test_checklist_item_supports_each_status(officer_a, village, value):
    officer_api = api_for(officer_a)
    inspection = create_inspection(officer_api, village.id).data
    officer_api.post(f"{INSPECTIONS}{inspection['id']}/start/")
    response_id = inspection["responses"][0]["id"]

    remarks = {"remarks": "needs a note"} if value != "PASSED" else {}
    response = officer_api.post(
        f"{INSPECTIONS}{inspection['id']}/responses/{response_id}/", {"status": value, **remarks}, format="json"
    )
    assert response.data["status"] == value


# 13. Remarks are stored.
def test_remarks_are_stored(officer_a, village):
    officer_api = api_for(officer_a)
    inspection = create_inspection(officer_api, village.id).data
    officer_api.post(f"{INSPECTIONS}{inspection['id']}/start/")
    response_id = inspection["responses"][0]["id"]
    response = officer_api.post(
        f"{INSPECTIONS}{inspection['id']}/responses/{response_id}/",
        {"status": "NEEDS_ACTION", "remarks": "Drainage near the inspected area requires cleaning."},
        format="json",
    )
    assert response.data["remarks"] == "Drainage near the inspected area requires cleaning."


def test_remark_required_for_failed_and_needs_action(officer_a, village):
    officer_api = api_for(officer_a)
    inspection = create_inspection(officer_api, village.id).data
    officer_api.post(f"{INSPECTIONS}{inspection['id']}/start/")
    response_id = inspection["responses"][0]["id"]
    response = officer_api.post(
        f"{INSPECTIONS}{inspection['id']}/responses/{response_id}/", {"status": "FAILED"}, format="json"
    )
    assert response.status_code == 400
    assert "remarks" in response.data["detail"]


# 14. Supporting document upload is secured.
def test_supporting_document_upload_is_authenticated_and_scoped(officer_a, officer_b, village):
    officer_api = api_for(officer_a)
    inspection_id = create_inspection(officer_api, village.id).data["id"]

    upload = officer_api.post(
        f"{INSPECTIONS}{inspection_id}/attachments/",
        {"file": f"data:application/pdf;base64,{PDF_B64}", "filename": "note.pdf"},
        format="json",
    )
    assert upload.status_code == 201
    attachment_id = upload.data["id"]

    download = api_for(officer_a).get(f"{INSPECTIONS}{inspection_id}/attachments/{attachment_id}/")
    assert download.status_code == 200

    denied = api_for(officer_b).get(f"{INSPECTIONS}{inspection_id}/attachments/{attachment_id}/")
    assert denied.status_code == 404


def test_attachment_rejects_unsupported_type(officer_a, village):
    officer_api = api_for(officer_a)
    inspection_id = create_inspection(officer_api, village.id).data["id"]
    docx_signature = base64.b64encode(b"PK\x03\x04 fake docx").decode()
    response = officer_api.post(
        f"{INSPECTIONS}{inspection_id}/attachments/",
        {"file": f"data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,{docx_signature}"},
        format="json",
    )
    assert response.status_code == 400


# 15. Unauthorized village access rejected.
def test_unauthorized_village_access_rejected(officer_a, officer_b, village):
    inspection_id = create_inspection(api_for(officer_a), village.id).data["id"]
    assert api_for(officer_b).get(f"{INSPECTIONS}{inspection_id}/").status_code == 404
    assert api_for(officer_b).get(INSPECTIONS).data == []


# 16. Completed inspection cannot be silently modified.
def test_completed_inspection_checklist_is_locked(officer_a, village):
    officer_api = api_for(officer_a)
    inspection = create_inspection(officer_api, village.id).data
    inspection_id = inspection["id"]
    officer_api.post(f"{INSPECTIONS}{inspection_id}/start/")
    response_id = inspection["responses"][0]["id"]
    officer_api.post(f"{INSPECTIONS}{inspection_id}/responses/{response_id}/", {"status": "PASSED"}, format="json")
    officer_api.post(f"{INSPECTIONS}{inspection_id}/complete/", {"summary_remarks": "done"}, format="json")

    locked = officer_api.post(
        f"{INSPECTIONS}{inspection_id}/responses/{response_id}/", {"status": "FAILED", "remarks": "trying to edit"}, format="json"
    )
    assert locked.status_code == 400

    inspection_obj = Inspection.objects.get(pk=inspection_id)
    assert inspection_obj.status == InspectionStatus.COMPLETED
    assert inspection_obj.responses.get(pk=response_id).status == "PASSED"


def test_inspection_summary_is_computed_from_stored_responses_not_client_input(officer_a, village):
    officer_api = api_for(officer_a)
    inspection = create_inspection(officer_api, village.id).data
    inspection_id = inspection["id"]
    officer_api.post(f"{INSPECTIONS}{inspection_id}/start/")
    ids = [r["id"] for r in inspection["responses"]]
    officer_api.post(f"{INSPECTIONS}{inspection_id}/responses/{ids[0]}/", {"status": "PASSED"}, format="json")
    officer_api.post(f"{INSPECTIONS}{inspection_id}/responses/{ids[1]}/", {"status": "FAILED", "remarks": "bad"}, format="json")

    detail = officer_api.get(f"{INSPECTIONS}{inspection_id}/").data
    assert detail["summary"]["passed"] == 1
    assert detail["summary"]["failed"] == 1
    assert detail["summary"]["total"] == len(inspection["responses"])
