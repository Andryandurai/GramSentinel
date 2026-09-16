"""Pregnancy / Maternal Health follow-up — model, rules, API, and security
tests (task §29/§30/§31/§32)."""

from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from core.models import Village
from patients.models import Patient
from pregnancy import rules
from pregnancy.models import PicmeRchStatus, PregnancyProfile, PregnancyStatus
from pregnancy.questionnaire import warning_sign_keys

User = get_user_model()
pytestmark = pytest.mark.django_db

PROFILES = "/api/pregnancy/profiles/"


def api_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def village_b(db) -> Village:
    return Village.objects.create(code="PREG-B", name="Other Village", cluster="Cluster B", district="Madurai")


@pytest.fixture
def worker_a(db, village):
    return User.objects.create_user(username="preg.worker.a", password="x", role=User.Role.CHW_PHC_WORKER, village=village)


@pytest.fixture
def worker_b(db, village_b):
    return User.objects.create_user(username="preg.worker.b", password="x", role=User.Role.CHW_PHC_WORKER, village=village_b)


@pytest.fixture
def officer_a(db, village):
    return User.objects.create_user(username="preg.officer.a", password="x", role=User.Role.HEALTH_OFFICER, village=village)


@pytest.fixture
def officer_b(db, village_b):
    return User.objects.create_user(username="preg.officer.b", password="x", role=User.Role.HEALTH_OFFICER, village=village_b)


@pytest.fixture
def patient_a(db, village, worker_a) -> Patient:
    return Patient.objects.create(
        patient_code="PREG-A-001", display_name="Test Patient A", age_years=27, sex="F",
        village=village, created_by=worker_a,
    )


@pytest.fixture
def patient_b(db, village_b, worker_b) -> Patient:
    return Patient.objects.create(
        patient_code="PREG-B-001", display_name="Test Patient B", age_years=24, sex="F",
        village=village_b, created_by=worker_b,
    )


