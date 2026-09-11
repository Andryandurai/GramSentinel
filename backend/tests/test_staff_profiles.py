"""Staff profiles: self-service update, photograph validation and visibility.

Visibility is the part that matters most: a profile is professional
information, and the village boundary that governs everything else in this
platform governs it too.
"""

from __future__ import annotations

import base64

import pytest
from django.contrib.auth import get_user_model

from users.photos import PhotoError, validate_photo

User = get_user_model()
pytestmark = pytest.mark.django_db

PROFILE = "/api/auth/profile/"
DIRECTORY = "/api/auth/staff-profiles/"

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"synthetic-test-image-payload"
JPEG_BYTES = b"\xff\xd8\xff" + b"synthetic-test-image-payload"


def data_uri(raw: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


@pytest.fixture
def officer_a(db, village):
    return User.objects.create_user(
        username="officer.a",
        password="demo1234",
        role=User.Role.HEALTH_OFFICER,
        full_name="Dr. A. Officer",
        village=village,
    )


@pytest.fixture
def officer_b(db, other_village):
    return User.objects.create_user(
        username="officer.b",
        password="demo1234",
        role=User.Role.HEALTH_OFFICER,
        full_name="Dr. B. Officer",
        village=other_village,
    )


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="admin", password="demo1234", role=User.Role.ADMIN
    )


# ---------------------------------------------------------------------------
# Photograph validation — pure
# ---------------------------------------------------------------------------
def test_a_real_png_is_accepted():
    assert validate_photo(data_uri(PNG_BYTES)).startswith("data:image/png;base64,")


def test_a_jpeg_is_accepted_however_the_browser_spells_it():
    assert validate_photo(data_uri(JPEG_BYTES, "image/jpg")).startswith(
        "data:image/jpeg;base64,"
    )


def test_an_empty_value_clears_the_photograph():
    assert validate_photo("") == ""
    assert validate_photo(None) == ""


@pytest.mark.parametrize(
    "value",
    [
        "not-a-data-uri",
        "data:text/html;base64,YWJj",
        "data:application/pdf;base64,YWJj",
        "data:image/png;base64,!!!!",
    ],
)
def test_anything_that_is_not_an_accepted_image_is_refused(value):
    with pytest.raises(PhotoError):
        validate_photo(value)


def test_a_file_that_only_claims_to_be_a_png_is_refused():
    with pytest.raises(PhotoError):
        validate_photo(data_uri(b"this is really a text file"))


def test_an_oversized_image_is_refused():
    with pytest.raises(PhotoError) as excinfo:
        validate_photo(data_uri(PNG_BYTES + b"x" * 2_000_000))

    assert "too large" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Own profile
# ---------------------------------------------------------------------------
def test_a_worker_can_read_their_own_profile(worker_api, worker):
    payload = worker_api.get(PROFILE).json()

    assert payload["profile"]["username"] == worker.username
    assert payload["profile"]["role"] == User.Role.CHW_PHC_WORKER
    assert payload["profile"]["village_name"] == "Kovilur"
    assert payload["photo_limits"]["accepted_types"]


def test_a_worker_can_update_their_own_profile(worker_api, worker):
    response = worker_api.patch(
        PROFILE,
        {
            "full_name": "A. Meena",
            "phone_number": "+91 99999 10001",
            "staff_id": "CHW-KVL-014",
            "qualification": "ANM",
            "experience_years": 7,
        },
        format="json",
    )

    assert response.status_code == 200
    worker.refresh_from_db()
    assert worker.qualification == "ANM"
    assert worker.experience_years == 7
    assert worker.profile_updated_at is not None


def test_an_officer_can_update_their_own_profile(officer_api, officer):
    response = officer_api.patch(
        PROFILE, {"qualification": "MBBS, MPH", "experience_years": 12}, format="json"
    )

    assert response.status_code == 200
    officer.refresh_from_db()
    assert officer.qualification == "MBBS, MPH"


def test_uploading_and_replacing_a_photograph(worker_api, worker):
    worker_api.patch(PROFILE, {"photo": data_uri(PNG_BYTES)}, format="json")
    worker.refresh_from_db()
    first = worker.photo
    assert worker.has_photo

    worker_api.patch(PROFILE, {"photo": data_uri(JPEG_BYTES, "image/jpeg")}, format="json")
    worker.refresh_from_db()
    assert worker.photo != first
    assert worker.photo.startswith("data:image/jpeg;base64,")

    worker_api.patch(PROFILE, {"photo": ""}, format="json")
    worker.refresh_from_db()
    assert worker.has_photo is False


def test_an_invalid_photograph_is_refused_with_a_readable_message(worker_api, worker):
    response = worker_api.patch(
        PROFILE, {"photo": "data:text/plain;base64,YWJj"}, format="json"
    )

    assert response.status_code == 400
    assert "photo" in response.json()["detail"]
    worker.refresh_from_db()
    assert worker.has_photo is False


