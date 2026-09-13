"""Phase 6 — deterministic Safety Engine tests.

Reuses the Phase 4/5 scenario-building helpers and village fixtures from
`test_simulation.py` rather than redefining them — see that file's own
`_build_pipeline_scenario`/`_week`/`_advance`/`village_b`/`officer_a_api`/
`officer_b_api` docstrings for what each represents. `village`, `officer`,
`worker`, `api` come from the shared `tests/conftest.py`.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from alerts.models import Alert, Feedback, Investigation
from simulation.models import (
    SafetyGateResult,
    SimulationAgentRun,
    SimulationResult,
    SimulationSafetyCheck,
    SimulationSession,
)
from simulation.safety import RULE_ORDER, RULES, SafetyEngine, SafetyRuleResult, finalize_evidence_strength
from simulation.safety.engine import _aggregate
from simulation.services import SimulationEngine

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


def _safety_url(session_id: int) -> str:
    return f"{SESSIONS_URL}{session_id}/safety/"


def _start_and_advance(api_client, scenario_id: int, times: int):
    response = api_client.post(SESSIONS_URL, {"scenario_id": scenario_id}, format="json")
    session_id = response.data["session_id"]
    for _ in range(times):
        response = _advance(api_client, session_id)
    return session_id, response


def _safety_output_from_advance(response) -> dict:
    return next(r for r in response.data["agent_runs"] if r["agent_name"] == "safety")["output"]


# ===========================================================================
# A. SafetyEngine structure
# ===========================================================================
def test_nine_rules_exist_in_fixed_order():
    assert RULE_ORDER == (
        "village_scope_verified",
        "reporting_period_validated",
        "duplicate_records_checked",
        "sufficient_historical_window",
        "source_relationships_evaluated",
        "missing_data_assessed",
        "no_individual_diagnosis_generated",
        "no_autonomous_outbreak_declaration",
        "human_review_required",
    )
    assert len(RULES) == 9
    assert SafetyEngine.RULES is RULES


def test_each_rule_is_independently_callable_with_valid_vocabulary(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-STRUCTURE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)
    session = SimulationSession.objects.get(id=session_id)
    officer = User.objects.get(username="officer.simulation-test")

    ctx = SafetyEngine._build_context(session, officer, {}, {}, {}, {})
    for rule in RULES:
        result = rule(ctx)
        assert isinstance(result, SafetyRuleResult)
        assert result.result in {
            SafetyGateResult.PASS,
            SafetyGateResult.BLOCK,
            SafetyGateResult.INSUFFICIENT,
        }
        assert result.rule_name in RULE_ORDER
        assert isinstance(result.reason, str) and result.reason


# ===========================================================================
# B. Positive case
# ===========================================================================
def test_positive_case_emerging_signal_passes_with_human_review(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-POSITIVE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True)}),
            _week(3, {"FEVER": 5}, {"CHW": (5, True), "PHC": (9, True)}),
            _week(4, {"FEVER": 9}, {"CHW": (9, True), "PHC": (14, True)}),
        ],
    )
    session_id, response = _start_and_advance(officer_a_api, scenario.id, 3)
    output = _safety_output_from_advance(response)

    assert all(check["result"] == "PASS" for check in output["checks"])
    assert output["gate_result"] == "PASS"
    assert output["human_review_required"] is True
    assert output["evidence_strength"] == "STRONG"


# ===========================================================================
# C. Unauthorized village (negative fixture 1)
# ===========================================================================
def test_unauthorized_village_api_returns_403(officer_a_api, officer_b_api, village_b):
    scenario = _build_pipeline_scenario(
        village_b,
        "SAFETY-CROSS-VILLAGE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_b_api, scenario.id, 1)

    response = officer_a_api.get(_safety_url(session_id))

    assert response.status_code == 403
    assert "checks" not in response.data  # never partial safety data alongside the error


def test_unauthorized_village_direct_engine_call_cannot_silently_pass(village, village_b):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-DIRECT-MISMATCH",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    officer_a = User.objects.create_user(
        username="officer.safety-direct-a", password="demo1234", role=User.Role.HEALTH_OFFICER, village=village
    )
    officer_b = User.objects.create_user(
        username="officer.safety-direct-b", password="demo1234", role=User.Role.HEALTH_OFFICER, village=village_b
    )
    state = SimulationEngine.start(scenario, officer_a)
    session = SimulationSession.objects.get(id=state["session_id"])
    SimulationEngine.advance(session, officer_a)
    session.refresh_from_db()

    result = SafetyEngine.evaluate_latest(session, officer_b)

    assert result["gate_result"] == "BLOCK"
    village_check = next(c for c in result["checks"] if c["rule"] == "village_scope_verified")
    assert village_check["result"] == "BLOCK"


# ===========================================================================
# D. Reporting period (negative fixture 8: invalid reporting period)
# ===========================================================================
def test_reporting_period_valid_passes(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-PERIOD-VALID",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, response = _start_and_advance(officer_a_api, scenario.id, 1)
    output = _safety_output_from_advance(response)
    period_check = next(c for c in output["checks"] if c["rule"] == "reporting_period_validated")
    assert period_check["result"] == "PASS"


def test_reporting_period_zero_is_blocked(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-PERIOD-ZERO",
        [_week(1, {"FEVER": 2}, {"CHW": (2, True)})],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    session = SimulationSession.objects.get(id=start.data["session_id"])
    session.replay_position = 0
    session.save(update_fields=["replay_position"])
    officer = User.objects.get(username="officer.simulation-test")

    result = SafetyEngine.evaluate_latest(session, officer)

    assert result["gate_result"] == "BLOCK"
    period_check = next(c for c in result["checks"] if c["rule"] == "reporting_period_validated")
    assert period_check["result"] == "BLOCK"


def test_reporting_period_beyond_available_data_is_blocked(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-PERIOD-FUTURE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    session = SimulationSession.objects.get(id=start.data["session_id"])
    session.replay_position = 999
    session.save(update_fields=["replay_position"])
    officer = User.objects.get(username="officer.simulation-test")

    result = SafetyEngine.evaluate_latest(session, officer)

    assert result["gate_result"] == "BLOCK"
    period_check = next(c for c in result["checks"] if c["rule"] == "reporting_period_validated")
    assert period_check["result"] == "BLOCK"
    assert "999" in period_check["reason"]
    assert "beyond" in period_check["reason"]


# ===========================================================================
# E. Historical window (negative fixture 3: insufficient historical window)
# ===========================================================================
def test_insufficient_historical_window_for_an_escalating_signal(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-WINDOW-INSUFFICIENT",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 6}, {"CHW": (6, True)}),  # SIGNAL_DETECTED at week 2
        ],
    )
    session_id, response = _start_and_advance(officer_a_api, scenario.id, 1)
    output = _safety_output_from_advance(response)

    window_check = next(c for c in output["checks"] if c["rule"] == "sufficient_historical_window")
    assert window_check["result"] == "INSUFFICIENT"
    assert output["gate_result"] == "INSUFFICIENT"


def test_stable_trend_does_not_require_the_historical_minimum(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-WINDOW-STABLE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 2}, {"CHW": (2, True)}),
        ],
    )
    session_id, response = _start_and_advance(officer_a_api, scenario.id, 1)
    output = _safety_output_from_advance(response)
    window_check = next(c for c in output["checks"] if c["rule"] == "sufficient_historical_window")
    assert window_check["result"] == "PASS"


# ===========================================================================
# F. Missing data (negative fixture 2: missing data)
# ===========================================================================
def test_low_completeness_is_insufficient_and_downgrades_strong_evidence(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-MISSING-DATA",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (6, True)}),
            _week(3, {"FEVER": 5}, {"CHW": (5, True), "PHC": (None, False)}),
            _week(4, {"FEVER": 9}, {"CHW": (9, True), "PHC": (None, False)}),
        ],
    )
    session_id, response = _start_and_advance(officer_a_api, scenario.id, 3)
    output = _safety_output_from_advance(response)

    missing_check = next(c for c in output["checks"] if c["rule"] == "missing_data_assessed")
    assert missing_check["result"] == "INSUFFICIENT"
    assert output["gate_result"] == "INSUFFICIENT"
    # Preliminary (Phase 5) evidence for this escalating, fully-agreeing
    # signal would be STRONG — safety must downgrade it, never leave it
    # upgraded or unchanged once completeness fails.
    assert output["evidence_strength"] in {"MODERATE", "WEAK"}
    assert output["evidence_strength"] != "STRONG"


# ===========================================================================
# G. Reported zero is not missing
# ===========================================================================
def test_reported_zero_is_not_treated_as_missing_by_the_safety_engine(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-REPORTED-ZERO",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (0, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True), "PHC": (0, True)}),
        ],
    )
    session_id, response = _start_and_advance(officer_a_api, scenario.id, 1)
    output = _safety_output_from_advance(response)
    missing_check = next(c for c in output["checks"] if c["rule"] == "missing_data_assessed")
    assert missing_check["result"] == "PASS"
    assert "100%" in missing_check["reason"]


# ===========================================================================
# H. Duplicate data (negative fixture 4: duplicate data)
# ===========================================================================
def test_duplicate_ingestion_records_for_the_same_week_are_blocked(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-DUPLICATE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, response = _start_and_advance(officer_a_api, scenario.id, 1)
    session = SimulationSession.objects.get(id=session_id)
    # The schema does not prevent two different `SimulationAgentRun` rows
    # both claiming to be the "ingestion" stage for the same week — inject
    # exactly that (a retried/duplicated advance(), which the DB itself has
    # no constraint against) rather than trying to violate a real
    # uniqueness constraint that would just raise IntegrityError.
    SimulationAgentRun.objects.create(
        session=session,
        village=session.village,
        agent_name="ingestion",
        status=SimulationAgentRun.Status.COMPLETE,
        input={},
        output={"week": 2, "sources": {}, "reported_source_count": 0, "missing_source_count": 0},
    )
    officer = User.objects.get(username="officer.simulation-test")

    result = SafetyEngine.evaluate_latest(session, officer)

    assert result["gate_result"] == "BLOCK"
    duplicate_check = next(c for c in result["checks"] if c["rule"] == "duplicate_records_checked")
    assert duplicate_check["result"] == "BLOCK"
    assert "week(s) 2" in duplicate_check["reason"]


def test_no_duplicates_passes_and_explains_the_schema_guarantee(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-NO-DUPLICATE",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, response = _start_and_advance(officer_a_api, scenario.id, 1)
    output = _safety_output_from_advance(response)
    duplicate_check = next(c for c in output["checks"] if c["rule"] == "duplicate_records_checked")
    assert duplicate_check["result"] == "PASS"


# ===========================================================================
# I. Source relationships (negative fixture 5: conflicting evidence)
# ===========================================================================
def test_supporting_relationships_are_acceptable(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-SUPPORTING",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHC": (5, True)}),
            _week(2, {"FEVER": 4}, {"CHW": (4, True), "PHC": (7, True)}),
        ],
    )
    session_id, response = _start_and_advance(officer_a_api, scenario.id, 1)
    output = _safety_output_from_advance(response)
    relationship_check = next(c for c in output["checks"] if c["rule"] == "source_relationships_evaluated")
    assert relationship_check["result"] == "PASS"


def test_conflicting_evidence_does_not_force_a_false_block(officer_a_api, village):
    """Negative fixture 5 (conflicting evidence). Task §6 Rule 5 is
    explicit and repeated: a conflicting source must never, by itself,
    force a non-PASS result ("should not manufacture a false failure
    merely because evidence disagrees") — caution is guaranteed instead by
    Rule 9's unconditional `human_review_required`, and the disagreement
    itself stays fully visible in the checklist reason text and in the
    Evidence Constellation. This is a deliberate resolution of an apparent
    tension with this phase's own one-line test-summary elsewhere
    ("conflicting relationships = cautious/non-PASS") in favour of §6's
    own, far more detailed and twice-repeated rule text — see the Phase 6
    report's "identified conflicts" section."""

    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-CONFLICTING",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True), "PHARMACY": (5, True)}),
            _week(2, {"FEVER": 4}, {"CHW": (4, True), "PHARMACY": (1, True)}),
            _week(3, {"FEVER": 6}, {"CHW": (6, True), "PHARMACY": (0, True)}),
        ],
    )
    session_id, response = _start_and_advance(officer_a_api, scenario.id, 2)
    output = _safety_output_from_advance(response)

    relationship_check = next(c for c in output["checks"] if c["rule"] == "source_relationships_evaluated")
    assert relationship_check["result"] == "PASS"
    assert output["gate_result"] == "PASS"
    assert output["human_review_required"] is True

    intelligence_relations = {
        c["source"]: c["relation"]
        for c in officer_a_api.get(
            f"{SESSIONS_URL}{session_id}/intelligence/"
        ).data["constellation"]
    }
    assert intelligence_relations["PHARMACY"] == "CONFLICTING"  # visible, not hidden


