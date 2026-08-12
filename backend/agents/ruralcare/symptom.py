"""Agent 2 — Symptom Analysis.

Maps the structured encounter onto the standardised taxonomy, tags duration and
severity, and identifies which syndrome groups are represented. It does not
name a disease and has no concept of one.
"""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from community.aggregation import category_for_symptoms

from .vocabulary import SYMPTOM_WEIGHT, SYNDROME_GROUPS


class SymptomAnalysisAgent(BaseAgent):
    name = "SymptomAnalysisAgent"
    display_name = "Symptom Analysis"
    purpose = "Identified relevant symptom patterns."
    layer = "RURALCARE"
    stage = "DOMAIN_REASONING"

    def summarise_output(self, output: dict[str, Any]) -> str:
        groups = output.get("syndrome_groups") or {}
        primary = output.get("primary_syndrome")
        duration = output.get("duration_band", "UNSTATED")

        if not groups:
            return "No recognised symptom pattern identified."

        named = ", ".join(sorted(groups))
        text = f"Matched {len(groups)} symptom group(s): {named}."
        if primary:
            text += f" Predominant pattern: {primary}."
        if duration != "UNSTATED":
            text += f" Duration band: {duration.replace('_', ' ').lower()}."
        return text

    def summarise_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        encounter = payload.get("encounter", {})
        return {
            "symptom_codes": encounter.get("symptoms", []),
            "duration_days": encounter.get("duration_days"),
        }

    def handle(self, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        encounter = payload.get("encounter", {})
        symptoms: list[str] = encounter.get("symptoms", [])
        duration_days: int = encounter.get("duration_days", 0) or 0

        groups = {
            group: sorted(set(symptoms) & set(members))
            for group, members in SYNDROME_GROUPS.items()
        }
        present_groups = {g: s for g, s in groups.items() if s}

        symptom_burden = round(sum(SYMPTOM_WEIGHT.get(s, 0.5) for s in symptoms), 2)

        if duration_days >= 7:
            duration_band = "PROLONGED"
        elif duration_days >= 3:
            duration_band = "SUB_ACUTE"
        elif duration_days >= 1:
            duration_band = "ACUTE"
        else:
            duration_band = "UNSTATED"

        return {
            "normalised_symptoms": symptoms,
            "syndrome_groups": present_groups,
            "primary_syndrome": (
                max(present_groups, key=lambda g: len(present_groups[g]))
                if present_groups
                else None
            ),
            "symptom_burden": symptom_burden,
            "duration_band": duration_band,
            "duration_days": duration_days,
            "signal_category": category_for_symptoms(symptoms),
            "vitals": encounter.get("vitals", {}),
            "age_months": encounter.get("age_months"),
        }
