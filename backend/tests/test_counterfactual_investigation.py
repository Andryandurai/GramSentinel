"""Counterfactual Investigation — a Village-A-only, structured-UI wrapper
around the existing Phase 7 What-If pipeline (`simulation.what_if
.WhatIfEngine`, unchanged in its computation, only enriched with a few
already-derivable comparison fields — see `simulation/views.py`'s
`SimulationCounterfactualView` and `simulation/what_if.py`'s
`original_payload` enrichment).

Reuses the exact scenario-building helpers, village fixtures and BLOCK/
INSUFFICIENT recipes from `test_simulation.py` / `test_simulation_replay_
whatif.py` rather than redefining them — the underlying engine is already
exhaustively tested there (missing-vs-zero, repeatability, cross-village
engine-level rejection, LLM-injected-outbreak BLOCK, historical-window
INSUFFICIENT, etc.); this file focuses on what is actually new: the
`/counterfactual/` endpoint itself, its Village-A gate, and the small
comparison-field enrichment.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from alerts.models import Alert, Investigation
from community.models import CommunityReport, LocalSignalReport
from simulation.models import SimulationInvestigation, SimulationSession, SimulationSourceSignal

from tests.test_simulation import (
    SESSIONS_URL,
    _advance,
    _build_pipeline_scenario,
    _week,
    officer_a_api,  # noqa: F401 - reused fixture
    officer_b_api,  # noqa: F401 - reused fixture
    village_b,  # noqa: F401 - reused fixture
)

User = get_user_model()
pytestmark = pytest.mark.django_db


def _counterfactual_url(session_id: int) -> str:
    return f"{SESSIONS_URL}{session_id}/counterfactual/"


def _start_and_advance(api_client, scenario_id: int, times: int):
    response = api_client.post(SESSIONS_URL, {"scenario_id": scenario_id}, format="json")
    session_id = response.data["session_id"]
    for _ in range(times):
        response = _advance(api_client, session_id)
    return session_id, response


def _operational_counts() -> dict[str, int]:
    return {
        "alerts": Alert.objects.count(),
        "investigations": Investigation.objects.count(),
        "community_reports": CommunityReport.objects.count(),
        "local_signal_reports": LocalSignalReport.objects.count(),
        "simulation_investigations": SimulationInvestigation.objects.count(),
    }


# ---------------------------------------------------------------------------
# 1, 4, 5, 6 — runs for an authorized Village A officer, using the real
# orchestrator, correlation output, and SafetyEngine
# ---------------------------------------------------------------------------
def test_counterfactual_runs_for_village_a_officer_via_real_pipeline(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "CF-VILLAGE-A",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 4}, {"CHW": (4, True), "PHC": (7, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    response = officer_a_api.post(
        _counterfactual_url(session_id), {"overrides": {"CHW": 10}}, format="json"
    )

    assert response.status_code == 200
    hypothetical = response.data["hypothetical"]
    stage_names = [stage["agent"] for stage in hypothetical["pipeline"]]
    assert stage_names == ["ingestion", "signal_analysis", "correlation", "evidence"]
    assert all(stage["status"] == "COMPLETE" for stage in hypothetical["pipeline"])
    assert all("relation" in c and "source" in c for c in hypothetical["constellation"])
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


# ---------------------------------------------------------------------------
# 2 — uses the selected hypothetical override
# ---------------------------------------------------------------------------
def test_counterfactual_applies_the_selected_override(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "CF-APPLIES-OVERRIDE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHARMACY": (1, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHARMACY": (1, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    data = officer_a_api.post(
        _counterfactual_url(session_id), {"overrides": {"PHARMACY": 8}}, format="json"
    ).data

    assert data["hypothetical"]["sources"]["PHARMACY"] == {"value": 8.0, "reported": True}
    # Untouched source keeps its real value.
    assert data["hypothetical"]["sources"]["CHW"] == {"value": 3.0, "reported": True}


# ---------------------------------------------------------------------------
# The new comparison-field enrichment (both sides symmetric, both derived
# from real constellation/timeline data — no new algorithm).
# ---------------------------------------------------------------------------
def test_counterfactual_comparison_fields_are_derived_from_real_data(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "CF-COMPARISON-FIELDS",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True)}),
            _week(3, {"FEVER": 5}, {"CHW": (5, True), "PHC": (9, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 2)

    data = officer_a_api.post(
        _counterfactual_url(session_id), {"overrides": {"PHC": None}}, format="json"
    ).data

    original = data["original"]
    hypothetical = data["hypothetical"]
    # Original: both sources reported and supporting an escalating trend.
    assert original["supporting_count"] == 2
    assert original["conflicting_count"] == 0
    assert original["missing_count"] == 0
    assert original["trend"] == "INCREASING"
    # Hypothetical: PHC now not reported -> one fewer supporting source, one missing.
    assert hypothetical["supporting_count"] == 1
    assert hypothetical["missing_count"] == 1
    assert data["changed_sources"] == ["PHC"]


# ---------------------------------------------------------------------------
# Regression for the screenshot bug this task fixes: a magnitude-only
# override that does not change a source's direction relative to the
# previous week must still be reported as applied via `changed_sources`,
# even though it leaves every derived comparison metric unchanged. Before
# this fix, the frontend read an empty `changed_sources` as the ONLY signal
# that anything happened, so this legitimate "applied, no effect" case was
# indistinguishable from "the override never reached the pipeline" — this
# test locks in the backend contract the frontend fix now relies on.
# ---------------------------------------------------------------------------
def test_counterfactual_override_can_leave_derived_metrics_unchanged(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "CF-MAGNITUDE-ONLY",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    data = officer_a_api.post(
        _counterfactual_url(session_id), {"overrides": {"CHW": 12}}, format="json"
    ).data

    original = data["original"]
    hypothetical = data["hypothetical"]
    # The override was genuinely applied...
    assert data["changed_sources"] == ["CHW"]
    assert hypothetical["sources"]["CHW"] == {"value": 12.0, "reported": True}
    # ...but CHW's direction relative to week 1 (up) is unchanged by going
    # from 3 to 12 (still up), so its SUPPORTING classification — and every
    # metric derived from it — stays exactly the same as the original.
    assert hypothetical["supporting_count"] == original["supporting_count"] == 2
    assert hypothetical["conflicting_count"] == original["conflicting_count"] == 0
    assert hypothetical["safety"]["evidence_strength"] == original["evidence_strength"]


# ---------------------------------------------------------------------------
# 3, 11, 14, 15, 16, 17 — isolation: nothing operational or simulation-real
# is created or modified, whether counterfactual is run once or repeatedly
# (repeated calls are what a worker does after "Reset" and a new selection).
# ---------------------------------------------------------------------------
def test_counterfactual_leaves_original_and_operational_records_untouched(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "CF-ISOLATION",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)
    real_rows_before = list(
        SimulationSourceSignal.objects.filter(event__session_id=session_id).values(
            "source_type", "value", "reported"
        )
    )
    before = _operational_counts()

    officer_a_api.post(_counterfactual_url(session_id), {"overrides": {"CHW": 99}}, format="json")
    # A second run with a different selection, as "Reset" then a new pick
    # would produce.
    officer_a_api.post(_counterfactual_url(session_id), {"overrides": {"CHW": None}}, format="json")

    assert (
        list(
            SimulationSourceSignal.objects.filter(event__session_id=session_id).values(
                "source_type", "value", "reported"
            )
        )
        == real_rows_before
    )
    assert _operational_counts() == before


# ---------------------------------------------------------------------------
# 7, 18 — Safety BLOCK is preserved, never softened, no outbreak declaration
# ---------------------------------------------------------------------------
def test_counterfactual_safety_block_is_preserved_and_never_softened(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "CF-SAFETY-BLOCK",
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
            _counterfactual_url(session_id), {"overrides": {"CHW": 12}}, format="json"
        )

    hypothetical = response.data["hypothetical"]
    assert hypothetical["safety"]["gate_result"] == "BLOCK"
    outbreak_check = next(
        c for c in hypothetical["safety"]["checks"] if c["rule"] == "no_autonomous_outbreak_declaration"
    )
    assert outbreak_check["result"] == "BLOCK"
    summary_text = json.dumps(
        {
            "trend": hypothetical["trend"],
            "constellation": hypothetical["constellation"],
            "sources": hypothetical["sources"],
            "gate_result": hypothetical["safety"]["gate_result"],
        }
    ).lower()
    assert "outbreak detected" not in summary_text
    assert "confirmed outbreak" not in summary_text
    # BLOCK never creates the operational Alert a real signal might.
    assert Alert.objects.count() == 0


# ---------------------------------------------------------------------------
# 8 — Safety INSUFFICIENT is preserved, never upgraded to strong evidence
# ---------------------------------------------------------------------------
def test_counterfactual_safety_insufficient_is_preserved(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "CF-SAFETY-INSUFFICIENT",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True), "PHARMACY": (3, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True), "PHARMACY": (3, True)}),
            _week(3, {"FEVER": 5}, {"CHW": (5, True), "PHC": (9, True), "PHARMACY": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 2)

    data = officer_a_api.post(
        _counterfactual_url(session_id),
        {"overrides": {"PHC": None, "PHARMACY": None}},
        format="json",
    ).data

    assert data["original"]["gate_result"] == "PASS"
    assert data["hypothetical"]["safety"]["gate_result"] == "INSUFFICIENT"
    # Adding two more (unreported) sources never turns this into "strong evidence".
    assert data["hypothetical"]["safety"]["evidence_strength"] != "STRONG"


# ---------------------------------------------------------------------------
# 9 — Missing vs reported-zero semantics preserved through the new endpoint
# ---------------------------------------------------------------------------
def test_counterfactual_preserves_missing_vs_reported_zero(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "CF-MISSING-VS-ZERO",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    hypothetical = officer_a_api.post(
        _counterfactual_url(session_id), {"overrides": {"PHC": 0, "CHW": None}}, format="json"
    ).data["hypothetical"]

    assert hypothetical["sources"]["PHC"] == {"value": 0.0, "reported": True}
    assert hypothetical["sources"]["CHW"] == {"value": None, "reported": False}


# ---------------------------------------------------------------------------
# 10 — multiple hypothetical overrides combine in one run
# ---------------------------------------------------------------------------
def test_counterfactual_multiple_overrides_combine(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "CF-MULTI-OVERRIDE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (3, True), "PHARMACY": (1, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (3, True), "PHARMACY": (1, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)

    data = officer_a_api.post(
        _counterfactual_url(session_id),
        {"overrides": {"PHC": 9, "PHARMACY": 7}},
        format="json",
    ).data

    assert data["hypothetical"]["sources"]["PHC"] == {"value": 9.0, "reported": True}
    assert data["hypothetical"]["sources"]["PHARMACY"] == {"value": 7.0, "reported": True}
    assert sorted(data["changed_sources"]) == ["PHARMACY", "PHC"]


# ---------------------------------------------------------------------------
# 12 — cross-village / non-Village-A access is rejected server-side
# ---------------------------------------------------------------------------
def test_counterfactual_rejects_non_village_a_session(officer_b_api, village_b):
    scenario = _build_pipeline_scenario(
        village_b,
        "CF-VILLAGE-B-REJECTED",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_b_api, scenario.id, 1)

    response = officer_b_api.post(
        _counterfactual_url(session_id), {"overrides": {"CHW": 10}}, format="json"
    )

    assert response.status_code == 403
    assert "Village A" in str(response.data)


def test_counterfactual_cross_village_officer_still_rejected(officer_a_api, officer_b_api, village_b):
    """A Village A officer probing a Village B session id — rejected by the
    same object-level village check every other session endpoint uses,
    before the feature's own Village-A gate is ever reached."""

    scenario = _build_pipeline_scenario(
        village_b,
        "CF-CROSS-VILLAGE-OFFICER",
        [_week(1, {"FEVER": 2}, {"CHW": (2, True)}), _week(2, {"FEVER": 3}, {"CHW": (3, True)})],
    )
    session_id, _ = _start_and_advance(officer_b_api, scenario.id, 1)

    response = officer_a_api.post(
        _counterfactual_url(session_id), {"overrides": {"CHW": 10}}, format="json"
    )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 13 — a Health Worker cannot invoke the officer counterfactual endpoint
