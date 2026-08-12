"""Agent 8 — Cluster Detection.

Assembles a candidate pattern from evidence cards that no single agent could
have produced alone. Its output is explicitly a *candidate*: it is handed to
the Cross-Level agent and then to the Safety Engine, never to a human.

The narrative may be rewritten by the LLM for readability. If it is, the Safety
Engine's Rule 6 still screens the result, so an over-reaching sentence gets the
whole finding blocked rather than shown.
"""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from agents.llm import LLMUnavailable, get_llm_client
from core.constants import EvidenceStatus

LLM_SYSTEM_PROMPT = (
    "You write one short paragraph for a district health officer summarising "
    "which independent data sources moved together in one village cluster in "
    "one week. Rules you must follow: describe only the listed evidence; never "
    "name or imply a disease; never state or imply that an outbreak exists, is "
    "confirmed, or is declared; never use the words 'diagnosis', 'confirmed "
    "outbreak', 'epidemic' or 'guaranteed'; always describe the finding as a "
    "possible pattern that a human should decide whether to investigate."
)


class ClusterDetectionAgent(BaseAgent):
    name = "ClusterDetectionAgent"
    display_name = "Cluster Detection"
    purpose = "Assembled a candidate pattern from the independent sources."
    layer = "GRAMSENTINEL"
    stage = "DOMAIN_REASONING"

    def summarise_output(self, output: dict[str, Any]) -> str:
        candidate = output.get("candidate_pattern") or {}
        count = candidate.get("corroborating_count", 0)
        if not candidate.get("detected"):
            return "No independent source exceeded its baseline. No candidate pattern."
        kinds = ", ".join(candidate.get("corroborating_source_kinds") or [])
        return (
            f"Put forward a possible pattern supported by {count} independent "
            f"source(s): {kinds}. Sent for safety verification, not to a human."
        )

    def summarise_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "card_count": len(payload.get("evidence_cards") or []),
            "cluster": payload.get("cluster"),
            "week_label": payload.get("week_label"),
        }

    def handle(self, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        cards: list[dict[str, Any]] = payload.get("evidence_cards") or []
        trend: dict[str, Any] = payload.get("village_trend") or {}
        cluster = payload.get("cluster", "")
        week_label = payload.get("week_label", "")
        category = payload.get("category", "")

        corroborating = [
            c
            for c in cards
            if c.get("is_corroborating")
            and c["status"]
            in {EvidenceStatus.ANOMALY_DETECTED, EvidenceStatus.CORROBORATING}
        ]
        context_cards = [
            c for c in cards if c["status"] == EvidenceStatus.SUPPORTING_CONTEXT
        ]

        pattern_detected = len(corroborating) >= 1
        deterministic = self._template(
            cluster, week_label, corroborating, context_cards, trend
        )
        narrative, used_llm = self._maybe_polish(deterministic, corroborating, cluster)

        return {
            "candidate_pattern": {
                "detected": pattern_detected,
                # The one permitted output type. Checked by Safety Rule 6.
                "kind": "correlation_hypothesis",
                "cluster": cluster,
                "category": category,
                "week_label": week_label,
                "corroborating_source_kinds": [c["source_kind"] for c in corroborating],
                "context_source_kinds": [c["source_kind"] for c in context_cards],
                "corroborating_count": len(corroborating),
                "narrative": narrative,
                "deterministic_narrative": deterministic,
                "trajectory": trend.get("trajectory"),
            },
            "_used_llm": used_llm,
        }

    @staticmethod
    def _template(
        cluster: str,
        week_label: str,
        corroborating: list[dict],
        context_cards: list[dict],
        trend: dict,
    ) -> str:
        if not corroborating:
            return (
                f"No independent source in {cluster} exceeded its own baseline "
                f"in {week_label}. No candidate pattern."
            )

        lines = []
        for card in sorted(corroborating, key=lambda c: c["source_kind"]):
            if card.get("change_pct") is not None:
                lines.append(
                    f"{card['source_kind']} {card['change_pct']:+.0f}% "
                    f"({card['baseline']:g} → {card['current_value']:g} {card['unit']})"
                )
            else:
                lines.append(
                    f"{card['source_kind']} {card['current_value']:g} {card['unit']}"
                )

        text = (
            f"In {cluster} during {week_label}, {len(corroborating)} independent "
            f"source(s) moved above their own baselines: {'; '.join(lines)}."
        )
        if context_cards:
            kinds = ", ".join(sorted({c["source_kind"] for c in context_cards}))
            text += f" Supporting environmental context is present ({kinds})."
        missing = trend.get("missing_sources") or []
        if missing:
            text += (
                f" {', '.join(sorted(set(missing)))} did not submit for this "
                "window and is recorded as missing rather than zero."
            )
        text += (
            " This is a possible pattern put forward for deterministic "
            "verification and human review, not a finding."
        )
        return text

    def _maybe_polish(
        self, deterministic: str, corroborating: list[dict], cluster: str
    ) -> tuple[str, bool]:
        client = get_llm_client()
        if not client.available or not corroborating:
            return deterministic, False
        try:
            facts = "\n".join(
                f"- {c['source_kind']}: baseline {c['baseline']}, current "
                f"{c['current_value']}, change {c.get('change_pct')}%, "
                f"quality {c['data_quality']}"
                for c in corroborating
            )
            text = client.summarise(
                LLM_SYSTEM_PROMPT,
                f"Cluster: {cluster}\nEvidence:\n{facts}\n\nCurrent wording:\n{deterministic}",
                max_tokens=320,
            )
            return text, True
        except LLMUnavailable:
            return deterministic, False
