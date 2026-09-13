"""High-signal alert + officer recommendation — backend regression tests.

This feature adds NO new detection algorithm: it only exposes the
existing, unmodified `simulation.orchestrator._classify_trend()` result
(`intelligence.timeline[].status`, already SIGNAL_DETECTED/INCREASING/
STABLE/NORMAL since Phase 4/5) and the existing, unmodified Phase 9/10
`simulation.investigation.suggested_decision()` — reused verbatim, now
also surfaced through `.../intelligence/`, `.../replay/`, and
`.../what-if/` (a new `suggested_next_step` key on each, additive to the
already-frozen Phase 5/6/7 payload shapes).

Reuses the Phase 4 scenario-building helpers and village/officer fixtures
from `test_simulation.py`.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from simulation.models import SafetyGateResult
from simulation.investigation import suggested_decision

from tests.test_simulation import (
    SESSIONS_URL,
    _advance,
    _build_pipeline_scenario,
    _operational_counts,
    _week,
    officer_a_api,  # noqa: F401 - reused fixture
    officer_b_api,  # noqa: F401 - reused fixture
    village_b,  # noqa: F401 - reused fixture
)

User = get_user_model()
pytestmark = pytest.mark.django_db

# The exact same escalating week data used throughout this project's Phase
# 8/9/10 test suites — week 4 genuinely reaches SIGNAL_DETECTED under the
# real, unmodified `_classify_trend` thresholds (9 vs 5 = +80% and +4,
# both above the 60%/3 SIGNAL_DETECTED thresholds).
_DEFAULT_WEEKS = [
    _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
    _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True)}),
    _week(3, {"FEVER": 5}, {"CHW": (5, True), "PHC": (9, True)}),
    _week(4, {"FEVER": 9}, {"CHW": (9, True), "PHC": (14, True)}),
]


def _intelligence_url(session_id: int) -> str:
    return f"{SESSIONS_URL}{session_id}/intelligence/"


def _replay_url(session_id: int, week: int) -> str:
    return f"{SESSIONS_URL}{session_id}/replay/?week={week}"


def _what_if_url(session_id: int) -> str:
    return f"{SESSIONS_URL}{session_id}/what-if/"


def _start_and_advance(api_client, scenario, times: int) -> int:
    response = api_client.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    session_id = response.data["session_id"]
    for _ in range(times):
        _advance(api_client, session_id)
    return session_id


# ===========================================================================
# A. Detection is derived from the existing, unmodified trend classifier
# ===========================================================================
def test_signal_detected_week_has_expected_timeline_and_recommendation(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "ALERT-DETECTED", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)

    response = officer_a_api.get(_intelligence_url(session_id))
    assert response.status_code == 200

    timeline = response.data["timeline"]
    assert timeline[-1]["week"] == 4
    assert timeline[-1]["status"] == "SIGNAL_DETECTED"
    assert timeline[-1]["value"] == 9
    assert timeline[-2]["value"] == 5  # the exact "previous" value the trend was classified against

    assert response.data["explanation"]["evidence_strength"] == "STRONG"
    assert response.data["safety"]["gate_result"] == "PASS"
    assert response.data["suggested_next_step"] == "CONDUCT_FIELD_VERIFICATION"


def test_stable_community_never_reaches_signal_detected(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "ALERT-STABLE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(3, {"FEVER": 3}, {"CHW": (3, True), "PHC": (5, True)}),
            _week(4, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
        ],
    )
    session_id = _start_and_advance(officer_a_api, scenario, 3)

    response = officer_a_api.get(_intelligence_url(session_id))
    statuses = [point["status"] for point in response.data["timeline"]]
    assert "SIGNAL_DETECTED" not in statuses


def test_missing_source_does_not_force_a_false_signal_detected(officer_a_api, village):
    """Missing data affects evidence/completeness, never the trend
    classification itself — the primary signal's category total (FEVER
    here) is unaffected by whether a SOURCE reported this week."""

    scenario = _build_pipeline_scenario(
        village,
        "ALERT-MISSING",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 2}, {"CHW": (2, True), "PHC": (None, False)}),
            _week(3, {"FEVER": 2}, {"CHW": (2, True), "PHC": (None, False)}),
        ],
    )
    session_id = _start_and_advance(officer_a_api, scenario, 2)

    response = officer_a_api.get(_intelligence_url(session_id))
    assert response.data["timeline"][-1]["status"] != "SIGNAL_DETECTED"
    assert response.data["data_quality"]["completeness_pct"] < 100


# ===========================================================================
# B. Recommendation varies with evidence, never a generic constant
# ===========================================================================
def test_recommendation_changes_across_the_real_progression(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "ALERT-PROGRESSION", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 0)

    seen = []
    for _ in range(3):
        response = _advance(officer_a_api, session_id)
        intelligence = officer_a_api.get(_intelligence_url(session_id)).data
        seen.append((intelligence["timeline"][-1]["status"], intelligence["suggested_next_step"]))

    assert seen == [
        ("STABLE", "CLOSE_AS_INSUFFICIENT_EVIDENCE"),
        ("INCREASING", "CONDUCT_FIELD_VERIFICATION"),
        ("SIGNAL_DETECTED", "CONDUCT_FIELD_VERIFICATION"),
    ]
    # Not a single constant across the whole progression.
    assert len({step for _status, step in seen}) > 1


# ===========================================================================
# C. Safety overrides the recommendation
# ===========================================================================
def test_safety_block_yields_no_actionable_recommendation(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "ALERT-BLOCK", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)

    with patch(
        "simulation.safety.engine.SafetyEngine.evaluate_latest",
        return_value={
            "checks": [],
            "gate_result": SafetyGateResult.BLOCK,
            "human_review_required": True,
            "evidence_strength": "WEAK",
        },
    ):
        response = officer_a_api.get(_intelligence_url(session_id))

    assert response.data["safety"]["gate_result"] == "BLOCK"
    assert response.data["suggested_next_step"] == ""


# ===========================================================================
# D. Replay shows the persisted recommendation, never a live recomputation
# ===========================================================================
def test_replay_matches_live_intelligence_for_the_signal_detected_week(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "ALERT-REPLAY", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)

    live = officer_a_api.get(_intelligence_url(session_id)).data
    replayed = officer_a_api.get(_replay_url(session_id, 4)).data["intelligence"]

    assert live["timeline"][-1]["status"] == "SIGNAL_DETECTED"
    assert replayed["timeline"][-1]["status"] == "SIGNAL_DETECTED"
    assert replayed["suggested_next_step"] == live["suggested_next_step"]


def test_replay_of_an_earlier_stable_week_shows_no_detection(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "ALERT-REPLAY-EARLY", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)

    replayed_week2 = officer_a_api.get(_replay_url(session_id, 2)).data["intelligence"]
    assert replayed_week2["timeline"][-1]["status"] == "STABLE"


# ===========================================================================
# E. What-If: real, tested architectural boundary — trend/status can never
# differ from the original (category totals are never overridden), only
# correlation/evidence/safety/recommendation can.
# ===========================================================================
def test_what_if_signal_detected_status_always_matches_original_never_invents_one(
    officer_a_api, village
):
    scenario = _build_pipeline_scenario(village, "ALERT-WHATIF-TREND", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)  # week 4, SIGNAL_DETECTED

    original_intelligence = officer_a_api.get(_intelligence_url(session_id)).data
    original_status = original_intelligence["timeline"][-1]["status"]

    result = officer_a_api.post(
        _what_if_url(session_id), {"overrides": {"CHW": 40}}, format="json"
    ).data

    assert result["hypothetical"]["trend"] == original_status == "SIGNAL_DETECTED"


def test_what_if_conflict_downgrades_evidence_and_changes_recommendation_without_touching_original(
    officer_a_api, village
):
    scenario = _build_pipeline_scenario(village, "ALERT-WHATIF-CONFLICT", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)  # week 4

    before = officer_a_api.get(_intelligence_url(session_id)).data
    assert before["explanation"]["evidence_strength"] == "STRONG"
    assert before["suggested_next_step"] == "CONDUCT_FIELD_VERIFICATION"

    result = officer_a_api.post(
        _what_if_url(session_id), {"overrides": {"PHC": 3}}, format="json"
    ).data

    assert result["hypothetical"]["trend"] == "SIGNAL_DETECTED"
    assert result["hypothetical"]["safety"]["evidence_strength"] == "MODERATE"
    assert result["hypothetical"]["suggested_next_step"] == "VERIFY_WITH_PHC"

    # Original session state — re-fetched, not assumed — is byte-for-byte
    # unchanged (task §22/§45).
    after = officer_a_api.get(_intelligence_url(session_id)).data
    assert after == before


# ===========================================================================
# F. Isolation
# ===========================================================================
def test_signal_detected_week_never_touches_operational_tables(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "ALERT-OPS-ISOLATION", _DEFAULT_WEEKS)
    before = _operational_counts()

    session_id = _start_and_advance(officer_a_api, scenario, 3)
    officer_a_api.get(_intelligence_url(session_id))
    officer_a_api.get(_replay_url(session_id, 4))
    officer_a_api.post(_what_if_url(session_id), {"overrides": {"PHC": 3}}, format="json")

    after = _operational_counts()
    assert before == after


def test_cross_village_officer_cannot_read_signal_detected_intelligence(
    officer_a_api, officer_b_api, village
):
    scenario = _build_pipeline_scenario(village, "ALERT-XVILLAGE", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)

    response = officer_b_api.get(_intelligence_url(session_id))
    assert response.status_code == 403


# ===========================================================================
# G. suggested_next_step exposure matches the underlying, unmodified
# Phase 9/10 function directly (never a second implementation).
# ===========================================================================
def test_exposed_suggested_next_step_matches_direct_function_call(officer_a_api, village):
    scenario = _build_pipeline_scenario(village, "ALERT-DIRECT-CALL", _DEFAULT_WEEKS)
    session_id = _start_and_advance(officer_a_api, scenario, 3)

    response = officer_a_api.get(_intelligence_url(session_id))
    intelligence_only = {
        key: response.data[key]
        for key in ("timeline", "constellation", "source_fusion", "data_quality", "explanation")
    }
    safety_only = response.data["safety"]

    assert response.data["suggested_next_step"] == suggested_decision(intelligence_only, safety_only)
