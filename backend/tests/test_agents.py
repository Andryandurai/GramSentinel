"""Agent behaviour and, importantly, agent *interaction*.

The claim under test is that this is genuinely multi-agent: distinct agents,
each with a narrow job, passing structured records to each other — not one
model call wearing several labels.
"""

from __future__ import annotations

import pytest

from agents.cross_level import CrossLevelIntelligenceAgent
from agents.gramsentinel import (
    CHWSignalAgent,
    ClusterDetectionAgent,
    LabEvidenceAgent,
    PharmacySignalAgent,
    SchoolSignalAgent,
    VillageTrendAgent,
    WeatherSignalAgent,
)
from agents.orchestration import RuralCareOrchestrator
from agents.ruralcare import PatientListenerAgent, SymptomAnalysisAgent
from core.constants import DataQuality, SignalCategory, SourceKind

from .conftest import WEEK_LABEL

pytestmark = pytest.mark.django_db

BASE_PAYLOAD = {
    "category": SignalCategory.FEVER,
    "village_code": "KVL",
    "village_name": "Kovilur",
    "cluster": "Village Cluster A",
    "week_label": WEEK_LABEL,
    "period_start": "2026-08-03",
    "period_end": "2026-08-09",
    "data_quality": DataQuality.GOOD,
}


# ---------------------------------------------------------------------------
# RuralCare individual agents
# ---------------------------------------------------------------------------
def test_listener_normalises_free_text_and_flags_gaps():
    result = PatientListenerAgent().run(
        {
            "symptoms": ["Fever", "loose motion"],
            "raw_symptom_text": "also complains of headache",
            "duration_days": 3,
            "temperature_c": 38.4,
        }
    )
    encounter = result.output["encounter"]

    assert "fever" in encounter["symptoms"]
    assert "diarrhoea" in encounter["symptoms"]  # 'loose motion' synonym
    assert "headache" in encounter["symptoms"]  # picked out of free text
    assert "spo2" in result.output["completeness"]["missing_vitals"]


def test_listener_keeps_unrecognised_entries_visible():
    result = PatientListenerAgent().run(
        {"symptoms": ["fever", "qwertyuiop"], "duration_days": 1}
    )
    assert result.output["encounter"]["unrecognised_entries"] == ["qwertyuiop"]


def test_symptom_agent_routes_to_the_right_community_category():
    listener = PatientListenerAgent().run(
        {"symptoms": ["diarrhoea", "vomiting"], "duration_days": 2}
    )
    analysis = SymptomAnalysisAgent().run(listener.output)

    assert analysis.output["signal_category"] == SignalCategory.DIARRHOEAL
    assert analysis.output["primary_syndrome"] == "gastrointestinal"


def test_listener_output_summary_carries_no_identifiers():
    """Audit rows must not become a back door around the privacy boundary."""

    agent = PatientListenerAgent()
    summary = agent.summarise_input(
        {
            "symptoms": ["fever"],
            "patient_code": "KVL-P-001",
            "display_name": "Real Name",
            "raw_symptom_text": "some free text",
        }
    )
    flat = str(summary)
    assert "KVL-P-001" not in flat
    assert "Real Name" not in flat
    assert "some free text" not in flat


# ---------------------------------------------------------------------------
# The RuralCare chain
# ---------------------------------------------------------------------------
def test_chain_produces_concerning_for_the_demo_case():
    result = RuralCareOrchestrator().run(
        {"symptoms": ["fever", "headache"], "duration_days": 3, "temperature_c": 38.4}
    )

    assert result["ok"] is True
    assert result["triage_level"] == "CONCERNING"
    assert result["signal_category"] == SignalCategory.FEVER
    assert result["red_flags"] == []
    assert "professional" in result["referral_recommendation"].lower()


def test_chain_records_five_distinct_agents_in_order():
    result = RuralCareOrchestrator().run(
        {"symptoms": ["fever"], "duration_days": 2}
    )
    names = [entry["agent"] for entry in result["agent_trace"]]

    assert names == [
        "PatientListenerAgent",
        "SymptomAnalysisAgent",
        "RiskTriageAgent",
        "ReferralAgent",
        "IndividualSafetyAgent",
    ]
    assert len(set(names)) == 5


