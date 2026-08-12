"""Agent 3 — Risk / Triage.

Produces a triage level and a short reasoning summary. The score itself is
rule-based and reproducible; the LLM, when configured, only rewrites the
already-decided reasoning into plainer language. It cannot change the level.

Permitted output: a triage level, a reasoning summary and a suggested
workflow. Never a disease name.
"""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from agents.llm import LLMUnavailable, get_llm_client
from core.constants import TriageLevel

#: Score bands. Fixed thresholds so the same encounter always lands the same way.
CONCERNING_THRESHOLD = 3.0
URGENT_THRESHOLD = 7.0

LLM_SYSTEM_PROMPT = (
    "You rewrite an already-decided clinical triage rationale into two plain "
    "sentences for a rural health worker. You must not name, suggest or imply "
    "any disease or diagnosis. You must not change the triage level you are "
    "given. You must not use the words 'diagnosis', 'confirmed', 'outbreak', "
    "or 'guaranteed'. Describe only what was observed and what level was "
    "assigned."
)


class RiskTriageAgent(BaseAgent):
    name = "RiskTriageAgent"
    display_name = "Risk / Triage"
    purpose = "Evaluated the available information for triage support."
    layer = "RURALCARE"
    stage = "DOMAIN_REASONING"

    def summarise_output(self, output: dict[str, Any]) -> str:
        level = output.get("triage_level", "ROUTINE")
        factors = output.get("contributing_factors") or []
        readable = {
            "ROUTINE": "routine",
            "CONCERNING": "concerning",
            "URGENT": "urgent",
        }.get(level, level.lower())

        text = f"Suggested triage level: {readable}."
        if factors:
            shown = factors[:2]
            text += f" Based on {'; '.join(shown)}"
            if len(factors) > 2:
                text += f" and {len(factors) - 2} other factor(s)"
            text += "."
        return text

    def summarise_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "symptom_burden": payload.get("symptom_burden"),
            "duration_band": payload.get("duration_band"),
            "primary_syndrome": payload.get("primary_syndrome"),
        }

    def handle(self, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        symptoms: list[str] = payload.get("normalised_symptoms", [])
        vitals: dict[str, Any] = payload.get("vitals") or {}
        duration_days: int = payload.get("duration_days", 0) or 0
        burden: float = float(payload.get("symptom_burden") or 0.0)

        score = burden
        factors: list[str] = []

        if symptoms:
            factors.append(
                f"symptom burden {burden:.1f} from {len(symptoms)} recorded symptom(s)"
            )

        # Duration contribution
        if duration_days >= 7:
            score += 2.0
            factors.append(f"symptoms persisting {duration_days} days")
        elif duration_days >= 3:
            score += 1.0
            factors.append(f"symptoms persisting {duration_days} days")

        # Vitals contribution — each is an explicit, inspectable threshold.
        temp = vitals.get("temperature_c")
        if temp is not None:
            if temp >= 39.0:
                score += 2.0
                factors.append(f"recorded temperature {temp} °C")
            elif temp >= 38.0:
                score += 1.0
                factors.append(f"recorded temperature {temp} °C")

        spo2 = vitals.get("spo2")
        if spo2 is not None and spo2 < 95:
            score += 2.5
            factors.append(f"oxygen saturation {spo2}%")

        rr = vitals.get("respiratory_rate")
        if rr is not None and rr > 24:
            score += 1.5
            factors.append(f"respiratory rate {rr}/min")

        sbp = vitals.get("systolic_bp")
        if sbp is not None and sbp < 100:
            score += 1.5
            factors.append(f"systolic blood pressure {sbp} mmHg")

        pulse = vitals.get("pulse_bpm")
        if pulse is not None and pulse > 110:
            score += 1.0
            factors.append(f"pulse {pulse}/min")

        age_months = payload.get("age_months")
        if age_months is not None and age_months < 60 and score > 0:
            score += 1.0
            factors.append("young child")

        score = round(score, 2)

        if score >= URGENT_THRESHOLD:
            level = TriageLevel.URGENT
        elif score >= CONCERNING_THRESHOLD:
            level = TriageLevel.CONCERNING
        else:
            level = TriageLevel.ROUTINE

        deterministic_summary = self._template_summary(level, factors)
        summary, used_llm = self._maybe_polish(deterministic_summary, level, factors)

        return {
            "triage_level": str(level),
            "triage_score": score,
            "contributing_factors": factors,
            "thresholds": {
                "concerning_at": CONCERNING_THRESHOLD,
                "urgent_at": URGENT_THRESHOLD,
            },
            "reasoning_summary": summary,
            "deterministic_summary": deterministic_summary,
            "_used_llm": used_llm,
        }

    @staticmethod
    def _template_summary(level: str, factors: list[str]) -> str:
        if not factors:
            return (
                "No concerning features were recorded. Routine care and the "
                "worker's own judgement apply."
            )
        joined = "; ".join(factors)
        phrasing = {
            TriageLevel.URGENT: (
                "Features recorded here fall in the urgent band: {joined}. "
                "Prompt professional evaluation is recommended."
            ),
            TriageLevel.CONCERNING: (
                "Features recorded here fall in the concerning band: {joined}. "
                "Professional clinical evaluation and follow-up are recommended."
            ),
            TriageLevel.ROUTINE: (
                "Recorded features fall in the routine band: {joined}. "
                "Routine care with follow-up if symptoms change."
            ),
        }
        return phrasing[level].format(joined=joined)

    def _maybe_polish(
        self, deterministic: str, level: str, factors: list[str]
    ) -> tuple[str, bool]:
        """Ask the LLM for plainer wording; keep the template on any failure."""

        client = get_llm_client()
        if not client.available:
            return deterministic, False
        try:
            text = client.summarise(
                LLM_SYSTEM_PROMPT,
                (
                    f"Triage level (fixed, do not change): {level}\n"
                    f"Observed factors: {'; '.join(factors) or 'none'}\n"
                    f"Current wording: {deterministic}"
                ),
                max_tokens=200,
            )
            # Cheap guard: if the model smuggled in banned language, discard it.
            lowered = text.lower()
            if any(
                bad in lowered
                for bad in ("diagnos", "confirmed", "outbreak", "guaranteed")
            ):
                return deterministic, False
            return text, True
        except LLMUnavailable:
            return deterministic, False