def visit1_payload(**overrides) -> dict:
    payload = {
        "visit_number": 1,
        "responses": {
            "first_pregnancy": "YES",
            "previous_complications": "NO",
            "vaginal_bleeding": "NO",
            "severe_abdominal_pain": "NO",
            "severe_vomiting": "NO",
            "fever_chills": "NO",
            "severe_headache_vision": "NO",
            "existing_health_problems": "NO",
            "iron_folic_started": "YES",
        },
        "next_checkup_date": "2099-01-15",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# 1-6. Model / rules / questionnaire.
# ---------------------------------------------------------------------------
def test_questionnaire_has_ten_questions_per_visit():
    from pregnancy.questionnaire import questions_for_visit

    for visit_number in (1, 2, 3, 4):
        assert len(questions_for_visit(visit_number)) == 10


def test_warning_signs_detected_from_responses():
    signs = rules.warning_signs_in_responses(1, {"vaginal_bleeding": "YES", "first_pregnancy": "YES"})
    assert signs == ["vaginal_bleeding"]


def test_no_warning_signs_when_all_no():
    signs = rules.warning_signs_in_responses(1, {k: "NO" for k in warning_sign_keys(1)})
    assert signs == []


def test_create_pregnancy_profile(worker_a, patient_a, village):
    response = api_for(worker_a).post(PROFILES, {"patient": patient_a.id}, format="json")
    assert response.status_code == 201
    assert response.data["status"] == "ACTIVE"
    assert response.data["picme_rch_status"] == "NOT_AVAILABLE"
    assert response.data["visits"] == []


def test_duplicate_active_pregnancy_prevented(worker_a, patient_a):
    api = api_for(worker_a)
    first = api.post(PROFILES, {"patient": patient_a.id}, format="json")
    assert first.status_code == 201
    second = api.post(PROFILES, {"patient": patient_a.id}, format="json")
    assert second.status_code == 409


def test_completed_pregnancy_allows_a_new_active_profile(worker_a, patient_a):
    api = api_for(worker_a)
    first_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    api.patch(f"{PROFILES}{first_id}/", {"status": "COMPLETED"}, format="json")
    second = api.post(PROFILES, {"patient": patient_a.id}, format="json")
    assert second.status_code == 201


# ---------------------------------------------------------------------------
# Pregnancy must not be available for a patient whose stored sex is MALE.
# Enforced server-side in `pregnancy.services.create_pregnancy_profile` —
# the one place a PregnancyProfile is ever created — using Patient.sex from
# the database, never a client-supplied value.
# ---------------------------------------------------------------------------
@pytest.fixture
def male_patient(db, village, worker_a) -> Patient:
    return Patient.objects.create(
        patient_code="PREG-A-MALE", display_name="Male Patient", age_years=30, sex="M",
        village=village, created_by=worker_a,
    )


def test_pregnancy_profile_rejected_for_male_patient(worker_a, male_patient):
    response = api_for(worker_a).post(PROFILES, {"patient": male_patient.id}, format="json")
    assert response.status_code == 400
    assert not PregnancyProfile.objects.filter(patient=male_patient).exists()


def test_pregnancy_profile_still_works_for_female_patient(worker_a, patient_a):
    """Regression: the male-only rejection must not touch the existing,
    already-working female workflow."""

    response = api_for(worker_a).post(PROFILES, {"patient": patient_a.id}, format="json")
    assert response.status_code == 201


def test_pregnancy_rejection_uses_stored_sex_not_client_input(worker_a, male_patient):
    """The endpoint has no `sex`/`gender` field to accept in the first
    place — attribution always comes from the stored Patient row, the same
    'never trust a client-supplied identity field' rule this codebase
    already applies to worker/village/officer ids elsewhere."""

    response = api_for(worker_a).post(
        PROFILES, {"patient": male_patient.id, "sex": "F", "gender": "F"}, format="json"
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 7-10. Visit recording — 1 through 4, warning signs, PICME.
# ---------------------------------------------------------------------------
def test_record_visits_1_through_4_and_count_completed(worker_a, patient_a):
    api = api_for(worker_a)
    profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]

    for visit_number in (1, 2, 3, 4):
        response = api.post(
            f"{PROFILES}{profile_id}/visits/",
            visit1_payload(visit_number=visit_number, responses={}),
            format="json",
        )
        assert response.status_code == 201, response.data

    detail = api.get(f"{PROFILES}{profile_id}/")
    assert detail.data["visit_status"]["completed_visit_count"] == 4
    assert len(detail.data["visits"]) == 4


def test_arbitrary_visit_number_rejected(worker_a, patient_a):
    api = api_for(worker_a)
    profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    response = api.post(
        f"{PROFILES}{profile_id}/visits/",
        {"visit_number": "third visit maybe", "responses": {}},
        format="json",
    )
    assert response.status_code == 400


def test_unknown_question_key_rejected(worker_a, patient_a):
    api = api_for(worker_a)
    profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    response = api.post(
        f"{PROFILES}{profile_id}/visits/",
        {"visit_number": 1, "responses": {"not_a_real_question": "YES"}},
        format="json",
    )
    assert response.status_code == 400


def test_invalid_answer_value_rejected(worker_a, patient_a):
    api = api_for(worker_a)
    profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    response = api.post(
        f"{PROFILES}{profile_id}/visits/",
        {"visit_number": 1, "responses": {"vaginal_bleeding": "maybe"}},
        format="json",
    )
    assert response.status_code == 400


def test_warning_sign_triggers_urgent_review_and_never_diagnoses(worker_a, patient_a):
    api = api_for(worker_a)
    profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    response = api.post(
        f"{PROFILES}{profile_id}/visits/",
        visit1_payload(responses={"vaginal_bleeding": "YES"}),
        format="json",
    )
    assert response.status_code == 201
    guidance = response.data["visit"]["ai_guidance"]
    assert guidance["follow_up_status"] == "URGENT_REVIEW_REQUIRED"
    assert guidance["requires_human_review"] is True
    assert "vaginal_bleeding" in response.data["visit"]["warning_signs"]
    # Never a named diagnosis or a disease claim (task §11/§37).
    banned = ("diagnos", "preeclampsia", "eclampsia", "confirmed", "you have dengue")
    text = (guidance["visit_summary"] + guidance["suggested_action"]).lower()
    assert not any(term in text for term in banned)


def test_missing_information_never_coerced_to_a_value(worker_a, patient_a):
    """An unanswered question is simply absent — never stored as NO/0."""

    api = api_for(worker_a)
    profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    response = api.post(
        f"{PROFILES}{profile_id}/visits/",
        {"visit_number": 1, "responses": {"vaginal_bleeding": "NO"}, "next_checkup_date": None},
        format="json",
    )
    assert response.status_code == 201
    responses = response.data["profile"]["visits"][0]["questionnaire_responses"]
    assert "severe_abdominal_pain" not in responses
    assert response.data["profile"]["next_checkup_date"] is None


def test_picme_recorded_via_visit_and_via_patch(worker_a, patient_a):
    api = api_for(worker_a)
    profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]

    response = api.post(
        f"{PROFILES}{profile_id}/visits/",
        visit1_payload(picme_rch_id="TN-2026-000999", picme_rch_status="AVAILABLE"),
        format="json",
    )
    assert response.data["profile"]["picme_rch_id"] == "TN-2026-000999"
    assert response.data["profile"]["picme_rch_status"] == "AVAILABLE"

    patched = api.patch(f"{PROFILES}{profile_id}/", {"picme_rch_status": "REGISTRATION_PENDING"}, format="json")
    assert patched.data["picme_rch_status"] == "REGISTRATION_PENDING"


