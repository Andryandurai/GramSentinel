"""Agent 7 — Village Trend.

Holds the per-village picture over time: how many sources are moving, in which
direction, and how complete this week's reporting actually was. It is the only
community agent that sees all the cards at once, and it still does not decide
anything — it describes.
"""

from __future__ import annotations

import statistics
from typing import Any

from agents.base import BaseAgent
from core.constants import DataQuality, EvidenceStatus


class VillageTrendAgent(BaseAgent):
    name = "VillageTrendAgent"
    display_name = "Village Trend"
    purpose = "Built the overall picture for this village and week."
    layer = "GRAMSENTINEL"
    stage = "DOMAIN_REASONING"

    def summarise_output(self, output: dict[str, Any]) -> str:
        return output.get("description") or "Village trend assembled."

    def summarise_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        cards = payload.get("evidence_cards") or []
        return {
            "card_count": len(cards),
            "village_code": payload.get("village_code"),
            "week_label": payload.get("week_label"),
        }

    def handle(self, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        cards: list[dict[str, Any]] = payload.get("evidence_cards") or []

        anomalous = [
            c
            for c in cards
            if c["status"]
            in {EvidenceStatus.ANOMALY_DETECTED, EvidenceStatus.CORROBORATING}
        ]
        corroborating = [c for c in anomalous if c.get("is_corroborating")]
        context_only = [
            c for c in cards if c["status"] == EvidenceStatus.SUPPORTING_CONTEXT
        ]
        operationally_unavailable = [
            c for c in cards if c["status"] == EvidenceStatus.EXPECTED_UNAVAILABLE
        ]
        # A source a human has explicitly recorded as unavailable this window
        # is not an unexplained gap, so it is never counted as "missing" (that
        # label is reserved for a genuinely unexplained absence) — Section 9.
        missing = [
            c
            for c in cards
            if not c.get("is_reported", True)
            and c["status"] != EvidenceStatus.EXPECTED_UNAVAILABLE
        ]

        changes = [
            c["change_pct"] for c in anomalous if c.get("change_pct") is not None
        ]
        median_change = round(statistics.median(changes), 1) if changes else None

        # Completeness is measured against sources that were actually
        # *expected* to report this window — a source flagged operationally
        # unavailable is excluded from both the numerator and the
        # denominator, so it never creates the same data-quality penalty an
        # unexpectedly missing source would (Section 10).
        expected_sources = [
            c for c in cards if c["status"] != EvidenceStatus.EXPECTED_UNAVAILABLE
        ]
        reporting_sources = [c for c in expected_sources if c.get("is_reported", True)]
        completeness = (
            round(len(reporting_sources) / len(expected_sources), 2)
            if expected_sources
            else 0.0
        )
        degraded = [
            c
            for c in reporting_sources
            if c.get("data_quality") not in {DataQuality.GOOD, DataQuality.PARTIAL}
        ]

        if len(corroborating) >= 2:
            trajectory = "MULTIPLE_SOURCES_RISING"
        elif len(corroborating) == 1:
            trajectory = "SINGLE_SOURCE_RISING"
        elif context_only:
            trajectory = "CONTEXT_ONLY"
        else:
            trajectory = "STABLE"

        return {
            "village_code": payload.get("village_code"),
            "village_name": payload.get("village_name", ""),
            "cluster": payload.get("cluster", ""),
            "week_label": payload.get("week_label"),
            "trajectory": trajectory,
            "sources_evaluated": len(cards),
            "sources_reporting": len(reporting_sources),
            "anomalous_sources": [c["source_kind"] for c in anomalous],
            "corroborating_sources": [c["source_kind"] for c in corroborating],
            "context_sources": [c["source_kind"] for c in context_only],
            "missing_sources": [c["source_kind"] for c in missing],
            "operationally_unavailable_sources": [
                c["source_kind"] for c in operationally_unavailable
            ],
            "degraded_quality_sources": [c["source_kind"] for c in degraded],
            "median_change_pct": median_change,
            "reporting_completeness": completeness,
            "description": self._describe(
                trajectory,
                corroborating,
                context_only,
                missing,
                operationally_unavailable,
                median_change,
            ),
        }

    @staticmethod
    def _describe(
        trajectory: str,
        corroborating: list[dict],
        context_only: list[dict],
        missing: list[dict],
        operationally_unavailable: list[dict],
        median_change: float | None,
    ) -> str:
        parts: list[str] = []
        if corroborating:
            kinds = ", ".join(sorted({c["source_kind"] for c in corroborating}))
            change = f" (median {median_change:+.0f}%)" if median_change is not None else ""
            parts.append(f"{len(corroborating)} independent source(s) rising: {kinds}{change}.")
        else:
            parts.append("No independent source is above its own baseline.")
        if context_only:
            kinds = ", ".join(sorted({c["source_kind"] for c in context_only}))
            parts.append(f"Supporting context present: {kinds}.")
        if missing:
            kinds = ", ".join(sorted({c["source_kind"] for c in missing}))
            parts.append(f"Not submitted this window (recorded as missing, not zero): {kinds}.")
        if operationally_unavailable:
            kinds = ", ".join(sorted({c["source_kind"] for c in operationally_unavailable}))
            parts.append(
                f"Excluded due to a recorded operational context: {kinds}."
            )
        parts.append(f"Trajectory: {trajectory.replace('_', ' ').lower()}.")
        return " ".join(parts)