def test_chain_output_of_one_agent_is_the_input_of_the_next():
    result = RuralCareOrchestrator().run(
        {"symptoms": ["fever", "cough"], "duration_days": 4}
    )
    trace = {entry["agent"]: entry for entry in result["agent_trace"]}

    listener_symptoms = trace["PatientListenerAgent"]["output"]["encounter"]["symptoms"]
    symptom_input = trace["SymptomAnalysisAgent"]["input_summary"]["symptom_codes"]
    assert symptom_input == listener_symptoms

    triage_level = trace["RiskTriageAgent"]["output"]["triage_level"]
    referral_input = trace["ReferralAgent"]["input_summary"]["triage_level"]
    assert referral_input == triage_level


def test_safety_agent_overrides_the_triage_agent():
    result = RuralCareOrchestrator().run(
        {"symptoms": ["fever", "neck_stiffness"], "duration_days": 1}
    )

    assert result["triage_level"] == "URGENT"
    assert result["escalation_forced"] is True
    assert result["safety_status"] == "ESCALATION_FORCED"


def test_safety_agent_never_lowers_a_level():
    """Red flags raise urgency; nothing in the chain walks it back down."""

    result = RuralCareOrchestrator().run(
        {
            "symptoms": ["fever", "breathlessness", "chest_pain"],
            "duration_days": 5,
            "spo2": 89,
        }
    )
    assert result["triage_level"] == "URGENT"


# ---------------------------------------------------------------------------
# GramSentinel signal agents
# ---------------------------------------------------------------------------
def test_chw_agent_flags_a_rise_against_its_own_baseline():
    card = CHWSignalAgent().run(
        {**BASE_PAYLOAD, "value": 14, "baseline": 5, "is_reported": True}
    ).output["evidence_card"]

    assert card["status"] == "ANOMALY_DETECTED"
    assert card["change_pct"] == 180.0
    assert card["is_corroborating"] is True


def test_signal_agent_treats_a_non_submission_as_missing_not_zero():
    card = SchoolSignalAgent().run(
        {**BASE_PAYLOAD, "value": None, "baseline": 6.0, "is_reported": False}
    ).output["evidence_card"]

    assert card["status"] == "NOT_REPORTED"
    assert card["current_value"] is None
    assert card["is_corroborating"] is False
    assert card["data_quality"] == DataQuality.MISSING


def test_school_agent_fires_on_percentage_point_rise():
    """6% -> 12% is only +100% relative but +6 points, which matters."""

    card = SchoolSignalAgent().run(
        {**BASE_PAYLOAD, "value": 12.0, "baseline": 6.0, "is_reported": True}
    ).output["evidence_card"]
    assert card["status"] == "ANOMALY_DETECTED"


def test_weather_is_context_and_never_corroborating():
    card = WeatherSignalAgent().run(
        {**BASE_PAYLOAD, "value": 240, "baseline": 110, "is_reported": True}
    ).output["evidence_card"]

    assert card["status"] == "SUPPORTING_CONTEXT"
    assert card["is_corroborating"] is False


def test_lab_agent_uses_an_absolute_floor_not_a_percentage():
    card = LabEvidenceAgent().run(
        {**BASE_PAYLOAD, "value": 1, "baseline": 0, "is_reported": True}
    ).output["evidence_card"]

    assert card["status"] == "CORROBORATING"
    assert card["is_corroborating"] is True


def test_agent_without_a_baseline_reports_insufficient_data():
    card = PharmacySignalAgent().run(
        {**BASE_PAYLOAD, "value": 310, "baseline": None, "is_reported": True}
    ).output["evidence_card"]

    assert card["status"] == "INSUFFICIENT_DATA"
    assert card["is_corroborating"] is False


def test_signal_agents_are_blind_to_each_other():
    """Each agent's payload contains only its own source. That is what makes
    later corroboration meaningful rather than circular."""

    agent = CHWSignalAgent()
    payload = {**BASE_PAYLOAD, "value": 14, "baseline": 5}
    output = agent.run(payload).output["evidence_card"]

    assert output["source_kind"] == SourceKind.CHW
    assert "evidence_cards" not in payload
    assert set(output) & {"other_sources", "peer_findings"} == set()


# ---------------------------------------------------------------------------
# Trend and cluster assembly
# ---------------------------------------------------------------------------
def _cards(*specs):
    made = []
    for kind, value, baseline, agent_cls in specs:
        made.append(
            agent_cls().run(
                {**BASE_PAYLOAD, "value": value, "baseline": baseline}
            ).output["evidence_card"]
        )
    return made


