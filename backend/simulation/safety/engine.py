"""Phase 6 — the deterministic simulation Safety Engine.

This is the fifth and final Phase 4 pipeline stage, finally implemented for
real: `ingestion -> signal_analysis -> correlation -> evidence -> safety`.
Everything downstream of Evidence — the aggregate gate, the finalized
evidence strength, human-review status — is decided here and only here.

Independent of the operational `backend.safety.engine.SafetyEngine`
(individual/community alert gating) by design: this module evaluates a
*simulation* session, never an operational `Alert`/`Investigation`, and
uses its own PASS/BLOCK/INSUFFICIENT vocabulary
(`simulation.models.SafetyGateResult`) rather than the operational
engine's PASS/DOWNGRADE/BLOCK — the two systems protect different things
and are not meant to be unified (see `rules.py`'s module docstring for the
same reasoning applied to the banned-phrase lists).

LLM independence (task §3/§22, non-negotiable): nothing under
`simulation/safety/` imports `agents.llm` or any LLM/model-inference
client. `test_simulation_safety.py::test_no_llm_import_under_safety_package`
statically scans every module in this package's source text and fails the
suite if an LLM import ever appears here — this is not just a convention,
it is enforced.
"""

from __future__ import annotations

from typing import Any

from simulation.intelligence import _batches_by_week, build_intelligence
from simulation.models import (
    EvidenceStrength,
    SafetyGateResult,
    SimulationSession,
    get_template_session,
)

from .rules import RULES, SafetyContext

#: Evidence-strength ordering used only to enforce "downgrade never
#: upgrade" (task §9) — not a score, not exposed anywhere outside this
#: module.
_STRENGTH_TIER = {
    EvidenceStrength.WEAK: 0,
    EvidenceStrength.MODERATE: 1,
    EvidenceStrength.STRONG: 2,
}
_TIER_STRENGTH = {tier: strength for strength, tier in _STRENGTH_TIER.items()}


def _aggregate(results) -> str:
    """BLOCK > INSUFFICIENT > PASS (task §8) — a fixed precedence over a
    small enum, never a weighted score or percentage."""

    values = {r.result for r in results}
    if SafetyGateResult.BLOCK in values:
        return SafetyGateResult.BLOCK
    if SafetyGateResult.INSUFFICIENT in values:
        return SafetyGateResult.INSUFFICIENT
    return SafetyGateResult.PASS


def finalize_evidence_strength(preliminary: str, gate_result: str) -> str:
    """The one centralized, downgrade-only evidence-strength function
    (task §9). `preliminary` is Phase 5's own deterministic
    `explanation.evidence_strength` (WEAK/MODERATE/STRONG) — safety only
    ever lowers it, or leaves it unchanged:

        gate_result == BLOCK          -> WEAK (safety conditions failed
                                          outright; treat evidence as the
                                          most conservative category)
        gate_result == INSUFFICIENT   -> one tier down from `preliminary`
                                          (STRONG->MODERATE,
                                          MODERATE->WEAK, WEAK->WEAK)
        gate_result == PASS           -> unchanged

    The final `min(...)` against `preliminary`'s own tier is a second,
    redundant safety net: even if a future edit to the branches above ever
    introduced an upgrade path by mistake, this line would still prevent
    it from taking effect — the function is monotonic in the safe
    direction by construction, not merely by the current branch logic.
    """

    preliminary_tier = _STRENGTH_TIER.get(preliminary, _STRENGTH_TIER[EvidenceStrength.WEAK])

    if gate_result == SafetyGateResult.BLOCK:
        target_tier = _STRENGTH_TIER[EvidenceStrength.WEAK]
    elif gate_result == SafetyGateResult.INSUFFICIENT:
        target_tier = max(preliminary_tier - 1, _STRENGTH_TIER[EvidenceStrength.WEAK])
    else:
        target_tier = preliminary_tier

    final_tier = min(target_tier, preliminary_tier)
    return _TIER_STRENGTH[final_tier]