# ---------------------------------------------------------------------------
def test_counterfactual_rejects_worker_role(api, worker, village):
    scenario = _build_pipeline_scenario(
        village,
        "CF-WORKER-REJECTED",
        [_week(1, {"FEVER": 2}, {"CHW": (2, True)})],
    )
    template_session = SimulationSession.objects.filter(scenario=scenario).first()
    api.force_authenticate(user=worker)

    response = api.post(
        _counterfactual_url(template_session.id), {"overrides": {"CHW": 10}}, format="json"
    )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Regression: the plain, pre-existing What-If endpoint remains completely
# unrestricted by this feature — Counterfactual Investigation is an
# additional, narrower door, not a new lock on the existing one.
# ---------------------------------------------------------------------------
def test_plain_what_if_endpoint_remains_unrestricted_for_village_b(officer_b_api, village_b):
    scenario = _build_pipeline_scenario(
        village_b,
        "CF-WHATIF-STILL-OPEN",
        [_week(1, {"FEVER": 2}, {"CHW": (2, True)}), _week(2, {"FEVER": 3}, {"CHW": (3, True)})],
    )
    session_id, _ = _start_and_advance(officer_b_api, scenario.id, 1)

    response = officer_b_api.post(
        f"{SESSIONS_URL}{session_id}/what-if/", {"overrides": {"CHW": 10}}, format="json"
    )

    assert response.status_code == 200