def test_village_trend_summarises_multiple_rising_sources():
    cards = _cards(
        (SourceKind.CHW, 14, 5, CHWSignalAgent),
        (SourceKind.PHARMACY, 310, 200, PharmacySignalAgent),
        (SourceKind.WEATHER, 240, 110, WeatherSignalAgent),
    )
    trend = VillageTrendAgent().run(
        {"evidence_cards": cards, "village_code": "KVL", "week_label": WEEK_LABEL}
    ).output

    assert trend["trajectory"] == "MULTIPLE_SOURCES_RISING"
    assert len(trend["corroborating_sources"]) == 2
    assert SourceKind.WEATHER in trend["context_sources"]


def test_cluster_agent_emits_only_a_correlation_hypothesis():
    cards = _cards(
        (SourceKind.CHW, 14, 5, CHWSignalAgent),
        (SourceKind.PHARMACY, 310, 200, PharmacySignalAgent),
    )
    candidate = ClusterDetectionAgent().run(
        {
            "evidence_cards": cards,
            "village_trend": {},
            "cluster": "Village Cluster A",
            "category": SignalCategory.FEVER,
            "week_label": WEEK_LABEL,
        }
    ).output["candidate_pattern"]

    assert candidate["kind"] == "correlation_hypothesis"
    assert candidate["detected"] is True
    assert candidate["corroborating_count"] == 2

    lowered = candidate["narrative"].lower()
    for banned in ("outbreak", "diagnos", "confirmed case"):
        assert banned not in lowered


def test_cluster_agent_reports_nothing_when_no_source_moved():
    cards = _cards(
        (SourceKind.CHW, 5, 5, CHWSignalAgent),
        (SourceKind.PHARMACY, 201, 200, PharmacySignalAgent),
    )
    candidate = ClusterDetectionAgent().run(
        {
            "evidence_cards": cards,
            "village_trend": {},
            "cluster": "Village Cluster A",
            "category": SignalCategory.FEVER,
            "week_label": WEEK_LABEL,
        }
    ).output["candidate_pattern"]

    assert candidate["detected"] is False
    assert candidate["corroborating_count"] == 0


# ---------------------------------------------------------------------------
# Cross-Level Intelligence
# ---------------------------------------------------------------------------
def _cross(counts, baselines, *, detected=True, week=WEEK_LABEL):
    return CrossLevelIntelligenceAgent().run(
        {
            "individual_snapshot": {
                "village_code": "KVL",
                "week_label": week,
                "counts_by_category": counts,
                "baselines_by_category": baselines,
            },
            "candidate_pattern": {
                "detected": detected,
                "cluster": "Village Cluster A",
                "category": SignalCategory.FEVER,
                "week_label": WEEK_LABEL,
                "corroborating_count": 4,
            },
            "village_cluster": "Village Cluster A",
        }
    ).output["cross_level"]


def test_cross_level_reports_consistency_when_both_layers_agree():
    result = _cross({SignalCategory.FEVER: 7}, {SignalCategory.FEVER: 2})

    assert result["verdict"] == "CONSISTENT"
    assert "potentially consistent pattern" in result["statement"]
    assert result["alignment"] == {"category": True, "geography": True, "time": True}


def test_cross_level_reports_contradiction_when_individual_layer_is_flat():
    result = _cross({SignalCategory.FEVER: 2}, {SignalCategory.FEVER: 2})

    assert result["verdict"] == "CONTRADICTORY"
    assert "lowers confidence" in result["statement"]


def test_cross_level_is_silent_when_the_individual_layer_has_nothing():
    result = _cross({}, {})
    assert result["verdict"] == "SILENT"


def test_cross_level_is_silent_on_a_time_mismatch():
    result = _cross(
        {SignalCategory.FEVER: 7}, {SignalCategory.FEVER: 2}, week="2026-W40"
    )
    assert result["verdict"] == "SILENT"
    assert "time window" in result["statement"]


def test_cross_level_receives_only_aggregated_counts():
    agent = CrossLevelIntelligenceAgent()
    summary = agent.summarise_input(
        {
            "individual_snapshot": {
                "village_code": "KVL",
                "week_label": WEEK_LABEL,
                "counts_by_category": {SignalCategory.FEVER: 7},
            }
        }
    )
    assert summary["input_type"] == "aggregated_counts_only"
    assert "patient" not in str(summary).lower()
