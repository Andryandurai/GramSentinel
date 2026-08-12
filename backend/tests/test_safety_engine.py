"""The safety engine gets disproportionate testing attention on purpose.

It is the component the entire safety argument rests on, and because it is
deterministic it can be tested exhaustively in a way model behaviour cannot.

These cases mirror the mandatory scenarios in the specification (Section 28 /
36.2), including the two adversarial ones: an LLM that says "no concern" while
the evidence corroborates, and a red-flag case the model called routine.
"""

from __future__ import annotations

import datetime as dt

import pytest

from core.constants import DataQuality, SourceKind
from safety import IndividualCase, SafetyEngine
from safety.engine import VERDICT_BLOCK, VERDICT_DOWNGRADE, VERDICT_PASS

from .conftest import WEEK_END, WEEK_START, make_hypothesis, make_record

pytestmark = pytest.mark.django_db


@pytest.fixture
def engine() -> SafetyEngine:
    return SafetyEngine()


def rule(result, code: str):
    return next(r for r in result.rules if r.code == code)


# ---------------------------------------------------------------------------
# Scenario 1 — a single anomalous source cannot produce a high-priority alert
# ---------------------------------------------------------------------------
def test_single_source_cannot_raise_high_priority_alert(engine):
    records = (
        make_record(SourceKind.CHW),
        make_record(SourceKind.PHC, status="NORMAL", change_pct=4.0),
        make_record(SourceKind.PHARMACY, status="NORMAL", change_pct=2.0),
    )
    result = engine.evaluate_community(make_hypothesis(records), records)

    assert result.verdict == VERDICT_DOWNGRADE
    assert result.severity != "HIGH"
    assert result.corroborating_source_count == 1
    assert not rule(result, "R1").passed
    assert not rule(result, "R2").passed


# ---------------------------------------------------------------------------
# Scenario 2 — two independent, consistent sources proceed to human review
# ---------------------------------------------------------------------------
def test_two_independent_sources_pass_to_human_review(engine):
    records = (
        make_record(SourceKind.CHW),
        make_record(SourceKind.PHC, change_pct=63.0, baseline=19.0, current_value=31.0),
    )
    result = engine.evaluate_community(make_hypothesis(records), records)

    assert result.verdict == VERDICT_PASS
    assert result.status == "REQUIRES_HUMAN_REVIEW"
    assert result.corroborating_source_count == 2
    assert result.requires_human_review is True


def test_four_sources_reach_high_severity(engine):
    records = tuple(
        make_record(kind)
        for kind in (
            SourceKind.CHW,
            SourceKind.PHC,
            SourceKind.PHARMACY,
            SourceKind.SCHOOL,
        )
    )
    result = engine.evaluate_community(make_hypothesis(records), records)

    assert result.verdict == VERDICT_PASS
    assert result.severity == "HIGH"


# ---------------------------------------------------------------------------
# Scenario 3 — geographic mismatch
# ---------------------------------------------------------------------------
def test_geographic_mismatch_is_downgraded(engine):
    records = (
        make_record(SourceKind.CHW, cluster="Village Cluster A"),
        make_record(SourceKind.PHARMACY, cluster="Village Cluster B"),
    )
    result = engine.evaluate_community(make_hypothesis(records), records)

    assert result.verdict == VERDICT_DOWNGRADE
    assert not rule(result, "R3").passed
    assert "more than one cluster" in rule(result, "R3").detail


# ---------------------------------------------------------------------------
# Scenario 4 — temporal mismatch
# ---------------------------------------------------------------------------
def test_time_window_mismatch_is_downgraded(engine):
    far_start = WEEK_START + dt.timedelta(days=40)
    records = (
        make_record(SourceKind.CHW),
        make_record(
            SourceKind.PHC,
            period_start=far_start,
            period_end=far_start + dt.timedelta(days=6),
            week_label="2026-W38",
        ),
    )
    result = engine.evaluate_community(make_hypothesis(records), records)

    assert result.verdict == VERDICT_DOWNGRADE
    assert not rule(result, "R4").passed


def test_signals_inside_the_window_satisfy_the_temporal_rule(engine):
    records = (
        make_record(SourceKind.CHW),
        make_record(
            SourceKind.PHC,
            period_start=WEEK_START + dt.timedelta(days=3),
            period_end=WEEK_END + dt.timedelta(days=3),
        ),
    )
    result = engine.evaluate_community(make_hypothesis(records), records)
    assert rule(result, "R4").passed