def test_missing_picme_flagged(worker_a, patient_a):
    api = api_for(worker_a)
    profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    response = api.post(f"{PROFILES}{profile_id}/visits/", visit1_payload(), format="json")
    flags = {f["rule"] for f in response.data["visit"]["rule_flags"]}
    assert rules.MISSING_PICME in flags


# ---------------------------------------------------------------------------
# 11-13. Overdue / follow-up logic — never "fewer than 4" alone.
# ---------------------------------------------------------------------------
def test_future_checkup_no_overdue(worker_a, patient_a):
    api = api_for(worker_a)
    profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    response = api.post(
        f"{PROFILES}{profile_id}/visits/",
        visit1_payload(next_checkup_date="2099-01-01"),
        format="json",
    )
    flags = {f["rule"] for f in response.data["visit"]["rule_flags"]}
    assert rules.FOLLOW_UP_OVERDUE not in flags


def test_past_checkup_is_overdue(worker_a, patient_a):
    api = api_for(worker_a)
    profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    api.post(f"{PROFILES}{profile_id}/visits/", visit1_payload(next_checkup_date="2020-01-01"), format="json")
    detail = api.get(f"{PROFILES}{profile_id}/")
    flags = {f["rule"] for f in detail.data["visit_status"]["rule_flags"]}
    assert rules.FOLLOW_UP_OVERDUE in flags


def test_early_stage_with_future_appointment_not_flagged_overdue(worker_a, patient_a):
    """2 completed visits, pregnancy genuinely early (LMP recent), next
    appointment in the future -> must not be treated as overdue just
    because the raw count is below 4 (task §17/§31)."""

    api = api_for(worker_a)
    profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    recent_lmp = (dt.date.today() - dt.timedelta(weeks=8)).isoformat()
    api.post(
        f"{PROFILES}{profile_id}/visits/",
        visit1_payload(responses={"lmp_date": recent_lmp}, next_checkup_date="2099-06-01"),
        format="json",
    )
    detail = api.get(f"{PROFILES}{profile_id}/")
    flags = {f["rule"] for f in detail.data["visit_status"]["rule_flags"]}
    assert rules.FOLLOW_UP_OVERDUE not in flags
    assert rules.LOW_VISIT_COMPLETION_FOR_STAGE not in flags


def test_four_visits_reaches_monitoring_target(worker_a, patient_a):
    api = api_for(worker_a)
    profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    for visit_number in (1, 2, 3, 4):
        api.post(
            f"{PROFILES}{profile_id}/visits/",
            visit1_payload(visit_number=visit_number, responses={}, next_checkup_date="2099-01-01"),
            format="json",
        )
    detail = api.get(f"{PROFILES}{profile_id}/")
    flags = {f["rule"] for f in detail.data["visit_status"]["rule_flags"]}
    assert rules.ANC_4PLUS_TARGET_NOT_YET_REACHED not in flags
    assert rules.LOW_VISIT_COMPLETION_FOR_STAGE not in flags


def test_no_next_checkup_date_shows_not_recorded(worker_a, patient_a):
    api = api_for(worker_a)
    profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    detail = api.get(f"{PROFILES}{profile_id}/")
    assert detail.data["next_checkup_date"] is None
    flags = {f["rule"] for f in detail.data["visit_status"]["rule_flags"]}
    assert rules.MISSING_NEXT_CHECKUP in flags


