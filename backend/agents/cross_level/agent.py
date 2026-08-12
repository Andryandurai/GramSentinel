"""The Cross-Level Intelligence Agent.

The question it asks: do appropriately aggregated individual-level signals
support, contradict, or say nothing about the community-level pattern — in the
same category, the same place, the same week?

It works on aggregates only. It never receives a patient record, and there is
no code path here that could request one: its input is the counts-by-category
snapshot produced at the aggregation boundary.

Hard limits, enforced structurally:
  * it must not diagnose an individual;
  * it must not declare an outbreak;
  * its only permitted output type is a correlation hypothesis;
  * its output goes to the Safety Engine, never directly to a human.
"""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent

CONSISTENT = "CONSISTENT"
CONTRADICTORY = "CONTRADICTORY"
SILENT = "SILENT"

#: Percentage change in aggregated encounters that counts as the individual
#: layer "agreeing" that something is moving.
AGREEMENT_THRESHOLD_PCT = 40.0
#: Below this, the individual layer is actively flat while the community layer
#: is elevated — a disagreement worth recording.
FLAT_THRESHOLD_PCT = 10.0


class CrossLevelIntelligenceAgent(BaseAgent):
    name = "CrossLevelIntelligenceAgent"
    display_name = "Cross-Level Intelligence"
    purpose = (
        "Checked whether anonymised patient activity agrees with the community "
        "signals."
    )
    layer = "CROSS_LEVEL"
    stage = "DOMAIN_REASONING"

    def summarise_output(self, output: dict[str, Any]) -> str:
        cross = output.get("cross_level") or {}
        verdict = cross.get("verdict", SILENT)
        readable = {
            CONSISTENT: "Individual and community evidence agree",
            CONTRADICTORY: "Individual and community evidence disagree",
            SILENT: "Individual evidence is neither for nor against",
        }.get(verdict, verdict)
        aggregated = cross.get("aggregated_individual") or {}
        count = aggregated.get("encounter_count")
        detail = (
            f" ({count} aggregated encounters compared)." if count is not None else "."
        )
        return readable + detail

    def summarise_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        snapshot = payload.get("individual_snapshot") or {}
        return {
            "village_code": snapshot.get("village_code"),
            "week_label": snapshot.get("week_label"),
            "categories_present": sorted(
                (snapshot.get("counts_by_category") or {}).keys()
            ),
            "input_type": "aggregated_counts_only",
        }

    def handle(self, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        snapshot: dict[str, Any] = payload.get("individual_snapshot") or {}
        candidate: dict[str, Any] = payload.get("candidate_pattern") or {}

        category = candidate.get("category") or ""
        cluster = candidate.get("cluster") or ""
        week_label = candidate.get("week_label") or snapshot.get("week_label") or ""

        counts = snapshot.get("counts_by_category") or {}
        baselines = snapshot.get("baselines_by_category") or {}

        current = counts.get(category)
        baseline = baselines.get(category)

        # --- alignment on three axes: category, geography, time --------
        category_aligned = current is not None
        geography_aligned = bool(
            snapshot.get("village_code")
            and candidate.get("cluster")
            and payload.get("village_cluster") == cluster
        )
        time_aligned = bool(
            snapshot.get("week_label")
            and candidate.get("week_label")
            and snapshot["week_label"] == candidate["week_label"]
        )

        change_pct: float | None = None
        if current is not None and baseline not in (None, 0):
            change_pct = round((current - baseline) / baseline * 100.0, 1)

        verdict, statement = self._verdict(
            category=category,
            cluster=cluster,
            week_label=week_label,
            current=current,
            change_pct=change_pct,
            category_aligned=category_aligned,
            geography_aligned=geography_aligned,
            time_aligned=time_aligned,
            community_detected=bool(candidate.get("detected")),
        )

        return {
            "cross_level": {
                # Same permitted output type as the cluster agent. Anything
                # else is blocked by Safety Rule 6.
                "kind": "correlation_hypothesis",
                "verdict": verdict,
                "statement": statement,
                "cluster": cluster,
                "category": category,
                "week_label": week_label,
                "alignment": {
                    "category": category_aligned,
                    "geography": geography_aligned,
                    "time": time_aligned,
                },
                "aggregated_individual": {
                    "encounter_count": current,
                    "baseline": baseline,
                    "change_pct": change_pct,
                    "source": "privacy_preserving_aggregation",
                },
                "community_corroborating_count": candidate.get("corroborating_count", 0),
                "limits": (
                    "Correlation hypothesis only. Does not diagnose an individual "
                    "and does not declare an outbreak."
                ),
            }
        }

    @staticmethod
    def _verdict(
        *,
        category: str,
        cluster: str,
        week_label: str,
        current: int | None,
        change_pct: float | None,
        category_aligned: bool,
        geography_aligned: bool,
        time_aligned: bool,
        community_detected: bool,
    ) -> tuple[str, str]:
        if not community_detected:
            return SILENT, (
                "No community-level candidate pattern to compare aggregated "
                "individual signals against."
            )

        if not category_aligned or current is None:
            return SILENT, (
                f"No aggregated {category.lower()} encounters were recorded in "
                f"{cluster} for {week_label}. The individual layer is silent on "
                "this pattern rather than agreeing or disagreeing with it."
            )

        if not (geography_aligned and time_aligned):
            mismatches = []
            if not geography_aligned:
                mismatches.append("geography")
            if not time_aligned:
                mismatches.append("time window")
            return SILENT, (
                "Aggregated individual signals exist but do not align on "
                f"{' and '.join(mismatches)}, so they neither support nor "
                "contradict the community pattern."
            )

        if change_pct is not None and change_pct >= AGREEMENT_THRESHOLD_PCT:
            return CONSISTENT, (
                f"Individual-level and community-level signals show a "
                f"potentially consistent pattern in the same geographical and "
                f"temporal context: {current} aggregated {category.lower()} "
                f"encounters in {cluster} during {week_label} "
                f"({change_pct:+.0f}% against their own baseline), alongside "
                "independent community sources moving in the same direction."
            )

        if change_pct is not None and change_pct <= FLAT_THRESHOLD_PCT:
            return CONTRADICTORY, (
                f"Community sources are elevated, but aggregated individual "
                f"encounters in {cluster} during {week_label} are flat "
                f"({current} encounters, {change_pct:+.0f}% against baseline). "
                "This disagreement lowers confidence and may point to a "
                "data-quality issue or a non-health explanation."
            )

        return SILENT, (
            f"{current} aggregated {category.lower()} encounters in {cluster} "
            f"during {week_label}"
            + (f" ({change_pct:+.0f}% against baseline)" if change_pct is not None else "")
            + ". Movement is not decisive either way; treated as neither "
            "support nor contradiction."
        )
