"""Phase 7 — Signal Replay + What-If Simulation tests.

Reuses the Phase 4/5/6 scenario-building helpers and village fixtures from
`test_simulation.py` (`_build_pipeline_scenario`/`_week`/`_advance`/
`village_b`/`officer_a_api`/`officer_b_api`/`_operational_counts`) rather
than redefining them. `village`, `officer`, `worker`, `api` come from the
shared `tests/conftest.py`.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from alerts.models import Alert, Feedback, Investigation
from simulation.models import (
    SimulationAgentRun,
    SimulationResult,
    SimulationSafetyCheck,
    SimulationSession,
    SimulationSourceSignal,
)
from simulation.replay import ReplayWeekOutOfRange, build_replay_state
from simulation.services import SimulationEngine, SimulationVillageMismatch
from simulation.what_if import WhatIfEngine, WhatIfValidationError

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


def _replay_url(session_id: int, week: int | None = None) -> str:
    url = f"{SESSIONS_URL}{session_id}/replay/"
    return f"{url}?week={week}" if week is not None else url


def _what_if_url(session_id: int) -> str:
    return f"{SESSIONS_URL}{session_id}/what-if/"


def _start_and_advance(api_client, scenario_id: int, times: int):
    response = api_client.post(SESSIONS_URL, {"scenario_id": scenario_id}, format="json")
    session_id = response.data["session_id"]
    for _ in range(times):
        response = _advance(api_client, session_id)
    return session_id, response


def _current_officer() -> User:
    return User.objects.get(username="officer.simulation-test")


# ===========================================================================
# REPLAY
# ===========================================================================

# 1. Replay position starts correctly
def test_replay_starts_at_week_one(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "REPLAY-START",
        [_week(1, {"FEVER": 2}, {"CHW": (2, True)})],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    session_id = start.data["session_id"]

    response = officer_a_api.get(_replay_url(session_id))

    assert response.status_code == 200
    assert response.data["week"] == 1
    assert response.data["min_week"] == 1
    assert response.data["max_week"] == 1
    assert response.data["is_first"] is True
    assert response.data["is_last"] is True


# 2. Next increments position (a later ?week= shows the later persisted week)
def test_replay_next_shows_next_persisted_week(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "REPLAY-NEXT",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
            _week(3, {"FEVER": 5}, {"CHW": (5, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 2)

    week1 = officer_a_api.get(_replay_url(session_id, 1)).data
    week2 = officer_a_api.get(_replay_url(session_id, 2)).data

    assert week1["intelligence"]["timeline"][-1]["value"] == 2
    assert week2["intelligence"]["timeline"][-1]["value"] == 3


# 3. Previous decrements position
def test_replay_previous_shows_earlier_persisted_week(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "REPLAY-PREVIOUS",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
            _week(3, {"FEVER": 5}, {"CHW": (5, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 2)

    latest = officer_a_api.get(_replay_url(session_id)).data
    assert latest["week"] == 3

    previous = officer_a_api.get(_replay_url(session_id, latest["week"] - 1)).data
    assert previous["week"] == 2


# 4. Reset returns to initial position
def test_replay_reset_returns_to_minimum_week(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "REPLAY-RESET",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
            _week(3, {"FEVER": 5}, {"CHW": (5, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 2)
    bounds = officer_a_api.get(_replay_url(session_id)).data
    reset = officer_a_api.get(_replay_url(session_id, bounds["min_week"])).data
    assert reset["week"] == bounds["min_week"] == 1
    assert reset["is_first"] is True


# 5. Cannot move beyond maximum computed week
def test_replay_cannot_move_beyond_maximum(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "REPLAY-BEYOND-MAX",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)  # at week 2

    response = officer_a_api.get(_replay_url(session_id, 3))
    assert response.status_code == 400


# 6. Cannot move below minimum week
def test_replay_cannot_move_below_minimum(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "REPLAY-BELOW-MIN",
        [_week(1, {"FEVER": 2}, {"CHW": (2, True)})],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    session_id = start.data["session_id"]

    response = officer_a_api.get(_replay_url(session_id, 0))
    assert response.status_code == 400


# 7. Future/unrevealed week is inaccessible even though it exists in the template
def test_replay_future_unrevealed_week_is_inaccessible(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "REPLAY-FUTURE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
            _week(3, {"FEVER": 5}, {"CHW": (5, True)}),
            _week(4, {"FEVER": 8}, {"CHW": (8, True)}),
        ],
    )
    # Advance only to week 2 — weeks 3-4 are seeded but not yet revealed.
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    response = officer_a_api.get(_replay_url(session_id, 3))
    assert response.status_code == 400
    assert "timeline" not in response.data


# 8-10. Replay never creates AgentRun/SafetyCheck/Result rows
def test_replay_creates_no_new_rows(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "REPLAY-NO-NEW-ROWS",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
            _week(3, {"FEVER": 5}, {"CHW": (5, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 2)

    before_runs = SimulationAgentRun.objects.count()
    before_checks = SimulationSafetyCheck.objects.count()
    before_results = SimulationResult.objects.count()

    officer_a_api.get(_replay_url(session_id, 1))
    officer_a_api.get(_replay_url(session_id, 2))
    officer_a_api.get(_replay_url(session_id, 3))
    officer_a_api.get(_replay_url(session_id, 1))  # revisit

    assert SimulationAgentRun.objects.count() == before_runs
    assert SimulationSafetyCheck.objects.count() == before_checks
    assert SimulationResult.objects.count() == before_results


# 11. Replay does not modify operational data
def test_replay_leaves_operational_data_untouched(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "REPLAY-OPERATIONAL-ISOLATION",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)
    before = _operational_counts()

    officer_a_api.get(_replay_url(session_id, 1))
    officer_a_api.get(_replay_url(session_id, 2))

    assert _operational_counts() == before


# 12. Same replay position returns deterministic persisted output
def test_replay_same_position_is_deterministic(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "REPLAY-DETERMINISTIC",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 4}, {"CHW": (4, True), "PHC": (1, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    first = officer_a_api.get(_replay_url(session_id, 2)).data
    second = officer_a_api.get(_replay_url(session_id, 2)).data

    assert first == second


# 13. Cross-village replay returns 403
def test_replay_cross_village_returns_403(officer_a_api, officer_b_api, village_b):
    scenario = _build_pipeline_scenario(
        village_b,
        "REPLAY-CROSS-VILLAGE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_b_api, scenario.id, 1)

    response = officer_a_api.get(_replay_url(session_id))
    assert response.status_code == 403
    assert officer_b_api.get(_replay_url(session_id)).status_code == 200


def test_replay_direct_engine_rejects_out_of_range_with_typed_exception(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "REPLAY-DIRECT",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)
    session = SimulationSession.objects.get(id=session_id)

    with pytest.raises(ReplayWeekOutOfRange):
        build_replay_state(session, week=5)


# ===========================================================================
# WHAT-IF
# ===========================================================================

# 14. Valid synthetic override succeeds
def test_what_if_valid_override_succeeds(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-VALID",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    response = officer_a_api.post(
        _what_if_url(session_id), {"overrides": {"CHW": 20}}, format="json"
    )

    assert response.status_code == 200
    assert response.data["is_hypothetical"] is True
    assert response.data["hypothetical"]["sources"]["CHW"]["value"] == 20
    assert response.data["original"]["sources"]["CHW"]["value"] == 3
    assert response.data["changed_sources"] == ["CHW"]


# 15. Invalid source rejected
def test_what_if_unknown_source_rejected(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-UNKNOWN-SOURCE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    response = officer_a_api.post(
        _what_if_url(session_id), {"overrides": {"PHARMACY": 10}}, format="json"
    )
    assert response.status_code == 400


# 16. Negative value rejected
def test_what_if_negative_value_rejected(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-NEGATIVE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    response = officer_a_api.post(
        _what_if_url(session_id), {"overrides": {"CHW": -5}}, format="json"
    )
    assert response.status_code == 400


# 17. Malformed value rejected
def test_what_if_malformed_value_rejected(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-MALFORMED",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    response = officer_a_api.post(
        _what_if_url(session_id), {"overrides": {"CHW": "a lot"}}, format="json"
    )
    assert response.status_code == 400


# 18. Unauthorized village rejected
def test_what_if_unauthorized_village_rejected(officer_a_api, officer_b_api, village_b):
    scenario = _build_pipeline_scenario(
        village_b,
        "WHATIF-CROSS-VILLAGE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_b_api, scenario.id, 1)

    response = officer_a_api.post(
        _what_if_url(session_id), {"overrides": {"CHW": 20}}, format="json"
    )
    assert response.status_code == 403


# 19. Future/unrevealed week rejected — What-If has no way to request one:
# it always targets `session.replay_position`, even if a client tries to
# smuggle a different week into the request body.
def test_what_if_always_targets_current_week_never_a_requested_future_one(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-NO-FUTURE-WEEK",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
            _week(3, {"FEVER": 5}, {"CHW": (5, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)  # at week 2

    response = officer_a_api.post(
        _what_if_url(session_id),
        {"overrides": {"CHW": 20}, "week": 3},  # week 3 not yet revealed
        format="json",
    )
    assert response.status_code == 200
    assert response.data["week"] == 2  # the extra "week" field is ignored


def test_what_if_on_the_first_week_has_no_persisted_original_and_forces_normal_trend(
    officer_a_api, village
):
    """Regression test for a real support report (not a bug — documents
    the actual, correct deterministic behaviour): `start()` never runs the
    pipeline (Phase 3/4 boundary — see `services.py`'s own module
    docstring), so week 1 has no `SimulationResult` row for `WhatIfEngine
    ._persisted_safety_for_week` to read back, and `_classify_trend`
    always returns NORMAL when `previous is None` (no prior week exists to
    compare against) — regardless of how extreme the What-If override is.
    Both are correct, existing Phase 3/4 semantics; this test only pins
    them down so a future change can't silently make week-1 What-If look
    broken in a NEW way."""

    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-WEEK-ONE",
        [_week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)})],
    )
    response = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    session_id = response.data["session_id"]
    assert response.data["week"] == 1
    assert response.data["agent_runs"] == []  # start() never runs the pipeline

    # A drastic override — the trend must still be NORMAL: there is no
    # previous week for `_classify_trend` to compare it against.
    result = officer_a_api.post(
        _what_if_url(session_id), {"overrides": {"PHC": 26}}, format="json"
    ).data

    assert result["changed_sources"] == ["PHC"]
    assert result["original"]["gate_result"] is None
    assert result["original"]["evidence_strength"] is None
    assert result["hypothetical"]["trend"] == "NORMAL"
    assert result["hypothetical"]["safety"]["evidence_strength"] == "WEAK"

    # And the real week-1 row is still exactly what it was before — seeded
    # on the scenario's template session, which every real session (this
    # one included) only ever reads from, never its own `SimulationEvent`
    # rows (Phase 3 architecture — `get_template_session`).
    assert SimulationResult.objects.filter(session_id=session_id).count() == 0
    assert (
        SimulationSourceSignal.objects.get(
            event__session__scenario_id=scenario.id,
            event__session__health_officer__isnull=True,
            event__week_number=1,
            source_type="PHC",
        ).value
        == 5
    )


# 20-24. Original rows are byte-for-byte unchanged
def test_what_if_leaves_original_rows_unchanged(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-ORIGINAL-UNCHANGED",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)
    session = SimulationSession.objects.get(id=session_id)

    before_session = SimulationSession.objects.get(id=session_id)
    before_signal_values = list(
        SimulationSourceSignal.objects.filter(
            event__session__scenario=scenario, event__session__health_officer__isnull=True
        ).values("source_type", "value", "reported")
    )
    before_agent_runs = list(
        SimulationAgentRun.objects.filter(session=session).values(
            "agent_name", "status", "output", "duration_ms"
        )
    )
    before_safety_checks = list(
        SimulationSafetyCheck.objects.filter(session=session).values("rule_name", "result", "reason")
    )
    before_results = list(
        SimulationResult.objects.filter(session=session).values("gate_result", "evidence_strength")
    )

    officer_a_api.post(_what_if_url(session_id), {"overrides": {"CHW": 999}}, format="json")

    after_session = SimulationSession.objects.get(id=session_id)
    assert before_session.replay_position == after_session.replay_position
    assert before_session.status == after_session.status

    after_signal_values = list(
        SimulationSourceSignal.objects.filter(
            event__session__scenario=scenario, event__session__health_officer__isnull=True
        ).values("source_type", "value", "reported")
    )
    assert before_signal_values == after_signal_values  # 21

    after_agent_runs = list(
        SimulationAgentRun.objects.filter(session=session).values(
            "agent_name", "status", "output", "duration_ms"
        )
    )
    assert before_agent_runs == after_agent_runs  # 20/22

    after_safety_checks = list(
        SimulationSafetyCheck.objects.filter(session=session).values("rule_name", "result", "reason")
    )
    assert before_safety_checks == after_safety_checks  # 23

    after_results = list(
        SimulationResult.objects.filter(session=session).values("gate_result", "evidence_strength")
    )
    assert before_results == after_results  # 24


# 25-27. Operational tables unchanged
def test_what_if_leaves_operational_tables_untouched(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-OPERATIONAL-ISOLATION",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)
    before = _operational_counts()
    before_alert = Alert.objects.count()
    before_investigation = Investigation.objects.count()

    officer_a_api.post(_what_if_url(session_id), {"overrides": {"CHW": 40}}, format="json")

    assert _operational_counts() == before
    assert Alert.objects.count() == before_alert
    assert Investigation.objects.count() == before_investigation


# 28-29. What-If runs the actual Phase 4 pipeline and Phase 6 SafetyEngine
def test_what_if_runs_actual_pipeline_and_safety_engine(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-REAL-PIPELINE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 4}, {"CHW": (4, True), "PHC": (7, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    response = officer_a_api.post(
        _what_if_url(session_id), {"overrides": {"CHW": 10}}, format="json"
    )
    hypothetical = response.data["hypothetical"]

    stage_names = [stage["agent"] for stage in hypothetical["pipeline"]]
    assert stage_names == ["ingestion", "signal_analysis", "correlation", "evidence"]
    assert all(stage["status"] == "COMPLETE" for stage in hypothetical["pipeline"])

    assert len(hypothetical["safety"]["checks"]) == 9
    assert {c["rule"] for c in hypothetical["safety"]["checks"]} == {
        "village_scope_verified",
        "reporting_period_validated",
        "duplicate_records_checked",
        "sufficient_historical_window",
        "source_relationships_evaluated",
        "missing_data_assessed",
        "no_individual_diagnosis_generated",
        "no_autonomous_outbreak_declaration",
        "human_review_required",
    }


# 30. What-If safety result is independent of original safety result
def test_what_if_safety_result_can_diverge_from_original(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-DIVERGENT-SAFETY",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True), "PHARMACY": (3, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True), "PHARMACY": (3, True)}),
            _week(3, {"FEVER": 5}, {"CHW": (5, True), "PHC": (9, True), "PHARMACY": (3, True)}),
        ],
    )
    session_id, response = _start_and_advance(officer_a_api, scenario.id, 2)  # week 3, escalating
    original_gate = response.data["agent_runs"][-1]["output"]["gate_result"]
    assert original_gate == "PASS"  # 3 weeks revealed, 100% completeness

    # Hypothetically mark two of the three sources as not reported for the
    # current week -> overall completeness drops below the Rule 6
    # threshold (78%, computed below), even though nothing about the
    # REAL, persisted week 3 changed.
    hypothetical = officer_a_api.post(
        _what_if_url(session_id),
        {"overrides": {"PHC": None, "PHARMACY": None}},
        format="json",
    ).data

    assert hypothetical["original"]["gate_result"] == "PASS"
    assert hypothetical["hypothetical"]["safety"]["gate_result"] == "INSUFFICIENT"
    assert hypothetical["hypothetical"]["data_quality"]["completeness_pct"] < 80


# 31. What-If evidence strength uses the actual existing deterministic logic
def test_what_if_evidence_strength_matches_deterministic_formula(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-EVIDENCE-FORMULA",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHARMACY": (5, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHARMACY": (3, True)}),
            _week(3, {"FEVER": 5}, {"CHW": (5, True), "PHARMACY": (1, True)}),
        ],
    )
    # 3 weeks revealed (meets the Rule 4 historical-window minimum) so the
    # safety-finalized value equals the Phase 5 preliminary one here —
    # otherwise an escalating trend with only 2 revealed weeks would be
    # downgraded by Rule 4 regardless of the override under test.
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 2)

    # CHW supports (up vs week 2's value), PHARMACY conflicts (steadily
    # down) against an escalating trend -> MODERATE by the documented
    # `_evidence_strength` formula (supporting=1, conflicting=1).
    hypothetical = officer_a_api.post(
        _what_if_url(session_id), {"overrides": {"CHW": 6}}, format="json"
    ).data["hypothetical"]

    relations = {c["source"]: c["relation"] for c in hypothetical["constellation"]}
    assert relations["CHW"] == "SUPPORTING"
    assert relations["PHARMACY"] == "CONFLICTING"
    assert hypothetical["trend"] == "INCREASING"
    assert hypothetical["safety"]["gate_result"] == "PASS"  # nothing else fails here
    assert hypothetical["safety"]["evidence_strength"] == "MODERATE"


# 32. Safety can downgrade hypothetical evidence strength
def test_what_if_safety_downgrades_hypothetical_strong_evidence(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-DOWNGRADE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True), "PHARMACY": (3, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True), "PHARMACY": (3, True)}),
            _week(3, {"FEVER": 5}, {"CHW": (5, True), "PHC": (9, True), "PHARMACY": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 2)  # week 3, escalating, STRONG

    hypothetical = officer_a_api.post(
        _what_if_url(session_id),
        {"overrides": {"PHC": None, "PHARMACY": None}},
        format="json",
    ).data["hypothetical"]

    assert hypothetical["safety"]["gate_result"] == "INSUFFICIENT"
    assert hypothetical["safety"]["evidence_strength"] in {"MODERATE", "WEAK"}
    assert hypothetical["safety"]["evidence_strength"] != "STRONG"


# 33. Safety cannot upgrade hypothetical evidence strength
def test_what_if_safety_never_upgrades_weak_evidence(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-NO-UPGRADE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 2}, {"CHW": (2, True)}),  # flat/non-escalating -> WEAK preliminary
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    hypothetical = officer_a_api.post(
        _what_if_url(session_id), {"overrides": {"CHW": 2}}, format="json"  # no real change
    ).data["hypothetical"]

    assert hypothetical["safety"]["gate_result"] == "PASS"
    assert hypothetical["safety"]["evidence_strength"] == "WEAK"  # never upgraded by a PASS gate


# 34. Missing vs reported-zero semantics preserved
def test_what_if_preserves_missing_vs_reported_zero(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-MISSING-VS-ZERO",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    hypothetical = officer_a_api.post(
        _what_if_url(session_id), {"overrides": {"PHC": 0, "CHW": None}}, format="json"
    ).data["hypothetical"]

    assert hypothetical["sources"]["PHC"] == {"value": 0.0, "reported": True}
    assert hypothetical["sources"]["CHW"] == {"value": None, "reported": False}


# 35. Same hypothetical input produces same deterministic result
def test_what_if_is_repeatable_for_the_same_overrides(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-REPEATABLE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHARMACY": (5, True)}),
            _week(2, {"FEVER": 4}, {"CHW": (4, True), "PHARMACY": (1, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    first = WhatIfEngine.run(SimulationSession.objects.get(id=session_id), _current_officer(), {"CHW": 9})
    second = WhatIfEngine.run(SimulationSession.objects.get(id=session_id), _current_officer(), {"CHW": 9})

    assert first["hypothetical"]["trend"] == second["hypothetical"]["trend"]
    assert first["hypothetical"]["constellation"] == second["hypothetical"]["constellation"]
    assert first["hypothetical"]["safety"]["gate_result"] == second["hypothetical"]["safety"]["gate_result"]
    assert (
        first["hypothetical"]["safety"]["evidence_strength"]
        == second["hypothetical"]["safety"]["evidence_strength"]
    )
    assert [c["result"] for c in first["hypothetical"]["safety"]["checks"]] == [
        c["result"] for c in second["hypothetical"]["safety"]["checks"]
    ]


# 36. Cross-village What-If returns 403 (endpoint-level, distinct from #18's engine-level check)
def test_what_if_cross_village_api_returns_403(officer_a_api, officer_b_api, village_b):
    scenario = _build_pipeline_scenario(
        village_b,
        "WHATIF-API-CROSS-VILLAGE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_b_api, scenario.id, 1)

    response = officer_a_api.post(_what_if_url(session_id), {"overrides": {"CHW": 5}}, format="json")
    assert response.status_code == 403


def test_what_if_direct_engine_rejects_mismatched_officer(village, village_b):
    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-DIRECT-MISMATCH",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    officer_a = User.objects.create_user(
        username="officer.whatif-direct-a", password="demo1234", role=User.Role.HEALTH_OFFICER, village=village
    )
    officer_b = User.objects.create_user(
        username="officer.whatif-direct-b", password="demo1234", role=User.Role.HEALTH_OFFICER, village=village_b
    )
    state = SimulationEngine.start(scenario, officer_a)
    session = SimulationSession.objects.get(id=state["session_id"])
    SimulationEngine.advance(session, officer_a)
    session.refresh_from_db()

    with pytest.raises(SimulationVillageMismatch):
        WhatIfEngine.run(session, officer_b, {"CHW": 5})


# 37. What-If cannot override village/officer/patient/operational identifiers
def test_what_if_cannot_override_operational_identifiers(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-NO-IDENTIFIER-OVERRIDE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    for forbidden_key in ("village_id", "officer_id", "session_id", "patient_id", "alert_id"):
        response = officer_a_api.post(
            _what_if_url(session_id), {"overrides": {forbidden_key: 1}}, format="json"
        )
        assert response.status_code == 400


# ===========================================================================
# SAFETY / SECURITY
# ===========================================================================

# 38. Malicious Evidence Agent output ("OUTBREAK DETECTED") in a What-If run -> BLOCK
def test_what_if_blocks_injected_outbreak_declaration(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-MALICIOUS-OUTBREAK",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    with patch("simulation.orchestrator.get_llm_client") as mock_get_client:
        mock_get_client.return_value.summarise.return_value = (
            "OUTBREAK DETECTED — confirmed outbreak, escalate immediately."
        )
        response = officer_a_api.post(
            _what_if_url(session_id), {"overrides": {"CHW": 12}}, format="json"
        )

    hypothetical = response.data["hypothetical"]
    assert hypothetical["safety"]["gate_result"] == "BLOCK"
    outbreak_check = next(
        c for c in hypothetical["safety"]["checks"] if c["rule"] == "no_autonomous_outbreak_declaration"
    )
    assert outbreak_check["result"] == "BLOCK"
    # The injected phrase never becomes an authoritative SUMMARY
    # conclusion — trend, primary signal, constellation, and the actual
    # source values are all deterministic and untouched by the LLM. It is
    # allowed to appear, quoted, in two places: the safety rule's own
    # `reason` (explaining what it caught) and the raw per-stage
    # `pipeline` debug output (the same "view raw input/output"
    # transparency Phase 4's Agent Pipeline card already offers) — neither
    # of those presents it AS a conclusion.
    summary_text = json.dumps(
        {
            "trend": hypothetical["trend"],
            "primary_signal": hypothetical["primary_signal"],
            "constellation": hypothetical["constellation"],
            "sources": hypothetical["sources"],
            "gate_result": hypothetical["safety"]["gate_result"],
            "evidence_strength": hypothetical["safety"]["evidence_strength"],
        }
    ).lower()
    assert "outbreak detected" not in summary_text
    assert "confirmed outbreak" not in summary_text


# 39. What-If cannot bypass SafetyEngine
def test_what_if_always_includes_a_full_safety_evaluation(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-NO-BYPASS",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    response = officer_a_api.post(_what_if_url(session_id), {"overrides": {"CHW": 5}}, format="json")

    safety = response.data["hypothetical"]["safety"]
    assert set(safety.keys()) >= {"checks", "gate_result", "human_review_required", "evidence_strength"}
    assert safety["human_review_required"] is True
    assert len(safety["checks"]) == 9


# 40. LLM failure does not alter the deterministic trend in a What-If run
def test_what_if_llm_failure_does_not_alter_deterministic_trend(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "WHATIF-LLM-FAILURE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    from agents.llm import LLMUnavailable

    with patch("simulation.orchestrator.get_llm_client") as mock_get_client:
        mock_get_client.return_value.summarise.side_effect = LLMUnavailable("down for test")
        response = officer_a_api.post(
            _what_if_url(session_id), {"overrides": {"CHW": 6}}, format="json"
        )

    assert response.status_code == 200
    hypothetical = response.data["hypothetical"]
    assert hypothetical["trend"] == "STABLE"  # 3 -> 6 is below the escalation threshold
    assert hypothetical["safety"]["gate_result"] == "PASS"


# 41. No LLM import anywhere under simulation/safety/ (re-confirmed unaffected by Phase 7)
def test_safety_package_still_has_no_llm_import():
    from tests.test_simulation_safety import test_no_llm_import_under_safety_package

    test_no_llm_import_under_safety_package()
