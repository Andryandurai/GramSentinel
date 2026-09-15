"""Operational Context / Temporary Data Source Availability.

Covers the task's own 12-item required test list plus the additional
security tests, organized under the same numbering for traceability.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from alerts.models import Alert
from community.models import DataSource, OperationalContextMode, SourceOperationalContext
from community.operational_context import context_snapshot, resolve_context, validate_no_overlap
from core.constants import SignalCategory, SourceKind
from integrations.ingestion import ingest_batch

User = get_user_model()
pytestmark = pytest.mark.django_db

WEEK_LABEL = "2026-W38"
WEEK_START = dt.date(2026, 9, 14)
WEEK_END = dt.date(2026, 9, 20)


def api_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def school_source(village) -> DataSource:
    return DataSource.objects.create(
        code=f"SCHOOL-{village.code}", name="School", kind=SourceKind.SCHOOL, village=village
    )


@pytest.fixture
def chw_source(village) -> DataSource:
    return DataSource.objects.create(
        code=f"CHW-{village.code}-OC", name="CHW", kind=SourceKind.CHW, village=village
    )


@pytest.fixture
def phc_source(village) -> DataSource:
    return DataSource.objects.create(
        code=f"PHC-{village.code}-OC", name="PHC", kind=SourceKind.PHC, village=village
    )


@pytest.fixture
def holiday_context(school_source, officer) -> SourceOperationalContext:
    return SourceOperationalContext.objects.create(
        source=school_source,
        mode=OperationalContextMode.TEMPORARILY_UNAVAILABLE,
        reason="School holiday",
        starts_on=dt.date(2026, 9, 15),
        ends_on=dt.date(2026, 9, 28),
        created_by=officer,
    )


def _ingest_week(chw_source, phc_source, school_source, *, school_value, week_label=WEEK_LABEL):
    records = [
        {
            "source_code": chw_source.code, "category": SignalCategory.FEVER,
            "week_label": week_label, "value": 14, "baseline": 5, "is_reported": True,
        },
        {
            "source_code": phc_source.code, "category": SignalCategory.FEVER,
            "week_label": week_label, "value": 12, "baseline": 5, "is_reported": True,
        },
    ]
    if school_value is not None:
        records.append(
            {
                "source_code": school_source.code, "category": SignalCategory.FEVER,
                "week_label": week_label, "value": school_value, "baseline": 8, "is_reported": True,
            }
        )
    else:
        records.append(
            {
                "source_code": school_source.code, "category": SignalCategory.FEVER,
                "week_label": week_label, "value": None, "baseline": 8, "is_reported": False,
            }
        )
    ingest_batch(records)


# ===========================================================================
# TEST 1 — holiday + anomalous absenteeism
# ===========================================================================


def test_1_holiday_plus_anomalous_absenteeism(village, chw_source, phc_source, school_source, holiday_context):
    from alerts.services import run_community_pipeline

    _ingest_week(chw_source, phc_source, school_source, school_value=100)
    outcome = run_community_pipeline(village, WEEK_LABEL, SignalCategory.FEVER)
    school_card = next(e for e in outcome["alert"].evidence.all() if e.source_kind == SourceKind.SCHOOL)

    assert school_card.status == "EXPECTED_UNAVAILABLE"
    assert school_card.current_value == 100.0
    assert school_card.is_corroborating is False


# ===========================================================================
# TEST 2 — same data without override
# ===========================================================================


def test_2_same_data_without_override_unchanged(village, chw_source, phc_source, school_source):
    from alerts.services import run_community_pipeline

    _ingest_week(chw_source, phc_source, school_source, school_value=100, week_label="2026-W39")
    outcome = run_community_pipeline(village, "2026-W39", SignalCategory.FEVER)
    school_card = next(e for e in outcome["alert"].evidence.all() if e.source_kind == SourceKind.SCHOOL)

    assert school_card.status == "ANOMALY_DETECTED"
    assert school_card.is_corroborating is True
    assert school_card.operational_context == {}


# ===========================================================================
# TEST 3 — automatic expiry
# ===========================================================================


def test_3_automatic_expiry_after_end_date(village, chw_source, phc_source, school_source, holiday_context):
    from alerts.services import run_community_pipeline

    # A week entirely after 28 Sep 2026.
    _ingest_week(chw_source, phc_source, school_source, school_value=100, week_label="2026-W41")
    outcome = run_community_pipeline(village, "2026-W41", SignalCategory.FEVER)
    school_card = next(e for e in outcome["alert"].evidence.all() if e.source_kind == SourceKind.SCHOOL)

    assert school_card.status == "ANOMALY_DETECTED"
    assert school_card.is_corroborating is True


# ===========================================================================
# TEST 4 — no report during holiday
# ===========================================================================


def test_4_no_report_during_holiday_value_stays_null(
    village, chw_source, phc_source, school_source, holiday_context
):
    from alerts.services import run_community_pipeline

    _ingest_week(chw_source, phc_source, school_source, school_value=None)
    outcome = run_community_pipeline(village, WEEK_LABEL, SignalCategory.FEVER)
    school_card = next(e for e in outcome["alert"].evidence.all() if e.source_kind == SourceKind.SCHOOL)

    assert school_card.status == "EXPECTED_UNAVAILABLE"
    assert school_card.current_value is None
    assert school_card.is_corroborating is False


# ===========================================================================
# TEST 5 — corroboration count
# ===========================================================================


def test_5_corroboration_count_excludes_overridden_source(
    village, chw_source, phc_source, school_source, holiday_context
):
    from alerts.services import run_community_pipeline

    _ingest_week(chw_source, phc_source, school_source, school_value=100)
    outcome = run_community_pipeline(village, WEEK_LABEL, SignalCategory.FEVER)

    assert outcome["alert"].corroborating_source_count == 2


# ===========================================================================
# TEST 6 — school normal after restoration (no context at all)
# ===========================================================================


def test_6_school_contributes_normally_with_no_context(village, chw_source, phc_source, school_source):
    from alerts.services import run_community_pipeline

    _ingest_week(chw_source, phc_source, school_source, school_value=100, week_label="2026-W42")
    outcome = run_community_pipeline(village, "2026-W42", SignalCategory.FEVER)

    assert outcome["alert"].corroborating_source_count == 3


# ===========================================================================
# TEST 7 — village permissions
# ===========================================================================


def test_7_village_b_officer_cannot_modify_village_a_context(
    village, other_village, school_source, holiday_context
):
    officer_b = User.objects.create_user(
        username="officer.oc.b", password="x", role=User.Role.HEALTH_OFFICER, village=other_village
    )
    response = api_for(officer_b).patch(
        f"/api/source-contexts/{holiday_context.id}/", {"reason": "Hacked"}, format="json"
    )
    assert response.status_code == 404

    response = api_for(officer_b).post(f"/api/source-contexts/{holiday_context.id}/cancel/")
    assert response.status_code == 404


# ===========================================================================
# TEST 8 — overlapping contexts
# ===========================================================================


def test_8_overlapping_context_rejected(officer, school_source, holiday_context):
    response = api_for(officer).post(
        "/api/source-contexts/",
        {
            "source": school_source.id,
            "mode": "TEMPORARILY_UNAVAILABLE",
            "reason": "Duplicate config",
            "starts_on": "2026-09-20",
            "ends_on": "2026-10-01",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "starts_on" in response.data["detail"]


def test_8b_non_overlapping_context_after_first_ends_is_allowed(officer, school_source, holiday_context):
    response = api_for(officer).post(
        "/api/source-contexts/",
        {
            "source": school_source.id,
            "mode": "TEMPORARILY_UNAVAILABLE",
            "reason": "Exam week",
            "starts_on": "2026-10-05",
            "ends_on": "2026-10-10",
        },
        format="json",
    )
    assert response.status_code == 201


def test_8c_validate_no_overlap_raises_directly():
    village_dummy = None  # not needed; source fixture used via helper below
    # Exercised via the API tests above for realistic coverage; this test
    # confirms the function itself raises Django's ValidationError, which
    # the serializer translates into a DRF error.
    from community.models import DataSource as DS
    from core.models import Village

    v = Village.objects.create(code="OCVAL", name="OC Validate", cluster="C", population=10)
    s = DS.objects.create(code="OCVAL-S", name="S", kind=SourceKind.SCHOOL, village=v)
    SourceOperationalContext.objects.create(
        source=s, mode=OperationalContextMode.TEMPORARILY_UNAVAILABLE, reason="r",
        starts_on=dt.date(2026, 1, 1), ends_on=dt.date(2026, 1, 10),
    )
    with pytest.raises(ValidationError):
        validate_no_overlap(s, dt.date(2026, 1, 5), dt.date(2026, 1, 15))


# ===========================================================================
# TEST 9 — historical snapshot
# ===========================================================================


def test_9_historical_snapshot_survives_cancellation(
    village, chw_source, phc_source, school_source, holiday_context
):
    from alerts.services import run_community_pipeline

    _ingest_week(chw_source, phc_source, school_source, school_value=100)
    outcome = run_community_pipeline(village, WEEK_LABEL, SignalCategory.FEVER)
    alert_id = outcome["alert"].id

    holiday_context.reason = "Something else entirely"
    holiday_context.cancelled_at = dt.datetime(2027, 1, 1, tzinfo=dt.timezone.utc)
    holiday_context.save(update_fields=["reason", "cancelled_at"])

    alert = Alert.objects.get(id=alert_id)
    school_card = next(e for e in alert.evidence.all() if e.source_kind == SourceKind.SCHOOL)
    assert school_card.operational_context["reason"] == "School holiday"


# ===========================================================================
# TEST 10 — reporting completeness
# ===========================================================================


def test_10_expected_unavailable_does_not_penalise_completeness(
    village, chw_source, phc_source, school_source, holiday_context
):
    from agents.gramsentinel.village_trend import VillageTrendAgent
    from agents.gramsentinel.signal_agents import SIGNAL_AGENTS
    from integrations.ingestion import build_agent_payloads

    _ingest_week(chw_source, phc_source, school_source, school_value=100)
    payloads = build_agent_payloads(village, WEEK_LABEL, SignalCategory.FEVER)
    cards = []
    for payload in payloads:
        agent_cls = SIGNAL_AGENTS.get(payload["source_kind"])
        if agent_cls:
            cards.append(agent_cls().handle(payload, None)["evidence_card"])

    result = VillageTrendAgent().handle(
        {"evidence_cards": cards, "village_code": village.code, "week_label": WEEK_LABEL}, None
    )
    assert result["reporting_completeness"] == 1.0
    assert SourceKind.SCHOOL in result["operationally_unavailable_sources"]


# ===========================================================================
# TEST 11 — context outside window
# ===========================================================================


def test_11_context_outside_evaluation_window_has_no_effect(village, chw_source, phc_source, school_source):
    SourceOperationalContext.objects.create(
        source=school_source, mode=OperationalContextMode.TEMPORARILY_UNAVAILABLE,
        reason="Unrelated period", starts_on=dt.date(2025, 1, 1), ends_on=dt.date(2025, 1, 10),
    )
    from alerts.services import run_community_pipeline

    _ingest_week(chw_source, phc_source, school_source, school_value=100, week_label="2026-W43")
    outcome = run_community_pipeline(village, "2026-W43", SignalCategory.FEVER)
    school_card = next(e for e in outcome["alert"].evidence.all() if e.source_kind == SourceKind.SCHOOL)
    assert school_card.status == "ANOMALY_DETECTED"


# ===========================================================================
# TEST 12 — date boundaries
# ===========================================================================


def test_12_date_boundaries_inclusive_both_ends():
    context = SourceOperationalContext(starts_on=dt.date(2026, 9, 15), ends_on=dt.date(2026, 9, 28))
    # Day before start: no effect.
    assert context.is_applicable(dt.date(2026, 9, 7), dt.date(2026, 9, 13)) is False
    # Exactly the start day: applies.
    assert context.is_applicable(dt.date(2026, 9, 15), dt.date(2026, 9, 15)) is True
    # Exactly the end day: applies.
    assert context.is_applicable(dt.date(2026, 9, 28), dt.date(2026, 9, 28)) is True
    # Day after end: no effect.
    assert context.is_applicable(dt.date(2026, 9, 29), dt.date(2026, 10, 5)) is False


def test_resolve_context_and_snapshot(school_source, holiday_context):
    resolved = resolve_context(school_source.id, WEEK_START, WEEK_END)
    assert resolved is not None
    assert resolved.id == holiday_context.id
    snapshot = context_snapshot(resolved)
    assert snapshot["reason"] == "School holiday"
    assert snapshot["mode"] == "TEMPORARILY_UNAVAILABLE"


# ===========================================================================
# Security tests
# ===========================================================================


def test_worker_cannot_create_context(worker_api, school_source):
    response = worker_api.post(
        "/api/source-contexts/",
        {
            "source": school_source.id, "mode": "TEMPORARILY_UNAVAILABLE",
            "reason": "x", "starts_on": "2026-11-01", "ends_on": "2026-11-05",
        },
        format="json",
    )
    assert response.status_code == 403


def test_worker_cannot_update_context(worker_api, holiday_context):
    response = worker_api.patch(
        f"/api/source-contexts/{holiday_context.id}/", {"reason": "x"}, format="json"
    )
    assert response.status_code == 403


def test_worker_cannot_cancel_context(worker_api, holiday_context):
    response = worker_api.post(f"/api/source-contexts/{holiday_context.id}/cancel/")
    assert response.status_code == 403


def test_cross_village_read_denied(other_village, holiday_context):
    officer_b = User.objects.create_user(
        username="officer.oc.reader", password="x", role=User.Role.HEALTH_OFFICER, village=other_village
    )
    response = api_for(officer_b).get(f"/api/source-contexts/{holiday_context.id}/")
    assert response.status_code == 404


def test_cross_village_list_does_not_leak(village, other_village, school_source, holiday_context):
    officer_b = User.objects.create_user(
        username="officer.oc.list", password="x", role=User.Role.HEALTH_OFFICER, village=other_village
    )
    response = api_for(officer_b).get("/api/source-contexts/")
    assert response.status_code == 200
    assert all(row["id"] != holiday_context.id for row in response.data)


def test_client_cannot_spoof_created_by(officer, school_source):
    other_user = User.objects.create_user(
        username="officer.oc.spoof-target", password="x", role=User.Role.HEALTH_OFFICER
    )
    response = api_for(officer).post(
        "/api/source-contexts/",
        {
            "source": school_source.id, "mode": "TEMPORARILY_UNAVAILABLE", "reason": "x",
            "starts_on": "2026-11-01", "ends_on": "2026-11-05", "created_by": other_user.id,
        },
        format="json",
    )
    assert response.status_code == 201
    context = SourceOperationalContext.objects.get(id=response.data["id"])
    assert context.created_by_id == officer.id


def test_officer_a_cannot_create_context_for_another_villages_source(village, other_village):
    # A village-scoped officer (not the district-wide `officer` fixture,
    # which is deliberately allowed to see every village) attempting to
    # configure a source outside their own village.
    village_officer = User.objects.create_user(
        username="officer.oc.scoped", password="x", role=User.Role.HEALTH_OFFICER, village=village
    )
    source_b = DataSource.objects.create(
        code="SCHOOL-OTHERV", name="School B", kind=SourceKind.SCHOOL, village=other_village
    )
    response = api_for(village_officer).post(
        "/api/source-contexts/",
        {
            "source": source_b.id, "mode": "TEMPORARILY_UNAVAILABLE", "reason": "x",
            "starts_on": "2026-11-01", "ends_on": "2026-11-05",
        },
        format="json",
    )
    assert response.status_code == 404


def test_expected_unavailable_never_shown_as_not_reported_in_relationships(
    village, chw_source, phc_source, school_source, holiday_context
):
    from alerts.services import run_community_pipeline
    from alerts.evidence_relationships import build_evidence_relationships

    _ingest_week(chw_source, phc_source, school_source, school_value=100)
    outcome = run_community_pipeline(village, WEEK_LABEL, SignalCategory.FEVER)
    alert = outcome["alert"]
    relationships = build_evidence_relationships(alert, list(alert.evidence.all()))

    school_entry = next(c for c in relationships["context"] if c["source_kind"] == SourceKind.SCHOOL)
    assert "not submit" not in school_entry["reason"].lower()
    assert "school holiday" in school_entry["reason"].lower()