# ---------------------------------------------------------------------------
# 14-19. Officer view, follow-up request, security.
# ---------------------------------------------------------------------------
def test_officer_sees_village_pregnancy_summary(worker_a, officer_a, patient_a):
    api_for(worker_a).post(PROFILES, {"patient": patient_a.id}, format="json")
    response = api_for(officer_a).get("/api/pregnancy/officer/summary/")
    assert response.status_code == 200
    assert response.data["active_pregnancies"] == 1


def test_officer_list_never_exposes_patient_display_name(worker_a, officer_a, patient_a):
    api_for(worker_a).post(PROFILES, {"patient": patient_a.id}, format="json")
    response = api_for(officer_a).get("/api/pregnancy/officer/list/")
    assert response.status_code == 200
    row = response.data[0]
    assert "patient_name" not in row
    assert "display_name" not in row
    assert row["patient_code"] == patient_a.patient_code


def test_follow_up_required_filter_only_flags_genuine_overdue(worker_a, officer_a, patient_a):
    api = api_for(worker_a)
    profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    # Only 1 of 4 visits, but next check-up is in the future — must not
    # appear under "follow-up required".
    api.post(f"{PROFILES}{profile_id}/visits/", visit1_payload(next_checkup_date="2099-01-01"), format="json")

    officer_api = api_for(officer_a)
    flagged = officer_api.get("/api/pregnancy/officer/list/?follow_up_required=1")
    assert flagged.data == []


def test_officer_can_request_health_worker_followup_and_worker_sees_it(worker_a, officer_a, patient_a, village):
    api = api_for(worker_a)
    profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    api.patch(f"{PROFILES}{profile_id}/", {"next_checkup_date": "2020-01-01"}, format="json")

    officer_api = api_for(officer_a)
    response = officer_api.post(
        f"/api/pregnancy/officer/profiles/{profile_id}/request-followup/",
        {"priority": "URGENT", "due_date": "2026-12-01", "reason": "Overdue ANC follow-up"},
        format="json",
    )
    assert response.status_code == 201

    dashboard = api.get("/api/worker/dashboard/")
    notes = [f["notes"] for f in dashboard.data["pending_followups"]]
    assert any("Overdue ANC follow-up" in n for n in notes)


def test_worker_cannot_access_another_villages_pregnancy_profile(worker_a, worker_b, patient_a):
    profile_id = api_for(worker_a).post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    response = api_for(worker_b).get(f"{PROFILES}{profile_id}/")
    assert response.status_code == 404


def test_officer_cannot_access_another_villages_pregnancy_data(worker_a, officer_b, patient_a):
    profile_id = api_for(worker_a).post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    detail = api_for(officer_b).get("/api/pregnancy/officer/list/")
    assert detail.data == []
    followup = api_for(officer_b).post(
        f"/api/pregnancy/officer/profiles/{profile_id}/request-followup/",
        {"priority": "NORMAL", "due_date": "2026-12-01"},
        format="json",
    )
    assert followup.status_code == 404


def test_officer_cannot_record_a_visit(worker_a, officer_a, patient_a):
    profile_id = api_for(worker_a).post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    response = api_for(officer_a).post(f"{PROFILES}{profile_id}/visits/", {"visit_number": 1}, format="json")
    assert response.status_code == 403


def test_worker_cannot_access_officer_endpoints(worker_a):
    response = api_for(worker_a).get("/api/pregnancy/officer/summary/")
    assert response.status_code == 403


def test_unauthenticated_access_denied():
    response = APIClient().get("/api/pregnancy/officer/summary/")
    assert response.status_code == 401


def test_picme_never_appears_in_worker_dashboard_or_officer_summary(worker_a, officer_a, patient_a):
    """Task §19/§28: PICME/RCH IDs must never surface through an aggregate
    endpoint."""

    api = api_for(worker_a)
    profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    api.post(
        f"{PROFILES}{profile_id}/visits/",
        visit1_payload(picme_rch_id="TN-SECRET-000777", picme_rch_status="AVAILABLE"),
        format="json",
    )

    officer_summary = api_for(officer_a).get("/api/pregnancy/officer/summary/")
    assert "TN-SECRET-000777" not in str(officer_summary.data)

    worker_summary = api.get("/api/pregnancy/worker/summary/")
    assert "TN-SECRET-000777" not in str(worker_summary.data)

    officer_list = api_for(officer_a).get("/api/pregnancy/officer/list/")
    assert "TN-SECRET-000777" not in str(officer_list.data)