# ---------------------------------------------------------------------------
# Scenario 5 — poor data quality
# ---------------------------------------------------------------------------
def test_poor_data_quality_downgrades_and_requests_verification(engine):
    records = (
        make_record(SourceKind.CHW, data_quality=DataQuality.POOR),
        make_record(SourceKind.PHC, data_quality=DataQuality.POOR),
    )
    result = engine.evaluate_community(make_hypothesis(records), records)

    assert result.verdict == VERDICT_DOWNGRADE
    assert result.status == "REQUIRES_VERIFICATION"
    assert not rule(result, "R5").passed


def test_partial_quality_still_counts_as_usable(engine):
    records = (
        make_record(SourceKind.CHW, data_quality=DataQuality.PARTIAL),
        make_record(SourceKind.PHC, data_quality=DataQuality.GOOD),
    )
    result = engine.evaluate_community(make_hypothesis(records), records)
    assert rule(result, "R5").passed


# ---------------------------------------------------------------------------
# Scenario 6 — missing data is never treated as zero
# ---------------------------------------------------------------------------
def test_missing_source_is_recorded_as_missing_not_zero(engine):
    records = (
        make_record(SourceKind.CHW),
        make_record(SourceKind.PHC),
        make_record(
            SourceKind.SCHOOL,
            status="NOT_REPORTED",
            is_reported=False,
            is_corroborating=False,
            data_quality=DataQuality.MISSING,
            current_value=None,
            baseline=6.0,
            change_pct=None,
        ),
    )
    result = engine.evaluate_community(make_hypothesis(records), records)

    assert rule(result, "R8").passed
    assert "SCHOOL" in rule(result, "R8").detail
    # The missing source contributed nothing to corroboration.
    assert result.corroborating_source_count == 2


def test_non_reporting_source_carrying_a_value_is_blocked(engine):
    """A 'not submitted' row with a number in it is a data-integrity defect."""

    records = (
        make_record(SourceKind.CHW),
        make_record(SourceKind.PHC),
        make_record(
            SourceKind.SCHOOL,
            status="NOT_REPORTED",
            is_reported=False,
            is_corroborating=False,
            current_value=0.0,
        ),
    )
    result = engine.evaluate_community(make_hypothesis(records), records)

    assert result.verdict == VERDICT_BLOCK
    assert not rule(result, "R8").passed
    assert "never be interpreted as zero" in rule(result, "R8").detail


# ---------------------------------------------------------------------------
# Rule 6 — no automatic outbreak declaration
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "narrative",
    [
        "A confirmed outbreak of dengue is under way in Village Cluster A.",
        "We declare an outbreak in this cluster.",
        "The diagnosis is dengue fever across the cluster.",
        "This is a guaranteed early detection of an epidemic.",
    ],
)
def test_declaratory_narrative_is_blocked(engine, narrative):
    records = (make_record(SourceKind.CHW), make_record(SourceKind.PHC))
    hypothesis = make_hypothesis(records, narrative=narrative)
    result = engine.evaluate_community(hypothesis, records)

    assert result.verdict == VERDICT_BLOCK
    assert not rule(result, "R6").passed
    assert result.confidence == 0.0


def test_non_hypothesis_output_type_is_blocked(engine):
    records = (make_record(SourceKind.CHW), make_record(SourceKind.PHC))
    hypothesis = make_hypothesis(records, kind="outbreak_declaration")
    result = engine.evaluate_community(hypothesis, records)

    assert result.verdict == VERDICT_BLOCK
    assert "not a correlation hypothesis" in rule(result, "R6").detail


# ---------------------------------------------------------------------------
# Rule 7 — human review is never satisfied by the system
# ---------------------------------------------------------------------------
def test_every_verdict_still_requires_human_review(engine):
    for records in (
        (make_record(SourceKind.CHW),),
        (make_record(SourceKind.CHW), make_record(SourceKind.PHC)),
    ):
        result = engine.evaluate_community(make_hypothesis(records), records)
        assert result.requires_human_review is True
        assert rule(result, "R7").code == "R7"


# ---------------------------------------------------------------------------
# Weather is context, not corroboration
# ---------------------------------------------------------------------------
def test_weather_alone_cannot_corroborate(engine):
    records = (
        make_record(SourceKind.CHW),
        make_record(
            SourceKind.WEATHER,
            status="SUPPORTING_CONTEXT",
            is_corroborating=False,
        ),
    )
    result = engine.evaluate_community(make_hypothesis(records), records)

    assert result.corroborating_source_count == 1
    assert result.verdict == VERDICT_DOWNGRADE


