"""The orchestrators — Stage 2 of the mandatory pipeline.

Two of them, because the platform has two reasoning paths that meet at the
Cross-Level agent:

  RuralCareOrchestrator   one patient encounter through five agents
  CommunityOrchestrator   one village-week through six signal agents, a trend
                          agent, a cluster agent, the Cross-Level agent and
                          finally the Deterministic Safety Engine

Neither orchestrator makes a domain judgement. It routes, it maintains shared
context, it sequences handoffs, and it records what happened.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from django.conf import settings

from agents.cross_level import CrossLevelIntelligenceAgent
from agents.gramsentinel import (
    ClusterDetectionAgent,
    SIGNAL_AGENTS,
    VillageTrendAgent,
)
from agents.ruralcare import (
    IndividualSafetyAgent,
    PatientListenerAgent,
    ReferralAgent,
    RiskTriageAgent,
    SymptomAnalysisAgent,
)
from safety import EvidenceRecord, Hypothesis, SafetyEngine

from .context import OrchestrationContext

logger = logging.getLogger("gramsentinel.orchestrator")


def _build_engine() -> SafetyEngine:
    cfg = settings.GRAMSENTINEL
    return SafetyEngine(
        min_independent_sources=cfg["MIN_INDEPENDENT_SOURCES"],
        temporal_window_days=cfg["TEMPORAL_WINDOW_DAYS"],
        min_data_quality_ratio=cfg["MIN_DATA_QUALITY_RATIO"],
    )


def _as_date(value: Any) -> dt.date:
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        return dt.date.fromisoformat(value)
    raise ValueError(f"Cannot interpret {value!r} as a date")


class RuralCareOrchestrator:
    """Individual layer: listener -> symptom -> triage -> referral -> safety."""

    def __init__(self, safety_engine: SafetyEngine | None = None) -> None:
        engine = safety_engine or _build_engine()
        self.listener = PatientListenerAgent()
        self.symptom = SymptomAnalysisAgent()
        self.triage = RiskTriageAgent()
        self.referral = ReferralAgent()
        self.individual_safety = IndividualSafetyAgent(engine=engine)

    def run(self, encounter_input: dict[str, Any]) -> dict[str, Any]:
        ctx = OrchestrationContext(
            scope="INDIVIDUAL",
            village_code=encounter_input.get("village_code", ""),
            cluster=encounter_input.get("cluster", ""),
        )

        ctx.begin_stage("STAGE_1_DATA_INGESTION")
        listener = ctx.record(self.listener.run(encounter_input, ctx))
        if listener.status != "OK":
            return self._failure(ctx, "Patient information could not be structured.")

        ctx.begin_stage("STAGE_3_DOMAIN_REASONING")
        symptom = ctx.record(self.symptom.run(listener.output, ctx))
        if symptom.status != "OK":
            return self._failure(ctx, "Symptom analysis failed.")

        triage = ctx.record(self.triage.run(symptom.output, ctx))
        if triage.status != "OK":
            return self._failure(ctx, "Triage support could not be produced.")

        # The referral agent needs both the triage decision and the symptom
        # context, so the orchestrator merges rather than blindly forwarding.
        referral_input = {**symptom.output, **triage.output}
        referral = ctx.record(self.referral.run(referral_input, ctx))

        ctx.begin_stage("STAGE_4_SAFETY_VERIFICATION")
        safety_input = {**symptom.output, **triage.output}
        safety = ctx.record(self.individual_safety.run(safety_input, ctx))
        if safety.status != "OK":
            # A failed safety agent must not resolve to "no red flags found".
            return self._failure(
                ctx, "Individual safety verification did not complete."
            )

        ctx.begin_stage("STAGE_5_HUMAN_FACING_OUTPUT")

        return {
            "ok": True,
            "run_id": str(ctx.run_id),
            "signal_category": symptom.output.get("signal_category"),
            "normalised_symptoms": symptom.output.get("normalised_symptoms", []),
            "syndrome_groups": symptom.output.get("syndrome_groups", {}),
            "completeness": listener.output.get("completeness", {}),
            # Optional free-text detail the worker added. Passed back for
            # display and storage only — no agent below the listener scores it.
            "supplementary_context": listener.output.get(
                "supplementary_context", {}
            ),
            "triage_level": safety.output.get("final_triage_level"),
            "model_triage_level": safety.output.get("model_triage_level"),
            "triage_score": triage.output.get("triage_score"),
            "contributing_factors": triage.output.get("contributing_factors", []),
            "reasoning_summary": triage.output.get("reasoning_summary", ""),
            "referral_recommendation": referral.output.get(
                "referral_recommendation", ""
            ),
            "referral_pathway": referral.output.get("referral_pathway", ""),
            "followup_interval_days": referral.output.get("followup_interval_days"),
            "red_flags": safety.output.get("red_flags", []),
            "escalation_forced": safety.output.get("escalation_forced", False),
            "safety_status": safety.output.get("safety_status", ""),
            "safety_result": safety.output.get("safety_result", {}),
            "safety_note": safety.output.get("safety_note", ""),
            "used_llm": ctx.used_llm,
            "agent_trace": ctx.trace_as_dicts(),
            "flow": ctx.flow_diagram(),
        }

    @staticmethod
    def _failure(ctx: OrchestrationContext, message: str) -> dict[str, Any]:
        logger.error("[ORCHESTRATOR] RuralCare run aborted: %s", message)
        return {
            "ok": False,
            "run_id": str(ctx.run_id),
            "error": message,
            "failed_agents": ctx.failed_agents,
            "agent_trace": ctx.trace_as_dicts(),
        }


class CommunityOrchestrator:
    """Community layer, ending at the deterministic gate."""

    def __init__(self, safety_engine: SafetyEngine | None = None) -> None:
        self.engine = safety_engine or _build_engine()
        self.village_trend = VillageTrendAgent()
        self.cluster = ClusterDetectionAgent()
        self.cross_level = CrossLevelIntelligenceAgent()

    def run(
        self,
        *,
        village: dict[str, Any],
        week_label: str,
        category: str,
        source_payloads: list[dict[str, Any]],
        individual_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        ctx = OrchestrationContext(
            scope="COMMUNITY",
            village_code=village.get("code", ""),
            village_name=village.get("name", ""),
            cluster=village.get("cluster", ""),
            week_label=week_label,
        )

        # ---- Stage 2: route each record to the agent that owns it ------
        ctx.begin_stage("STAGE_2_ORCHESTRATION")
        cards: list[dict[str, Any]] = []
        for payload in source_payloads:
            agent_cls = SIGNAL_AGENTS.get(payload.get("source_kind"))
            if agent_cls is None:
                logger.warning(
                    "[ORCHESTRATOR] no agent registered for source kind %s",
                    payload.get("source_kind"),
                )
                continue
            result = ctx.record(agent_cls().run(payload, ctx))
            if result.status == "OK" and "evidence_card" in result.output:
                cards.append(result.output["evidence_card"])

        ctx.shared["evidence_cards"] = cards

        # ---- Stage 3: trend, then cluster assembly ---------------------
        ctx.begin_stage("STAGE_3_DOMAIN_REASONING")
        trend = ctx.record(
            self.village_trend.run(
                {
                    "evidence_cards": cards,
                    "village_code": village.get("code"),
                    "village_name": village.get("name"),
                    "cluster": village.get("cluster"),
                    "week_label": week_label,
                },
                ctx,
            )
        )

        cluster_result = ctx.record(
            self.cluster.run(
                {
                    "evidence_cards": cards,
                    "village_trend": trend.output,
                    "cluster": village.get("cluster"),
                    "category": category,
                    "week_label": week_label,
                },
                ctx,
            )
        )
        candidate = cluster_result.output.get("candidate_pattern", {})

        cross = ctx.record(
            self.cross_level.run(
                {
                    "individual_snapshot": individual_snapshot,
                    "candidate_pattern": candidate,
                    "village_cluster": village.get("cluster"),
                },
                ctx,
            )
        )
        cross_level = cross.output.get("cross_level", {})

        # ---- Stage 4: the deterministic gate ---------------------------
        ctx.begin_stage("STAGE_4_SAFETY_VERIFICATION")
        records = tuple(self._to_records(cards))
        hypothesis = Hypothesis(
            kind=candidate.get("kind", "correlation_hypothesis"),
            cluster=village.get("cluster", ""),
            category=category,
            week_label=week_label,
            narrative=candidate.get("narrative", ""),
            contributing=records,
            cross_level_verdict=cross_level.get("verdict", "SILENT"),
            cross_level_statement=cross_level.get("statement", ""),
        )
        safety = self.engine.evaluate_community(hypothesis, records)

        ctx.begin_stage("STAGE_5_HUMAN_FACING_OUTPUT")

        return {
            "ok": True,
            "run_id": str(ctx.run_id),
            "village": village,
            "week_label": week_label,
            "category": category,
            "evidence_cards": cards,
            "village_trend": trend.output,
            "candidate_pattern": candidate,
            "cross_level": cross_level,
            "safety": safety.to_dict(),
            "safety_result": safety,
            "hypothesis": hypothesis,
            "used_llm": ctx.used_llm,
            "failed_agents": ctx.failed_agents,
            "agent_trace": ctx.trace_as_dicts(),
            "flow": ctx.flow_diagram(),
        }

    @staticmethod
    def _to_records(cards: list[dict[str, Any]]) -> list[EvidenceRecord]:
        records: list[EvidenceRecord] = []
        for card in cards:
            records.append(
                EvidenceRecord(
                    source_kind=card["source_kind"],
                    source_name=card.get("source_name", ""),
                    category=card.get("category", ""),
                    village_code=card.get("village_code", ""),
                    cluster=card.get("cluster", ""),
                    week_label=card.get("week_label", ""),
                    period_start=_as_date(card["period_start"]),
                    period_end=_as_date(card["period_end"]),
                    status=card["status"],
                    data_quality=card["data_quality"],
                    baseline=card.get("baseline"),
                    current_value=card.get("current_value"),
                    change_pct=card.get("change_pct"),
                    unit=card.get("unit", ""),
                    is_corroborating=bool(card.get("is_corroborating")),
                    is_reported=bool(card.get("is_reported", True)),
                    explanation=card.get("explanation", ""),
                    produced_by_agent=card.get("produced_by_agent", ""),
                )
            )
        return records