# ---------------------------------------------------------------------------
# 20-24. Multilingual AI guidance — task §41/§42/§43 equivalence tests.
# ---------------------------------------------------------------------------
def test_language_defaults_to_english_when_omitted(worker_a, patient_a):
    api = api_for(worker_a)
    profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    response = api.post(f"{PROFILES}{profile_id}/visits/", visit1_payload(), format="json")
    assert response.data["visit"]["ai_guidance"]["visit_summary"].isascii()


def test_invalid_language_value_rejected(worker_a, patient_a):
    api = api_for(worker_a)
    profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
    response = api.post(
        f"{PROFILES}{profile_id}/visits/",
        visit1_payload(language="fr"),
        format="json",
    )
    assert response.status_code == 400


def test_tamil_and_hindi_guidance_are_genuinely_different_text(worker_a, patient_a):
    """Same input, three languages — the narrative text must actually
    differ (task §41), and Tamil/Hindi text must not just be the English
    ASCII fallback."""

    api = api_for(worker_a)
    summaries = {}
    for language in ("en", "ta", "hi"):
        profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
        response = api.post(
            f"{PROFILES}{profile_id}/visits/",
            visit1_payload(language=language),
            format="json",
        )
        assert response.status_code == 201
        summaries[language] = response.data["visit"]["ai_guidance"]["visit_summary"]
        # Clean up so the next language's profile creation doesn't collide
        # with the "one active pregnancy" constraint.
        api.patch(f"{PROFILES}{profile_id}/", {"status": "COMPLETED"}, format="json")

    assert summaries["en"] != summaries["ta"]
    assert summaries["en"] != summaries["hi"]
    assert summaries["ta"] != summaries["hi"]
    # Tamil/Hindi text is not just the English string re-encoded — it must
    # contain non-ASCII script characters.
    assert not summaries["ta"].isascii()
    assert not summaries["hi"].isascii()


def test_structured_guidance_fields_identical_across_languages(worker_a, patient_a):
    """Task §42: follow_up_status, warning_signs, next_checkup and rule
    flags must not change simply because the UI language changed — only
    the free-text narrative may vary."""

    api = api_for(worker_a)
    results = {}
    for language in ("en", "ta", "hi"):
        profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
        response = api.post(
            f"{PROFILES}{profile_id}/visits/",
            visit1_payload(
                responses={"vaginal_bleeding": "YES"},
                next_checkup_date="2099-01-01",
                language=language,
            ),
            format="json",
        )
        results[language] = response.data
        api.patch(f"{PROFILES}{profile_id}/", {"status": "COMPLETED"}, format="json")

    for language in ("ta", "hi"):
        assert results[language]["visit"]["warning_signs"] == results["en"]["visit"]["warning_signs"]
        assert (
            results[language]["visit"]["ai_guidance"]["follow_up_status"]
            == results["en"]["visit"]["ai_guidance"]["follow_up_status"]
        )
        assert (
            results[language]["visit"]["ai_guidance"]["requires_human_review"]
            == results["en"]["visit"]["ai_guidance"]["requires_human_review"]
        )
        en_rules = {f["rule"] for f in results["en"]["visit"]["rule_flags"]}
        other_rules = {f["rule"] for f in results[language]["visit"]["rule_flags"]}
        assert en_rules == other_rules


def test_warning_sign_scenario_identical_safety_decision_across_languages(worker_a, patient_a):
    """Task §43: the same warning-sign scenario (severe headache = YES)
    must produce the identical safety decision (URGENT_REVIEW_REQUIRED,
    requires_human_review=True) in every language — only the wording of
    the warning differs."""

    api = api_for(worker_a)
    for language in ("en", "ta", "hi"):
        profile_id = api.post(PROFILES, {"patient": patient_a.id}, format="json").data["id"]
        response = api.post(
            f"{PROFILES}{profile_id}/visits/",
            visit1_payload(
                responses={"severe_headache_vision": "YES"},
                language=language,
            ),
            format="json",
        )
        guidance = response.data["visit"]["ai_guidance"]
        assert guidance["follow_up_status"] == "URGENT_REVIEW_REQUIRED"
        assert guidance["requires_human_review"] is True
        assert "severe_headache_vision" in response.data["visit"]["warning_signs"]
        api.patch(f"{PROFILES}{profile_id}/", {"status": "COMPLETED"}, format="json")
