"""Agent 5 — Individual Safety.

The last agent in the RuralCare chain, and deliberately the only one with no
model inference in it at all. It calls the deterministic red-flag rule set and,
if a flag fires, overwrites whatever the earlier agents concluded.

The override direction is one-way: this agent can raise a triage level, never
lower one.
"""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from core.constants import TriageLevel
from safety import IndividualCase, SafetyEngine


class IndividualSafetyAgent(BaseAgent):
    name = "IndividualSafetyAgent"
    display_name = "Safety Verification"
    purpose = "Performed deterministic safety verification."
    layer = "RURALCARE"
    stage = "SAFETY_VERIFICATION"

    def __init__(self, engine: SafetyEngine | None = None) -> None:
        self.engine = engine or SafetyEngine()

    def summarise_output(self, output: dict[str, Any]) -> str:
        flags = output.get("red_flags") or []
        if not flags:
            return (
                "Checked the fixed red-flag rule set. No red-flag combination "
                "detected, so the suggested level stands."
            )
        labels = ", ".join(f["label"] for f in flags)
        return (
            f"Red-flag condition detected ({labels}). Escalated to urgent by "
            "rule — this cannot be overridden by the AI."
        )

    def summarise_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "model_triage_level": payload.get("triage_level"),
            "symptom_count": len(payload.get("normalised_symptoms") or []),
        }

    def handle(self, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        vitals = payload.get("vitals") or {}
        model_level = payload.get("triage_level", TriageLevel.ROUTINE)

        case = IndividualCase(
            symptoms=tuple(payload.get("normalised_symptoms") or []),
            duration_days=int(payload.get("duration_days") or 0),
            age_months=payload.get("age_months"),
            temperature_c=vitals.get("temperature_c"),
            pulse_bpm=vitals.get("pulse_bpm"),
            respiratory_rate=vitals.get("respiratory_rate"),
            systolic_bp=vitals.get("systolic_bp"),
            spo2=vitals.get("spo2"),
            model_triage_level=model_level,
        )

        result, triggered = self.engine.evaluate_individual(case)

        if triggered:
            final_level = TriageLevel.URGENT
            escalation_forced = model_level != TriageLevel.URGENT
            safety_note = (
                "Red-flag combination detected. Escalated to URGENT by the "
                "deterministic rule set; this cannot be suppressed by the model."
            )
        else:
            final_level = model_level
            escalation_forced = False
            safety_note = "No red-flag combination detected."

        return {
            "final_triage_level": str(final_level),
            "model_triage_level": str(model_level),
            "escalation_forced": escalation_forced,
            "red_flags": triggered,
            "safety_status": result.status,
            "safety_verdict": result.verdict,
            "safety_result": result.to_dict(),
            "safety_note": safety_note,
        }
