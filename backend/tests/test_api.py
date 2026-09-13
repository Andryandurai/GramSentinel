"""API behaviour, role enforcement, and the end-to-end acceptance test.

The role tests matter because the spec is explicit that permission checks are
server-side: a worker token must not be able to reach officer data even if the
frontend would never send that request.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from alerts.models import Alert, Feedback, Investigation
from alerts.services import run_community_pipeline
from core.constants import DataQuality, SignalCategory, SourceKind
from integrations.ingestion import ingest_batch

pytestmark = pytest.mark.django_db

CORROBORATED = {
    SourceKind.CHW: (14, 5, SignalCategory.FEVER),
    SourceKind.PHC: (31, 19, SignalCategory.FEVER),
    SourceKind.PHARMACY: (310, 200, SignalCategory.FEVER),
    SourceKind.SCHOOL: (14.0, 6.0, SignalCategory.FEVER),
    SourceKind.WEATHER: (240, 110, SignalCategory.ENVIRONMENT),
    SourceKind.LAB: (1, 0, SignalCategory.LAB_CONFIRMATION),
}


def seed_alert(village, sources, week_label="2026-W32"):
    ingest_batch(
        [
            {
                "source_code": sources[kind].code,
                "category": category,
                "week_label": week_label,
                "value": value,
                "baseline": baseline,
                "is_reported": True,
                "data_quality": DataQuality.GOOD,
            }
            for kind, (value, baseline, category) in CORROBORATED.items()
        ],
        week_label=week_label,
    )
    return run_community_pipeline(village, week_label, SignalCategory.FEVER)["alert"]


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def test_login_returns_a_token_and_the_role(api, worker):
    response = api.post(
        "/api/auth/login/", {"username": "worker", "password": "demo1234"}, format="json"
    )
    assert response.status_code == 200
    assert response.data["access"]
    assert response.data["user"]["role"] == "CHW_PHC_WORKER"
    assert "disclaimer" in response.data


def test_login_with_a_bad_password_is_rejected(api, worker):
    response = api.post(
        "/api/auth/login/", {"username": "worker", "password": "wrong"}, format="json"
    )
    assert response.status_code == 401


def test_endpoints_require_authentication(api):
    for url in ("/api/worker/dashboard/", "/api/officer/dashboard/", "/api/alerts/"):
        assert api.get(url).status_code == 401


def test_health_endpoint_is_open(api):
    response = api.get("/api/health/")
    assert response.status_code == 200
    assert "Synthetic" in response.json()["data_notice"]


# ---------------------------------------------------------------------------
# Role enforcement — server-side, not cosmetic
# ---------------------------------------------------------------------------
def test_worker_token_cannot_reach_officer_endpoints(worker_api, village, sources):
    alert = seed_alert(village, sources)

    assert worker_api.get("/api/officer/dashboard/").status_code == 403
    assert worker_api.get("/api/alerts/").status_code == 403
    assert worker_api.get(f"/api/alerts/{alert.id}/evidence/").status_code == 403
    assert (
        worker_api.patch(
            f"/api/alerts/{alert.id}/status/", {"status": "CLOSED"}, format="json"
        ).status_code
        == 403
    )


def test_officer_token_cannot_reach_worker_endpoints(officer_api):
    assert officer_api.get("/api/worker/dashboard/").status_code == 403
    assert officer_api.get("/api/patients/").status_code == 403
    assert officer_api.post("/api/assessments/", {}, format="json").status_code == 403
    assert officer_api.get("/api/local-signals/").status_code == 403


def test_worker_only_sees_their_own_village(worker_api, village, other_village):
    from patients.models import Patient

    Patient.objects.create(
        patient_code="MLR-P-001", age_years=30, village=other_village
    )
    mine = Patient.objects.create(
        patient_code="KVL-P-002", age_years=30, village=village
    )

    response = worker_api.get("/api/patients/")
    codes = [p["patient_code"] for p in response.data]

    assert codes == [mine.patient_code]


# ---------------------------------------------------------------------------
# Worker flow
# ---------------------------------------------------------------------------
def test_assessment_preview_stores_nothing(worker_api, patient):
    from assessments.models import PatientAssessment

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
    assert PatientAssessment.objects.count() == 0


def test_assessment_rejects_an_empty_presentation(worker_api, patient):
    response = worker_api.post(
        "/api/assessments/preview/",
        {"patient": patient.id, "symptoms": [], "duration_days": 2},
        format="json",
    )
    assert response.status_code == 400


def test_assessment_rejects_an_impossible_vital(worker_api, patient):
    response = worker_api.post(
        "/api/assessments/preview/",
        {
            "patient": patient.id,
            "symptoms": ["fever"],
            "duration_days": 2,
            "temperature_c": 91.0,
        },
        format="json",
    )
    assert response.status_code == 400


def test_submitting_an_assessment_generates_an_anonymised_signal(worker_api, patient):
    response = worker_api.post(
        "/api/assessments/",
        {
            "patient": patient.id,
            "symptoms": ["fever", "headache"],
            "duration_days": 3,
            "temperature_c": 38.4,
        },
        format="json",
    )

    assert response.status_code == 201
    aggregation = response.data["aggregation"]
    assert aggregation["signals_written"]
    assert aggregation["signals_written"][0]["encounter_count"] == 1.0
    # The aggregation block must not leak the patient back out.
    assert patient.patient_code not in str(aggregation)


def test_red_flag_case_is_escalated_through_the_api(worker_api, infant):
    response = worker_api.post(
        "/api/assessments/preview/",
        {"patient": infant.id, "symptoms": ["fever"], "duration_days": 1},
        format="json",
    )
    support = response.data["support"]

    assert support["triage_level"] == "URGENT"
    assert support["escalation_forced"] is True
    assert any(f["code"] == "RF_YOUNG_INFANT_FEVER" for f in support["red_flags"])


def test_worker_dashboard_reports_today(worker_api, patient):
    worker_api.post(
        "/api/assessments/",
        {"patient": patient.id, "symptoms": ["fever"], "duration_days": 2},
        format="json",
    )
    response = worker_api.get("/api/worker/dashboard/")

    assert response.status_code == 200
    assert response.data["today"]["assessment_count"] == 1
    assert response.data["village"]["code"] == "KVL"


def test_community_report_triggers_the_pipeline(worker_api, village, sources):
    ingest_batch(
        [
            {
                "source_code": sources[kind].code,
                "category": category,
                "week_label": "2026-W32",
                "value": value,
                "baseline": baseline,
                "is_reported": True,
            }
            for kind, (value, baseline, category) in CORROBORATED.items()
            if kind != SourceKind.CHW
        ],
        week_label="2026-W32",
    )

    response = worker_api.post(
        "/api/community-reports/",
        {
            "village": village.id,
            "week_label": "2026-W32",
            "period_start": "2026-08-03",
            "period_end": "2026-08-09",
            "unusual_observation": True,
            "entries": [
                {"category": "FEVER", "case_count": 14},
                {"category": "RESPIRATORY", "case_count": 5},
                {"category": "DIARRHOEAL", "case_count": 3},
            ],
        },
        format="json",
    )

    assert response.status_code == 201
    fever = next(p for p in response.data["pipeline"] if p["category"] == "FEVER")
    assert fever["alert_raised"] is True
    assert fever["safety_verdict"] == "PASS"


# ---------------------------------------------------------------------------
# Expanded community report categories and described "Other" concerns
# ---------------------------------------------------------------------------
def test_report_categories_endpoint_lists_the_expanded_vocabulary(worker_api):
    response = worker_api.get("/api/report-categories/")
    values = {c["value"] for c in response.data["categories"]}

    assert response.status_code == 200
    # Original four preserved...
    assert {"FEVER", "RESPIRATORY", "DIARRHOEAL", "OTHER"} <= values
    # ...and the vocabulary extended.
    assert {"SKIN", "EYE", "INJURY", "MATERNAL", "MENTAL_HEALTH"} <= values
    # System categories are not worker-selectable.
    assert "ENVIRONMENT" not in values
    assert "LAB_CONFIRMATION" not in values
    assert "not confirmed diagnoses" in response.data["note"]


def test_report_accepts_an_expanded_category_with_description(worker_api, village):
    from community.models import CommunityReport

    response = worker_api.post(
        "/api/community-reports/",
        {
            "village": village.id,
            "week_label": "2026-W32",
            "period_start": "2026-08-03",
            "period_end": "2026-08-09",
            "entries": [
                {
                    "category": "SKIN",
                    "case_count": 6,
                    "description": "Itchy lesions across three households.",
                }
            ],
        },
        format="json",
    )

    assert response.status_code == 201
    report = CommunityReport.objects.get(village=village, week_label="2026-W32")
    entry = report.entries.get(category="SKIN")
    assert entry.case_count == 6
    assert "Itchy lesions" in entry.description


def test_other_category_requires_a_description(worker_api, village):
    response = worker_api.post(
        "/api/community-reports/",
        {
            "village": village.id,
            "week_label": "2026-W32",
            "period_start": "2026-08-03",
            "period_end": "2026-08-09",
            "entries": [{"category": "OTHER", "case_count": 4}],
        },
        format="json",
    )
    assert response.status_code == 400
    assert "describe" in str(response.data).lower()


def test_report_with_no_categories_is_rejected(worker_api, village):
    response = worker_api.post(
        "/api/community-reports/",
        {
            "village": village.id,
            "week_label": "2026-W32",
            "period_start": "2026-08-03",
            "period_end": "2026-08-09",
            "entries": [],
        },
        format="json",
    )
    assert response.status_code == 400


def test_legacy_columns_stay_in_sync_with_entries(worker_api, village):
    from community.models import CommunityReport

    worker_api.post(
        "/api/community-reports/",
        {
            "village": village.id,
            "week_label": "2026-W32",
            "period_start": "2026-08-03",
            "period_end": "2026-08-09",
            "entries": [
                {"category": "FEVER", "case_count": 11},
                {"category": "SKIN", "case_count": 2},
            ],
        },
        format="json",
    )

    report = CommunityReport.objects.get(village=village, week_label="2026-W32")
    assert report.fever_cases == 11  # legacy column still populated
    assert report.entries.filter(category="SKIN").exists()


def test_worker_cannot_report_for_another_village(worker_api, other_village):
    response = worker_api.post(
        "/api/community-reports/",
        {
            "village": other_village.id,
            "week_label": "2026-W32",
            "period_start": "2026-08-03",
            "period_end": "2026-08-09",
            "fever_cases": 40,
        },
        format="json",
    )
    assert response.status_code == 403


def test_local_signals_are_scoped_to_the_worker_area(worker_api, village, sources):
    seed_alert(village, sources)
    response = worker_api.get("/api/local-signals/")

    assert response.status_code == 200
    assert response.data["village"]["code"] == "KVL"
    assert "district-wide" in response.data["scope_note"].lower()


# ---------------------------------------------------------------------------
# Officer flow
# ---------------------------------------------------------------------------
def test_officer_dashboard_lists_the_alert(officer_api, village, sources):
    seed_alert(village, sources)
    response = officer_api.get("/api/officer/dashboard/")

    assert response.status_code == 200
    assert response.data["summary"]["active_alerts"] == 1
    assert response.data["summary"]["human_review_rate"] == 1.0
    assert response.data["alerts"][0]["severity"] == "HIGH"


def test_evidence_view_explains_why_the_alert_exists(officer_api, village, sources):
    alert = seed_alert(village, sources)
    response = officer_api.get(f"/api/alerts/{alert.id}/evidence/")
    data = response.data

    assert response.status_code == 200
    assert data["why_this_alert"]["corroborating_count"] == 5
    assert set(data["why_this_alert"]["corroborating_sources"]) == {
        "CHW", "PHC", "PHARMACY", "SCHOOL", "LAB"
    }
    assert data["why_this_alert"]["context_sources"] == ["WEATHER"]

    # Per-rule safety result, not just a verdict.
    codes = [r["code"] for r in data["safety_check"]["rules"]]
    assert codes == ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
    assert data["safety_check"]["verdict"] == "PASS"

    # Visible agent handoffs.
    assert any(e["agent"] == "ClusterDetectionAgent" for e in data["agent_trace"])
    assert data["human_review"]["required"] is True


def test_officer_marks_an_alert_under_investigation(officer_api, village, sources):
    alert = seed_alert(village, sources)
    response = officer_api.patch(
        f"/api/alerts/{alert.id}/status/",
        {"status": "UNDER_INVESTIGATION", "notes": "Field team dispatched."},
        format="json",
    )

    assert response.status_code == 200
    alert.refresh_from_db()
    assert alert.status == Alert.Status.UNDER_INVESTIGATION
    assert Investigation.objects.filter(alert=alert).exists()


def test_officer_records_the_outcome(officer_api, village, sources):
    alert = seed_alert(village, sources)
    officer_api.patch(
        f"/api/alerts/{alert.id}/status/",
        {"status": "UNDER_INVESTIGATION"},
        format="json",
    )
    response = officer_api.post(
        f"/api/alerts/{alert.id}/feedback/",
        {"outcome": "VALID_SIGNAL", "notes": "Investigation justified."},
        format="json",
    )

    assert response.status_code == 201
    assert "not confirmation of any disease" in response.data["meaning"]

    alert.refresh_from_db()
    assert alert.status == Alert.Status.CLOSED
    feedback = Feedback.objects.get(alert=alert)
    assert feedback.outcome == "VALID_SIGNAL"
    assert feedback.resolution_latency_seconds is not None


def test_feedback_rejects_an_unknown_outcome(officer_api, village, sources):
    alert = seed_alert(village, sources)
    response = officer_api.post(
        f"/api/alerts/{alert.id}/feedback/",
        {"outcome": "OUTBREAK_CONFIRMED"},
        format="json",
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# The Patient Portal (a separate, patient-facing login and dashboard) has
# been removed from the application — see `users.models.User.Role` (no
# PATIENT value) and `patients/urls.py` (no `patient/me/` route). The
# RuralCare domain `Patient`/`PatientAssessment` records the tests above
# already exercise are unaffected: they are Health Worker workflow data,
# never a second authenticated role. `test_old_patient_portal_endpoint_is_gone`
# below is the regression test confirming the removed route stays removed.
# ---------------------------------------------------------------------------
def test_old_patient_portal_endpoint_is_gone(worker_api, officer_api):
    assert worker_api.get("/api/patient/me/").status_code == 404
    assert officer_api.get("/api/patient/me/").status_code == 404


# ---------------------------------------------------------------------------
# The primary acceptance test (Section 39)
# ---------------------------------------------------------------------------
def test_full_flow_worker_login_to_officer_feedback(api, worker, officer, patient, village, sources):
    """Worker login -> assessment -> agents -> aggregation -> community agents
    -> cross-level -> safety -> officer alert -> evidence -> investigation ->
    outcome -> feedback."""

    # 1. Worker logs in with a real token, not force_authenticate.
    login = api.post(
        "/api/auth/login/", {"username": "worker", "password": "demo1234"}, format="json"
    )
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    # 2-5. Assessment through the agent chain, then submitted.
    submitted = api.post(
        "/api/assessments/",
        {
            "patient": patient.id,
            "symptoms": ["fever", "headache"],
            "duration_days": 3,
            "temperature_c": 38.4,
            "encounter_date": "2026-08-05",
        },
        format="json",
    )
    assert submitted.status_code == 201
    assert submitted.data["support"]["triage_level"] == "CONCERNING"

    # 6. The individual signal crossed as an anonymised count.
    assert submitted.data["aggregation"]["signals_written"][0]["encounter_count"] == 1.0

    # 7. Community sources arrive through the Integration Layer.
    ingest_batch(
        [
            {
                "source_code": sources[kind].code,
                "category": category,
                "week_label": "2026-W32",
                "value": value,
                "baseline": baseline,
                "is_reported": True,
            }
            for kind, (value, baseline, category) in CORROBORATED.items()
        ],
        week_label="2026-W32",
    )
    outcome = run_community_pipeline(village, "2026-W32", SignalCategory.FEVER)
    alert = outcome["alert"]

    # 8-10. Cross-level, safety verdict, alert raised.
    assert alert.cross_level_verdict
    assert alert.safety_verdict == "PASS"
    assert alert.severity == "HIGH"

    # 11. Officer logs in.
    officer_login = api.post(
        "/api/auth/login/",
        {"username": "officer", "password": "demo1234"},
        format="json",
    )
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {officer_login.data['access']}")

    dashboard = api.get("/api/officer/dashboard/")
    assert dashboard.data["summary"]["active_alerts"] == 1

    # 12. Evidence view.
    evidence = api.get(f"/api/alerts/{alert.id}/evidence/")
    assert evidence.data["why_this_alert"]["corroborating_count"] == 5
    assert evidence.data["safety_check"]["verdict"] == "PASS"

    # 13. Human investigation.
    api.patch(
        f"/api/alerts/{alert.id}/status/",
        {"status": "UNDER_INVESTIGATION"},
        format="json",
    )

    # 14-15. Outcome and feedback stored.
    feedback = api.post(
        f"/api/alerts/{alert.id}/feedback/",
        {"outcome": "VALID_SIGNAL", "notes": "Confirmed worth investigating."},
        format="json",
    )
    assert feedback.status_code == 201

    alert.refresh_from_db()
    assert alert.status == Alert.Status.CLOSED
    assert Feedback.objects.get(alert=alert).outcome == "VALID_SIGNAL"
