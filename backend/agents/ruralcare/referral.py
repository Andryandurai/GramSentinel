"""Agent 4 — Referral.

Converts a triage level into a plain-language workflow suggestion and a
follow-up interval. It suggests where to go and when to check back; it does not
prescribe treatment.
"""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from core.constants import TriageLevel

REFERRAL_PATHWAYS: dict[str, dict[str, Any]] = {
    TriageLevel.URGENT: {
        "recommendation": (
            "Arrange prompt professional evaluation today at the nearest PHC or "
            "referral facility. Accompany or arrange transport where possible."
        ),
        "pathway": "SAME_DAY_FACILITY_REFERRAL",
        "followup_interval_days": 1,
    },
    TriageLevel.CONCERNING: {
        "recommendation": (
            "Professional clinical evaluation is recommended. Refer to the PHC "
            "and schedule a follow-up visit."
        ),
        "pathway": "PHC_REFERRAL",
        "followup_interval_days": 2,
    },
    TriageLevel.ROUTINE: {
        "recommendation": (
            "Routine care in the community. Advise the household to return if "
            "symptoms worsen or new symptoms appear."
        ),
        "pathway": "COMMUNITY_FOLLOW_UP",
        "followup_interval_days": 5,
    },
}


class ReferralAgent(BaseAgent):
    name = "ReferralAgent"
    display_name = "Referral"
    purpose = "Generated an appropriate workflow / referral suggestion."
    layer = "RURALCARE"
    stage = "DOMAIN_REASONING"

    def summarise_output(self, output: dict[str, Any]) -> str:
        pathway = (output.get("referral_pathway") or "").replace("_", " ").lower()
        interval = output.get("followup_interval_days")
        text = f"Suggested pathway: {pathway or 'none'}."
        if interval:
            text += f" Follow-up in {interval} day(s)."
        return text

    def summarise_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"triage_level": payload.get("triage_level")}

    def handle(self, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        level = payload.get("triage_level", TriageLevel.ROUTINE)
        pathway = REFERRAL_PATHWAYS.get(level, REFERRAL_PATHWAYS[TriageLevel.ROUTINE])

        return {
            "referral_recommendation": pathway["recommendation"],
            "referral_pathway": pathway["pathway"],
            "followup_interval_days": pathway["followup_interval_days"],
            "triage_level": level,
            "note": (
                "This is a suggested workflow for the health worker, not a "
                "treatment instruction."
            ),
        }