def test_insufficient_relationships_when_none_have_been_evaluated_yet(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-NO-RELATIONSHIPS",
        [_week(1, {"FEVER": 2}, {"CHW": (2, True)})],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    session = SimulationSession.objects.get(id=start.data["session_id"])
    officer = User.objects.get(username="officer.simulation-test")

    result = SafetyEngine.evaluate_latest(session, officer)

    relationship_check = next(c for c in result["checks"] if c["rule"] == "source_relationships_evaluated")
    assert relationship_check["result"] == "INSUFFICIENT"
    assert result["gate_result"] == "INSUFFICIENT"


# ===========================================================================
# J. Malformed agent output (negative fixture 6)
# ===========================================================================
def test_malformed_evidence_output_is_non_pass_not_an_exception(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-MALFORMED",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)
    session = SimulationSession.objects.get(id=session_id)
    officer = User.objects.get(username="officer.simulation-test")

    for malformed in ("not-a-dict", 42, {"unexpected": "shape"}, {"primary_signal": "FEVER", "trend": "STABLE", "source_relationships": "not-a-list"}):
        result = SafetyEngine.evaluate(session, officer, evidence_output=malformed)
        assert result["gate_result"] != "PASS"
        relationship_check = next(c for c in result["checks"] if c["rule"] == "source_relationships_evaluated")
        assert relationship_check["result"] == "INSUFFICIENT"


# ===========================================================================
# K. Autonomous outbreak declaration (negative fixture 7)
# ===========================================================================
def test_outbreak_declaration_language_is_blocked(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-OUTBREAK-INJECTION",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)
    session = SimulationSession.objects.get(id=session_id)
    officer = User.objects.get(username="officer.simulation-test")

    result = SafetyEngine.evaluate(
        session,
        officer,
        evidence_output={
            "primary_signal": "FEVER",
            "trend": "STABLE",
            "source_relationships": [],
            "explanation": "OUTBREAK DETECTED — immediate action required.",
        },
    )

    assert result["gate_result"] == "BLOCK"
    outbreak_check = next(c for c in result["checks"] if c["rule"] == "no_autonomous_outbreak_declaration")
    assert outbreak_check["result"] == "BLOCK"
    # The injected text is never presented as the system's own authoritative
    # conclusion — the top-level `gate_result` is the deterministic BLOCK,
    # not the injected string, and nothing in the response claims an
    # outbreak is confirmed.
    payload_text = json.dumps(result).lower()
    assert "outbreak detected" not in payload_text.replace("contains an autonomous outbreak-declaration phrase ('outbreak detected')", "")


# ===========================================================================
# L. Individual diagnosis (part of negative fixture set)
# ===========================================================================
def test_individual_diagnosis_language_is_blocked(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-DIAGNOSIS-INJECTION",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)
    session = SimulationSession.objects.get(id=session_id)
    officer = User.objects.get(username="officer.simulation-test")

    result = SafetyEngine.evaluate(
        session,
        officer,
        signal_output={"trend": "STABLE", "explanation": "The patient has confirmed dengue fever."},
    )

    assert result["gate_result"] == "BLOCK"
    diagnosis_check = next(c for c in result["checks"] if c["rule"] == "no_individual_diagnosis_generated")
    assert diagnosis_check["result"] == "BLOCK"


# ===========================================================================
# M. Human review always required
# ===========================================================================
@pytest.mark.parametrize(
    "evidence_output,expect_gate",
    [
        (None, "PASS"),
        ({"primary_signal": "FEVER", "trend": "STABLE", "source_relationships": [], "explanation": "OUTBREAK DETECTED"}, "BLOCK"),
    ],
)
def test_human_review_required_regardless_of_gate_result(officer_a_api, village, evidence_output, expect_gate):
    scenario = _build_pipeline_scenario(
        village,
        f"SAFETY-HUMAN-REVIEW-{expect_gate}",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)
    session = SimulationSession.objects.get(id=session_id)
    officer = User.objects.get(username="officer.simulation-test")

    kwargs = {"evidence_output": evidence_output} if evidence_output else {}
    result = SafetyEngine.evaluate(session, officer, **kwargs)

    assert result["gate_result"] == expect_gate
    assert result["human_review_required"] is True


def test_human_review_required_for_insufficient_case(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-HUMAN-REVIEW-INSUFFICIENT",
        [_week(1, {"FEVER": 2}, {"CHW": (2, True)})],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    session = SimulationSession.objects.get(id=start.data["session_id"])
    officer = User.objects.get(username="officer.simulation-test")
    result = SafetyEngine.evaluate_latest(session, officer)
    assert result["gate_result"] == "INSUFFICIENT"
    assert result["human_review_required"] is True


# ===========================================================================
# N. Aggregate rule
# ===========================================================================
def _r(result: str) -> SafetyRuleResult:
    return SafetyRuleResult("stub_rule", result, "stub reason")


@pytest.mark.parametrize(
    "results,expected",
    [
        ([_r("PASS"), _r("PASS")], "PASS"),
        ([_r("PASS"), _r("INSUFFICIENT")], "INSUFFICIENT"),
        ([_r("PASS"), _r("BLOCK")], "BLOCK"),
        ([_r("INSUFFICIENT"), _r("BLOCK")], "BLOCK"),
        ([_r("BLOCK"), _r("INSUFFICIENT"), _r("PASS")], "BLOCK"),
    ],
)
def test_aggregate_rule_is_block_over_insufficient_over_pass(results, expected):
    assert _aggregate(results) == expected


# ===========================================================================
# O. Evidence-strength downgrade (monotonic, never an upgrade)
# ===========================================================================
@pytest.mark.parametrize(
    "preliminary,gate_result,expected",
    [
        ("STRONG", "PASS", "STRONG"),
        ("MODERATE", "PASS", "MODERATE"),
        ("WEAK", "PASS", "WEAK"),
        ("STRONG", "INSUFFICIENT", "MODERATE"),
        ("MODERATE", "INSUFFICIENT", "WEAK"),
        ("WEAK", "INSUFFICIENT", "WEAK"),
        ("STRONG", "BLOCK", "WEAK"),
        ("MODERATE", "BLOCK", "WEAK"),
        ("WEAK", "BLOCK", "WEAK"),
    ],
)
def test_finalize_evidence_strength_downgrade_table(preliminary, gate_result, expected):
    assert finalize_evidence_strength(preliminary, gate_result) == expected


def test_finalize_evidence_strength_never_upgrades():
    tier = {"WEAK": 0, "MODERATE": 1, "STRONG": 2}
    for preliminary in ("WEAK", "MODERATE", "STRONG"):
        for gate_result in (SafetyGateResult.PASS, SafetyGateResult.INSUFFICIENT, SafetyGateResult.BLOCK):
            final = finalize_evidence_strength(preliminary, gate_result)
            assert tier[final] <= tier[preliminary]


# ===========================================================================
# P. LLM independence — static import scan
# ===========================================================================
def test_no_llm_import_under_safety_package():
    safety_dir = Path(__file__).resolve().parent.parent / "simulation" / "safety"
    forbidden_module_prefixes = ("agents.llm", "openai", "anthropic")

    scanned_files = list(safety_dir.glob("*.py"))
    assert scanned_files, "expected to find .py files under simulation/safety/"

    for path in scanned_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if node.module else []
            else:
                continue
            for name in names:
                assert not any(
                    name == prefix or name.startswith(prefix + ".") for prefix in forbidden_module_prefixes
                ), f"{path.name} imports forbidden module '{name}'"


# ===========================================================================
# Q. Malicious upstream LLM output through the real pipeline
# ===========================================================================
def test_llm_contradiction_through_real_pipeline_cannot_change_gate_result(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-LLM-MALICIOUS",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    start = officer_a_api.post(SESSIONS_URL, {"scenario_id": scenario.id}, format="json")
    session_id = start.data["session_id"]

    with patch("simulation.orchestrator.get_llm_client") as mock_get_client:
        mock_get_client.return_value.summarise.return_value = (
            "OUTBREAK DETECTED — this is a confirmed outbreak, AI confidence 99%."
        )
        response = _advance(officer_a_api, session_id)

    output = _safety_output_from_advance(response)
    assert output["gate_result"] == "BLOCK"
    outbreak_check = next(c for c in output["checks"] if c["rule"] == "no_autonomous_outbreak_declaration")
    assert outbreak_check["result"] == "BLOCK"


# ===========================================================================
# R. Simulation isolation
# ===========================================================================
def test_safety_evaluation_leaves_operational_tables_untouched(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-ISOLATION",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    before = _operational_counts()
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)
    officer_a_api.get(_safety_url(session_id))  # read-only, called twice
    officer_a_api.get(_safety_url(session_id))

    assert _operational_counts() == before
    assert SimulationSafetyCheck.objects.filter(session_id=session_id).count() == 9
    assert SimulationResult.objects.filter(session_id=session_id).count() == 1


# ===========================================================================
# S. Cross-village safety API
# ===========================================================================
def test_cross_village_safety_api_returns_403_and_officer_b_own_village_still_works(
    officer_a_api, officer_b_api, village_b
):
    scenario = _build_pipeline_scenario(
        village_b,
        "SAFETY-CROSS-VILLAGE-2",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_b_api, scenario.id, 1)

    assert officer_a_api.get(_safety_url(session_id)).status_code == 403
    assert officer_b_api.get(_safety_url(session_id)).status_code == 200


# ===========================================================================
# T. No patient data
# ===========================================================================
def test_safety_payload_contains_no_patient_identity_fields(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-NO-PATIENT-DATA",
        [
            _week(1, {"FEVER": 2}, {"CHW": (2, True)}),
            _week(2, {"FEVER": 3}, {"CHW": (3, True)}),
        ],
    )
    session_id, _ = _start_and_advance(officer_a_api, scenario.id, 1)
    payload_text = json.dumps(officer_a_api.get(_safety_url(session_id)).data).lower()
    for forbidden in ("patient", "phone", "aadhaar", "date_of_birth", "address", "name\":"):
        assert forbidden not in payload_text


# ===========================================================================
# U. No autonomous alerting
# ===========================================================================
def test_no_operational_alert_investigation_or_feedback_created(officer_a_api, village):
    scenario = _build_pipeline_scenario(
        village,
        "SAFETY-NO-AUTONOMOUS-ALERT",
        [
            _week(1, {"FEVER": 8}, {"CHW": (8, True)}),
            _week(2, {"FEVER": 20}, {"CHW": (20, True)}),  # a dramatic escalation
        ],
    )
    before_alerts = Alert.objects.count()
    before_investigations = Investigation.objects.count()
    before_feedback = Feedback.objects.count()

    session_id, response = _start_and_advance(officer_a_api, scenario.id, 1)
    output = _safety_output_from_advance(response)
    assert output["gate_result"] in {"PASS", "BLOCK", "INSUFFICIENT"}  # ran to completion

    assert Alert.objects.count() == before_alerts
    assert Investigation.objects.count() == before_investigations
    assert Feedback.objects.count() == before_feedback