def test_the_profile_endpoint_cannot_change_credentials_or_assignment(
    worker_api, worker, other_village
):
    worker_api.patch(
        PROFILE,
        {
            "username": "someone.else",
            "role": User.Role.ADMIN,
            "village": other_village.id,
            "is_superuser": True,
            "password": "hacked",
        },
        format="json",
    )

    worker.refresh_from_db()
    assert worker.username == "worker"
    assert worker.role == User.Role.CHW_PHC_WORKER
    assert worker.village.code == "KVL"
    assert worker.is_superuser is False
    assert worker.check_password("demo1234")


def test_a_patient_has_no_staff_profile_endpoint(api, db, village):
    patient_user = User.objects.create_user(
        username="patient", password="demo1234", role=User.Role.PATIENT, village=village
    )
    api.force_authenticate(user=patient_user)

    assert api.get(PROFILE).status_code == 403
    assert api.get(DIRECTORY).status_code == 403


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------
def test_an_officer_sees_the_workers_of_their_own_village(api, officer_a, worker):
    api.force_authenticate(user=officer_a)
    payload = api.get(DIRECTORY).json()

    assert {row["username"] for row in payload["profiles"]} == {"worker", "officer.a"}
    assert payload["counts"]["workers"] == 1


def test_an_officer_cannot_see_another_villages_worker(
    api, officer_b, worker, officer_a
):
    api.force_authenticate(user=officer_b)
    payload = api.get(DIRECTORY).json()

    assert "worker" not in {row["username"] for row in payload["profiles"]}
    assert api.get(f"{DIRECTORY}{worker.id}/").status_code == 404


def test_an_officer_can_open_a_worker_profile_in_their_own_village(
    api, officer_a, worker
):
    worker.qualification = "ANM"
    worker.photo = validate_photo(data_uri(PNG_BYTES))
    worker.save()

    api.force_authenticate(user=officer_a)
    payload = api.get(f"{DIRECTORY}{worker.id}/").json()

    assert payload["profile"]["qualification"] == "ANM"
    assert payload["profile"]["has_photo"] is True
    assert payload["profile"]["photo_url"].startswith("data:image/png;base64,")


def test_a_district_wide_officer_keeps_seeing_the_whole_district(
    api, officer, worker, officer_a, officer_b
):
    """The unassigned officer account supervises the district, as it always has."""

    api.force_authenticate(user=officer)
    payload = api.get(DIRECTORY).json()

    assert {"worker", "officer.a", "officer.b"} <= {
        row["username"] for row in payload["profiles"]
    }


def test_an_administrator_sees_every_village_and_which_is_which(
    api, admin_user, worker, officer_a, officer_b
):
    api.force_authenticate(user=admin_user)
    payload = api.get(DIRECTORY).json()

    labels = {group["village_label"] for group in payload["groups"]}
    assert {"Village A", "Village C"} <= labels
    assert api.get(f"{DIRECTORY}{worker.id}/").status_code == 200


def test_an_administrator_can_filter_the_directory_by_village(
    api, admin_user, worker, officer_b, other_village
):
    api.force_authenticate(user=admin_user)
    payload = api.get(f"{DIRECTORY}?village={other_village.code}").json()

    assert {row["username"] for row in payload["profiles"]} == {"officer.b"}


def test_an_unknown_village_filter_is_handled_rather_than_failing(api, admin_user):
    api.force_authenticate(user=admin_user)
    response = api.get(f"{DIRECTORY}?village=NOPE")

    assert response.status_code == 200
    assert response.json()["scope"]["notice"]


def test_a_worker_is_not_given_the_staff_directory(worker_api):
    assert worker_api.get(DIRECTORY).status_code == 403


def test_admin_overview_carries_profile_details_per_village(
    api, admin_user, worker, officer_a
):
    worker.qualification = "ANM"
    worker.phone_number = "+91 99999 10001"
    worker.save()

    api.force_authenticate(user=admin_user)
    team = api.get("/api/admin/overview/").json()["team"]
    village_a = [row for row in team if row["label"] == "Village A"][0]

    profile = village_a["workers"][0]
    assert profile["name"] == worker.display_name  # preserved field
    assert profile["qualification"] == "ANM"
    assert profile["phone_number"] == "+91 99999 10001"
    assert profile["village_label"] == "Village A"


def test_a_profile_never_carries_account_internals(api, officer_a, worker):
    api.force_authenticate(user=officer_a)
    profile = api.get(f"{DIRECTORY}{worker.id}/").json()["profile"]

    for forbidden in ("password", "is_superuser", "is_staff", "last_login"):
        assert forbidden not in profile
