"""Village-level data isolation across the three demonstration areas.

The rule under test: a user with a village assigned sees only that village; a
user with no village assigned (the original district officer) still sees
everything. Both halves matter — the second is what keeps the pre-existing
`officer` account working.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from alerts.services import run_community_pipeline
from community.models import CommunityReport, CommunityReportEntry
from core.constants import DataQuality, SignalCategory, SourceKind
from core.models import Village
from community.models import DataSource
from integrations.ingestion import ingest_batch
from patients.models import Patient

User = get_user_model()
pytestmark = pytest.mark.django_db

WEEK = "2026-W32"


@pytest.fixture
def three_villages(db):
    return {
        code: Village.objects.create(
            code=code, name=name, cluster=cluster, district="Thiruvannamalai"
        )
        for code, name, cluster in (
            ("KVL", "Kovilur", "Village Cluster A"),
            ("ARY", "Ariyanur", "Village Cluster A"),
            ("MLR", "Melur", "Village Cluster B"),
        )
    }


@pytest.fixture
def village_users(three_villages):
    users = {}
    for code in three_villages:
        users[f"worker_{code}"] = User.objects.create_user(
            username=f"worker.{code.lower()}",
            password="demo1234",
            role=User.Role.CHW_PHC_WORKER,
            village=three_villages[code],
        )
        users[f"officer_{code}"] = User.objects.create_user(
            username=f"officer.{code.lower()}",
            password="demo1234",
            role=User.Role.HEALTH_OFFICER,
            village=three_villages[code],
            district="Thiruvannamalai",
        )
    # The original district officer: no village, therefore district-wide.
    users["district_officer"] = User.objects.create_user(
        username="officer",
        password="demo1234",
        role=User.Role.HEALTH_OFFICER,
        district="Thiruvannamalai",
    )
    return users


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def seed_alert_for(village) -> object:
    """Give one village a corroborated fever cluster."""

    kinds = {
        SourceKind.CHW: (14, 5, SignalCategory.FEVER),
        SourceKind.PHC: (31, 19, SignalCategory.FEVER),
        SourceKind.PHARMACY: (310, 200, SignalCategory.FEVER),
        SourceKind.SCHOOL: (14.0, 6.0, SignalCategory.FEVER),
    }
    records = []
    for kind, (value, baseline, category) in kinds.items():
        source = DataSource.objects.create(
            code=f"{kind}-{village.code}",
            name=f"{kind} {village.code}",
            kind=kind,
            village=village,
        )
        records.append(
            {
                "source_code": source.code,
                "category": category,
                "week_label": WEEK,
                "value": value,
                "baseline": baseline,
                "is_reported": True,
                "data_quality": DataQuality.GOOD,
            }
        )
    ingest_batch(records, week_label=WEEK)
    return run_community_pipeline(village, WEEK, SignalCategory.FEVER)["alert"]


def make_report(village, worker, category="SKIN", description="Observed locally."):
    report = CommunityReport.objects.create(
        village=village,
        worker=worker,
        week_label=WEEK,
        period_start="2026-08-03",
        period_end="2026-08-09",
    )
    CommunityReportEntry.objects.create(
        report=report, category=category, case_count=5, description=description
    )
    return report


# ---------------------------------------------------------------------------
# Officers
# ---------------------------------------------------------------------------
def test_officer_sees_only_their_own_village_alerts(three_villages, village_users):
    alert_a = seed_alert_for(three_villages["KVL"])
    alert_c = seed_alert_for(three_villages["MLR"])

    response = client_for(village_users["officer_KVL"]).get("/api/alerts/")
    ids = [a["id"] for a in response.data]

    assert alert_a.id in ids
    assert alert_c.id not in ids


def test_officer_cannot_open_another_villages_alert_by_id(
    three_villages, village_users
):
    other_alert = seed_alert_for(three_villages["MLR"])
    api = client_for(village_users["officer_KVL"])

    assert api.get(f"/api/alerts/{other_alert.id}/").status_code == 404
    assert api.get(f"/api/alerts/{other_alert.id}/evidence/").status_code == 404
    assert (
        api.patch(
            f"/api/alerts/{other_alert.id}/status/",
            {"status": "CLOSED"},
            format="json",
        ).status_code
        == 404
    )
    assert (
        api.post(
            f"/api/alerts/{other_alert.id}/feedback/",
            {"outcome": "VALID_SIGNAL"},
            format="json",
        ).status_code
        == 404
    )


def test_officer_dashboard_counts_only_their_village(three_villages, village_users):
    seed_alert_for(three_villages["KVL"])
    seed_alert_for(three_villages["MLR"])

    scoped = client_for(village_users["officer_KVL"]).get("/api/officer/dashboard/")
    assert scoped.data["summary"]["active_alerts"] == 1
    assert scoped.data["scope"]["village_code"] == "KVL"
    assert scoped.data["scope"]["is_district_wide"] is False


def test_district_officer_without_a_village_still_sees_everything(
    three_villages, village_users
):
    """The pre-existing `officer` account must keep working unchanged."""

    seed_alert_for(three_villages["KVL"])
    seed_alert_for(three_villages["MLR"])

    response = client_for(village_users["district_officer"]).get(
        "/api/officer/dashboard/"
    )
    assert response.data["summary"]["active_alerts"] == 2
    assert response.data["scope"]["is_district_wide"] is True


# ---------------------------------------------------------------------------
# Community reports reach the right officer
# ---------------------------------------------------------------------------
def test_report_reaches_the_officer_for_that_village(three_villages, village_users):
    make_report(
        three_villages["ARY"],
        village_users["worker_ARY"],
        category="SKIN",
        description="Unusual skin infections — 6 reported cases.",
    )

    officer_b = client_for(village_users["officer_ARY"]).get(
        "/api/officer/community-reports/"
    )
    assert len(officer_b.data["reports"]) == 1
    entry = officer_b.data["reports"][0]["entries"][0]
    assert entry["label"] == "Skin conditions / infections"
    assert "Unusual skin infections" in entry["description"]


def test_report_is_not_visible_to_another_villages_officer(
    three_villages, village_users
):
    make_report(three_villages["ARY"], village_users["worker_ARY"])

    officer_a = client_for(village_users["officer_KVL"]).get(
        "/api/officer/community-reports/"
    )
    assert officer_a.data["reports"] == []


def test_new_report_indicator_then_clears_once_reviewed(
    three_villages, village_users
):
    make_report(three_villages["KVL"], village_users["worker_KVL"])
    api = client_for(village_users["officer_KVL"])

    before = api.get("/api/officer/dashboard/")
    assert before.data["new_reports"] == 1

    listing = api.get("/api/officer/community-reports/")
    assert listing.data["reports"][0]["acknowledged"] is False

    after = api.get("/api/officer/dashboard/")
    assert after.data["new_reports"] == 0


def test_district_officer_sees_reports_from_every_village(
    three_villages, village_users
):
    make_report(three_villages["KVL"], village_users["worker_KVL"])
    make_report(three_villages["ARY"], village_users["worker_ARY"])
    make_report(three_villages["MLR"], village_users["worker_MLR"])

    response = client_for(village_users["district_officer"]).get(
        "/api/officer/community-reports/"
    )
    assert len(response.data["reports"]) == 3


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------
def test_worker_sees_only_their_own_village_patients(three_villages, village_users):
    Patient.objects.create(
        patient_code="KVL-P-001", age_years=30, village=three_villages["KVL"]
    )
    Patient.objects.create(
        patient_code="ARY-P-001", age_years=30, village=three_villages["ARY"]
    )

    response = client_for(village_users["worker_KVL"]).get("/api/patients/")
    codes = [p["patient_code"] for p in response.data]

    assert codes == ["KVL-P-001"]


def test_worker_cannot_register_a_patient_in_another_village(
    three_villages, village_users
):
    response = client_for(village_users["worker_KVL"]).post(
        "/api/patients/",
        {
            "display_name": "Test",
            "age_years": 30,
            "village": three_villages["ARY"].id,
        },
        format="json",
    )
    assert response.status_code == 403


def test_worker_local_signals_are_their_own_village(three_villages, village_users):
    seed_alert_for(three_villages["ARY"])

    response = client_for(village_users["worker_KVL"]).get("/api/local-signals/")
    assert response.data["village"]["code"] == "KVL"
    assert response.data["signals"] == []


def test_each_village_worker_can_log_in_and_reach_their_dashboard(
    three_villages, village_users
):
    for code in three_villages:
        api = APIClient()
        login = api.post(
            "/api/auth/login/",
            {"username": f"worker.{code.lower()}", "password": "demo1234"},
            format="json",
        )
        assert login.status_code == 200
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        dashboard = api.get("/api/worker/dashboard/")
        assert dashboard.status_code == 200
        assert dashboard.data["village"]["code"] == code


def test_each_village_officer_can_log_in_and_reach_their_dashboard(
    three_villages, village_users
):
    for code in three_villages:
        api = APIClient()
        login = api.post(
            "/api/auth/login/",
            {"username": f"officer.{code.lower()}", "password": "demo1234"},
            format="json",
        )
        assert login.status_code == 200
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        dashboard = api.get("/api/officer/dashboard/")
        assert dashboard.status_code == 200
        assert dashboard.data["scope"]["village_code"] == code


# ---------------------------------------------------------------------------
# Patient registration from inside the assessment flow
# ---------------------------------------------------------------------------
def test_worker_can_register_a_patient_without_supplying_a_code(
    three_villages, village_users
):
    response = client_for(village_users["worker_KVL"]).post(
        "/api/patients/",
        {"display_name": "New Patient", "age_years": 28, "sex": "F"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["patient_code"].startswith("KVL-P-")
    assert response.data["village_code"] == "KVL"


def test_generated_patient_codes_do_not_collide(three_villages, village_users):
    api = client_for(village_users["worker_KVL"])
    codes = set()
    for index in range(3):
        response = api.post(
            "/api/patients/",
            {"display_name": f"Patient {index}", "age_years": 20 + index},
            format="json",
        )
        codes.add(response.data["patient_code"])
    assert len(codes) == 3


def test_registering_a_patient_then_assessing_them_works(
    three_villages, village_users
):
    """The new-patient path must flow straight into an assessment."""

    api = client_for(village_users["worker_KVL"])
    created = api.post(
        "/api/patients/",
        {"display_name": "Walk-in", "age_years": 34},
        format="json",
    )
    patient_id = created.data["id"]

    preview = api.post(
        "/api/assessments/preview/",
        {
            "patient": patient_id,
            "symptoms": ["fever", "headache"],
            "duration_days": 3,
        },
        format="json",
    )
    assert preview.status_code == 200
    assert preview.data["support"]["triage_level"] == "CONCERNING"

    submitted = api.post(
        "/api/assessments/",
        {
            "patient": patient_id,
            "symptoms": ["fever", "headache"],
            "duration_days": 3,
        },
        format="json",
    )
    assert submitted.status_code == 201
