"""The aggregation boundary, Stage-1 ingestion, and the full pipeline.

The privacy tests here are the ones worth keeping honest: they assert that no
identifier can cross from the individual layer into community surveillance,
using the actual code path rather than a promise in a document.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from alerts.models import Alert, SafetyCheck
from alerts.services import run_community_pipeline
from assessments.models import PatientAssessment
from community.aggregation import (
    PERMITTED_AGGREGATE_FIELDS,
    aggregate_village_week,
    aggregated_individual_snapshot,
    assert_no_identifiers,
    build_aggregate_payloads,
    week_bounds,
    week_label_for,
)
from community.models import CommunitySignal
from core.constants import DataQuality, SignalCategory, SourceKind
from integrations.ingestion import ingest_batch, build_agent_payloads
from integrations.models import IngestionEvent

pytestmark = pytest.mark.django_db


def _encounter(patient, village, category, date, worker=None):
    return PatientAssessment.objects.create(
        patient=patient,
        worker=worker,
        village=village,
        symptoms=["fever"],
        duration_days=3,
        primary_category=category,
        triage_level="CONCERNING",
        is_draft=False,
        encounter_date=date,
    )


# ---------------------------------------------------------------------------
# The aggregation boundary
# ---------------------------------------------------------------------------
def test_aggregate_payload_contains_only_permitted_fields(patient, village):
    today = timezone.localdate()
    _encounter(patient, village, SignalCategory.FEVER, today)
    start, end = week_bounds(today)

    payloads = build_aggregate_payloads(village, start, end)

    assert payloads
    for payload in payloads:
        assert set(payload) <= PERMITTED_AGGREGATE_FIELDS
        assert_no_identifiers(payload)


def test_aggregate_payload_carries_no_patient_identifier(patient, village):
    today = timezone.localdate()
    assessment = _encounter(patient, village, SignalCategory.FEVER, today)
    start, end = week_bounds(today)

    payloads = build_aggregate_payloads(village, start, end)
    flat = str(payloads)

    assert patient.patient_code not in flat
    assert patient.display_name not in flat

    # Structural rather than value-matching: the guarantee is that the payload
    # carries no field capable of identifying a patient or an encounter. A
    # value check would be meaningless — an encounter count of 1 is
    # indistinguishable from a patient id of 1, and the count is legitimate.
    for payload in payloads:
        assert set(payload) <= PERMITTED_AGGREGATE_FIELDS
        assert not any(
            token in key.lower()
            for key in payload
            for token in ("patient", "assessment", "name", "id")
        )

    # And the guard rail refuses to emit one if a future change adds it.
    with pytest.raises(ValueError):
        assert_no_identifiers({**payloads[0], "assessment_id": assessment.id})


def test_boundary_guard_rejects_a_leaked_field():
    with pytest.raises(ValueError, match="Aggregation boundary violation"):
        assert_no_identifiers(
            {"village_code": "KVL", "category": "FEVER", "patient_code": "KVL-P-001"}
        )


def test_community_signal_holds_a_count_not_records(patient, village):
    today = timezone.localdate()
    for _ in range(3):
        _encounter(patient, village, SignalCategory.FEVER, today)

    signals = aggregate_village_week(village, today)
    fever = next(s for s in signals if s.category == SignalCategory.FEVER)

    assert fever.value == 3.0
    assert fever.unit == "encounters"
    assert fever.source.kind == SourceKind.RURALCARE_AGGREGATE
    # Nothing on the community model can reach back to a patient.
    assert not hasattr(fever, "patient")
    assert not hasattr(fever, "assessment")


def test_aggregation_is_idempotent(patient, village):
    today = timezone.localdate()
    _encounter(patient, village, SignalCategory.FEVER, today)

    aggregate_village_week(village, today)
    aggregate_village_week(village, today)

    label = week_label_for(week_bounds(today)[0])
    rows = CommunitySignal.objects.filter(
        village=village, week_label=label, category=SignalCategory.FEVER
    )
    assert rows.count() == 1
    assert rows.first().value == 1.0


def test_aggregation_marks_encounters_as_aggregated(patient, village):
    today = timezone.localdate()
    assessment = _encounter(patient, village, SignalCategory.FEVER, today)
    assert assessment.aggregated_at is None

    aggregate_village_week(village, today)
    assessment.refresh_from_db()
    assert assessment.aggregated_at is not None


def test_snapshot_exposes_only_counts(patient, village):
    today = timezone.localdate()
    _encounter(patient, village, SignalCategory.FEVER, today)
    aggregate_village_week(village, today)

    snapshot = aggregated_individual_snapshot(
        village, week_label_for(week_bounds(today)[0])
    )
    assert set(snapshot) == {
        "village_code",
        "week_label",
        "counts_by_category",
        "baselines_by_category",
    }


# ---------------------------------------------------------------------------
# Stage 1 — ingestion
# ---------------------------------------------------------------------------
def test_ingestion_rejects_a_record_with_no_value(sources):
    event = ingest_batch(
        [
            {
                "source_code": sources[SourceKind.CHW].code,
                "category": SignalCategory.FEVER,
                "week_label": "2026-W32",
                "value": None,
                "is_reported": True,
            }
        ]
    )
    assert event.records_rejected == 1
    assert event.result == IngestionEvent.Result.REJECTED


def test_ingestion_rejects_a_missing_record_that_carries_a_number(sources):
    """This is the guarantee behind Safety Rule 8, enforced at the front door."""

    event = ingest_batch(
        [
            {
                "source_code": sources[SourceKind.SCHOOL].code,
                "category": SignalCategory.FEVER,
                "week_label": "2026-W32",
                "value": 0,
                "is_reported": False,
            }
        ]
    )
    assert event.records_rejected == 1
    assert "must not be given a number" in str(event.validation_notes)


def test_ingestion_stores_a_non_submission_as_missing(sources):
    ingest_batch(
        [
            {
                "source_code": sources[SourceKind.SCHOOL].code,
                "category": SignalCategory.FEVER,
                "week_label": "2026-W32",
                "value": None,
                "baseline": 6.0,
                "is_reported": False,
            }
        ]
    )
    signal = CommunitySignal.objects.get(source=sources[SourceKind.SCHOOL])
    assert signal.is_reported is False
    assert signal.value is None
    assert signal.data_quality == DataQuality.MISSING


def test_ingestion_deduplicates_a_resubmitted_window(sources):
    record = {
        "source_code": sources[SourceKind.CHW].code,
        "category": SignalCategory.FEVER,
        "week_label": "2026-W32",
        "value": 14,
        "baseline": 5,
        "is_reported": True,
    }
    ingest_batch([record])
    event = ingest_batch([{**record, "value": 15}])

    assert event.records_deduplicated == 1
    assert CommunitySignal.objects.filter(source=sources[SourceKind.CHW]).count() == 1
    assert CommunitySignal.objects.get(source=sources[SourceKind.CHW]).value == 15.0


def test_ingestion_rejects_an_unregistered_source():
    event = ingest_batch(
        [
            {
                "source_code": "NOT-A-REAL-SOURCE",
                "category": SignalCategory.FEVER,
                "week_label": "2026-W32",
                "value": 10,
                "is_reported": True,
            }
        ]
    )
    assert event.records_rejected == 1


def test_registered_source_with_no_data_becomes_a_missing_card(village, sources):
    """A silent gap must not simply vanish from the evidence set."""

    payloads = build_agent_payloads(village, "2026-W32", SignalCategory.FEVER)
    kinds = {p["source_kind"] for p in payloads}

    assert SourceKind.SCHOOL in kinds
    assert all(p["is_reported"] is False for p in payloads)


# ---------------------------------------------------------------------------
# The full community pipeline
# ---------------------------------------------------------------------------
def _seed_window(sources, week_label, values):
    records = []
    for kind, (value, baseline, category) in values.items():
        records.append(
            {
                "source_code": sources[kind].code,
                "category": category,
                "week_label": week_label,
                "value": value,
                "baseline": baseline,
                "is_reported": True,
                "data_quality": DataQuality.GOOD,
            }
        )
    ingest_batch(records, week_label=week_label)


CORROBORATED = {
    SourceKind.CHW: (14, 5, SignalCategory.FEVER),
    SourceKind.PHC: (31, 19, SignalCategory.FEVER),
    SourceKind.PHARMACY: (310, 200, SignalCategory.FEVER),
    SourceKind.SCHOOL: (14.0, 6.0, SignalCategory.FEVER),
    SourceKind.WEATHER: (240, 110, SignalCategory.ENVIRONMENT),
    SourceKind.LAB: (1, 0, SignalCategory.LAB_CONFIRMATION),
}


def test_pipeline_raises_a_high_severity_alert_when_sources_corroborate(
    village, sources
):
    _seed_window(sources, "2026-W32", CORROBORATED)
    outcome = run_community_pipeline(village, "2026-W32", SignalCategory.FEVER)

    assert outcome["alert_raised"] is True
    alert = outcome["alert"]
    assert alert.severity == Alert.Severity.HIGH
    assert alert.safety_verdict == "PASS"
    assert alert.corroborating_source_count == 5
    assert alert.status == Alert.Status.DETECTED


def test_pipeline_records_every_evidence_card_including_context_and_missing(
    village, sources
):
    _seed_window(sources, "2026-W32", CORROBORATED)
    alert = run_community_pipeline(village, "2026-W32", SignalCategory.FEVER)["alert"]

    statuses = {e.source_kind: e.status for e in alert.evidence.all()}
    assert statuses[SourceKind.CHW] == "ANOMALY_DETECTED"
    assert statuses[SourceKind.WEATHER] == "SUPPORTING_CONTEXT"
    assert statuses[SourceKind.LAB] == "CORROBORATING"
    assert not any(e.is_corroborating for e in alert.evidence.filter(
        source_kind=SourceKind.WEATHER
    ))


def test_pipeline_downgrades_a_single_rising_source(village, sources):
    _seed_window(
        sources,
        "2026-W32",
        {
            SourceKind.CHW: (14, 5, SignalCategory.FEVER),
            SourceKind.PHC: (19, 19, SignalCategory.FEVER),
            SourceKind.PHARMACY: (201, 200, SignalCategory.FEVER),
            SourceKind.SCHOOL: (6.0, 6.0, SignalCategory.FEVER),
        },
    )
    outcome = run_community_pipeline(village, "2026-W32", SignalCategory.FEVER)

    assert outcome["safety"]["verdict"] == "DOWNGRADE"
    assert outcome["alert"].severity == Alert.Severity.LOW


def test_pipeline_raises_nothing_when_no_source_moves(village, sources):
    _seed_window(
        sources,
        "2026-W32",
        {
            SourceKind.CHW: (5, 5, SignalCategory.FEVER),
            SourceKind.PHC: (19, 19, SignalCategory.FEVER),
        },
    )
    outcome = run_community_pipeline(village, "2026-W32", SignalCategory.FEVER)

    assert outcome["alert_raised"] is False
    assert Alert.objects.count() == 0
    # The decision is still recorded, so the absence of an alert is auditable.
    assert SafetyCheck.objects.filter(village=village).exists()


def test_pipeline_records_the_agent_trace(village, sources):
    _seed_window(sources, "2026-W32", CORROBORATED)
    outcome = run_community_pipeline(village, "2026-W32", SignalCategory.FEVER)

    from alerts.models import AgentRun

    runs = AgentRun.objects.filter(run_id=outcome["alert"].orchestration_run_id)
    names = list(runs.order_by("sequence").values_list("agent_name", flat=True))

    assert "CHWSignalAgent" in names
    assert "VillageTrendAgent" in names
    assert "ClusterDetectionAgent" in names
    assert "CrossLevelIntelligenceAgent" in names
    # The cross-level agent runs after the cluster agent, not before it.
    assert names.index("CrossLevelIntelligenceAgent") > names.index(
        "ClusterDetectionAgent"
    )


def test_rerunning_the_pipeline_replaces_rather_than_duplicates(village, sources):
    _seed_window(sources, "2026-W32", CORROBORATED)
    run_community_pipeline(village, "2026-W32", SignalCategory.FEVER)
    run_community_pipeline(village, "2026-W32", SignalCategory.FEVER)

    assert Alert.objects.filter(village=village, week_label="2026-W32").count() == 1


def test_cross_level_verdict_is_stored_on_the_alert(village, sources, patient):
    week_start = dt.date.fromisocalendar(2026, 32, 1)
    for _ in range(7):
        _encounter(patient, village, SignalCategory.FEVER, week_start)
    aggregate_village_week(village, week_start)

    _seed_window(sources, "2026-W32", CORROBORATED)
    alert = run_community_pipeline(village, "2026-W32", SignalCategory.FEVER)["alert"]

    assert alert.cross_level_verdict in {"CONSISTENT", "SILENT", "CONTRADICTORY"}
    assert alert.cross_level_statement