class SafetyEngine:
    """No instance state — same `classmethod`-only shape as
    `simulation.services.SimulationEngine`, for the same reason (a stable,
    single import site)."""

    RULES = RULES

    @classmethod
    def evaluate(
        cls,
        session: SimulationSession,
        officer: Any,
        *,
        ingestion_output: dict | None = None,
        signal_output: dict | None = None,
        correlation_output: dict | None = None,
        evidence_output: dict | None = None,
        intelligence_override: dict | None = None,
    ) -> dict[str, Any]:
        """Pure: reads the session's own persisted history (via
        `build_intelligence`) plus whatever upstream stage outputs the
        caller passes in, and returns a plain result dict. Persists
        nothing — `simulation.services._persist_agent_runs` (the app's one
        persistence layer, same as every other Phase 4 stage) turns this
        into a `SimulationAgentRun` row plus the per-rule
        `SimulationSafetyCheck` rows and the finalized `SimulationResult`.

        Explicit keyword arguments rather than silently reconstructed
        defaults, on purpose: an auditable safety engine should never
        guess what it is evaluating. `evaluate_latest` below is the one
        place that fills these in automatically, for the real pipeline and
        for tests that want the ordinary, non-injected case.

        `intelligence_override` (Phase 7 — What-If, task §16/§27/§28): when
        given, `ctx.intelligence` is this dict instead of
        `build_intelligence(session)` — Rules 5/6 (`source_relationships
        _evaluated`, `missing_data_assessed`) read `ctx.intelligence
        ["constellation"]`/`["data_quality"]`, and a hypothetical run needs
        THEM to see the hypothetical constellation/completeness, not the
        real session's persisted ones. Everything else in `_build_context`
        (village, template, revealed-event count) still comes from the
        REAL session — What-If only ever substitutes what the officer
        actually asked to change, never the authorization/history checks.
        `None` (the default) is the exact previous behaviour: every
        existing caller is unaffected.
        """

        ctx = cls._build_context(
            session,
            officer,
            ingestion_output or {},
            signal_output or {},
            correlation_output or {},
            evidence_output or {},
            intelligence_override,
        )
        results = [rule(ctx) for rule in cls.RULES]
        gate_result = _aggregate(results)
        preliminary_strength = ctx.intelligence.get("explanation", {}).get(
            "evidence_strength", EvidenceStrength.WEAK
        )
        final_strength = finalize_evidence_strength(preliminary_strength, gate_result)

        return {
            "checks": [r.to_dict() for r in results],
            "gate_result": gate_result,
            # Rule 9 is unconditional and always PASS — this is not derived
            # from it defensively; it is the same standing invariant Rule 9
            # itself asserts, spelled out at the top level of the response
            # so the API/frontend never has to dig through the checklist to
            # find it (task §9/§12).
            "human_review_required": True,
            "evidence_strength": final_strength,
        }

    @classmethod
    def evaluate_latest(cls, session: SimulationSession, officer: Any) -> dict[str, Any]:
        """Convenience wrapper for the real pipeline
        (`simulation.services._persist_agent_runs`, called once stages 1-4
        are already persisted for the current week) and for tests that
        want the ordinary case without manually fetching each stage's
        output. Reuses `simulation.intelligence._batches_by_week` — the
        exact same "group agent runs into fixed-size per-week batches"
        logic Phase 5 already uses — rather than a second implementation.
        """

        current_week = session.replay_position
        agent_runs = list(session.agent_runs.order_by("id"))
        batch = _batches_by_week(agent_runs).get(current_week, {})

        def _output(agent_name: str) -> dict:
            run = batch.get(agent_name)
            return run.output if run and isinstance(run.output, dict) else {}

        return cls.evaluate(
            session,
            officer,
            ingestion_output=_output("ingestion"),
            signal_output=_output("signal_analysis"),
            correlation_output=_output("correlation"),
            evidence_output=_output("evidence"),
        )

    @staticmethod
    def _build_context(
        session: SimulationSession,
        officer: Any,
        ingestion_output: dict,
        signal_output: dict,
        correlation_output: dict,
        evidence_output: dict,
        intelligence_override: dict | None = None,
    ) -> SafetyContext:
        template = get_template_session(session.scenario)
        revealed_events = (
            list(
                template.events.filter(week_number__lte=session.replay_position)
                .order_by("week_number")
                .prefetch_related("per_source_signals")
            )
            if template is not None
            else []
        )
        intelligence = (
            intelligence_override if intelligence_override is not None else build_intelligence(session)
        )

        return SafetyContext(
            session=session,
            officer=officer,
            template=template,
            revealed_events=revealed_events,
            intelligence=intelligence,
            ingestion_output=ingestion_output,
            signal_output=signal_output,
            correlation_output=correlation_output,
            evidence_output=evidence_output,
        )