# ---------------------------------------------------------------------------
# Adversarial: the engine overrides the model, not the other way round
# ---------------------------------------------------------------------------
def test_engine_escalates_even_when_the_narrative_downplays_it(engine):
    """The LLM said 'no significant concern'. The evidence says otherwise."""

    records = tuple(
        make_record(kind)
        for kind in (
            SourceKind.CHW,
            SourceKind.PHC,
            SourceKind.PHARMACY,
            SourceKind.SCHOOL,
        )
    )
    hypothesis = make_hypothesis(
        records, narrative="No significant concern in this cluster."
    )
    result = engine.evaluate_community(hypothesis, records)

    assert result.verdict == VERDICT_PASS
    assert result.severity == "HIGH"
    assert result.requires_human_review is True


def test_engine_has_no_bypass_parameter(engine):
    """There is no argument, flag or field that skips verification."""

    import inspect

    signature = inspect.signature(engine.evaluate_community)
    assert set(signature.parameters) == {"hypothesis", "records"}


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
def test_identical_evidence_yields_identical_verdict(engine):
    records = tuple(
        make_record(kind)
        for kind in (SourceKind.CHW, SourceKind.PHC, SourceKind.PHARMACY)
    )
    hypothesis = make_hypothesis(records)

    results = [engine.evaluate_community(hypothesis, records) for _ in range(25)]
    first = results[0]
    for other in results[1:]:
        assert other.verdict == first.verdict
        assert other.status == first.status
        assert other.confidence == first.confidence
        assert other.severity == first.severity
        assert [r.to_dict() for r in other.rules] == [
            r.to_dict() for r in first.rules
        ]


def test_confidence_never_reaches_certainty(engine):
    records = tuple(
        make_record(kind)
        for kind in (
            SourceKind.CHW,
            SourceKind.PHC,
            SourceKind.PHARMACY,
            SourceKind.SCHOOL,
            SourceKind.LAB,
        )
    )
    result = engine.evaluate_community(make_hypothesis(records), records)
    assert 0.0 < result.confidence <= 0.95


def test_contradictory_cross_level_lowers_confidence(engine):
    records = (make_record(SourceKind.CHW), make_record(SourceKind.PHC))
    consistent = engine.evaluate_community(
        make_hypothesis(records, cross_level_verdict="CONSISTENT"), records
    )
    contradictory = engine.evaluate_community(
        make_hypothesis(records, cross_level_verdict="CONTRADICTORY"), records
    )
    assert contradictory.confidence < consistent.confidence


# ---------------------------------------------------------------------------
# Rule 9 — individual red flags
# ---------------------------------------------------------------------------
def test_red_flag_forces_escalation_over_a_reassuring_model(engine):
    case = IndividualCase(
        symptoms=("fever", "neck_stiffness"),
        duration_days=2,
        model_triage_level="ROUTINE",
    )
    result, triggered = engine.evaluate_individual(case)

    assert result.verdict == VERDICT_BLOCK
    assert result.status == "ESCALATION_FORCED"
    assert any(f["code"] == "RF_FEVER_NECK_STIFFNESS" for f in triggered)
    assert "cannot be suppressed" in result.rules[0].detail


@pytest.mark.parametrize(
    "case,expected_code",
    [
        (IndividualCase(symptoms=("fever",), spo2=88), "RF_LOW_SPO2"),
        (IndividualCase(symptoms=("cough",), respiratory_rate=34), "RF_HIGH_RESP_RATE"),
        (IndividualCase(symptoms=("fatigue",), systolic_bp=85), "RF_LOW_BP"),
        (IndividualCase(symptoms=("fever",), temperature_c=40.2), "RF_VERY_HIGH_FEVER"),
        (
            IndividualCase(symptoms=("chest_pain", "breathlessness")),
            "RF_CHEST_PAIN_BREATHLESSNESS",
        ),
        (IndividualCase(symptoms=("seizure",)), "RF_SEIZURE"),
        (IndividualCase(symptoms=("fever",), age_months=1), "RF_YOUNG_INFANT_FEVER"),
        (
            IndividualCase(symptoms=("fever",), duration_days=9),
            "RF_PROLONGED_FEVER",
        ),
    ],
)
def test_each_red_flag_fires(engine, case, expected_code):
    result, triggered = engine.evaluate_individual(case)
    assert result.verdict == VERDICT_BLOCK
    assert any(f["code"] == expected_code for f in triggered)


def test_ordinary_presentation_has_no_red_flag(engine):
    case = IndividualCase(
        symptoms=("fever", "headache"), duration_days=3, temperature_c=38.4
    )
    result, triggered = engine.evaluate_individual(case)

    assert triggered == []
    assert result.verdict == VERDICT_PASS
    assert result.requires_human_review is True
