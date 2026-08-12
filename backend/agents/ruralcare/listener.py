"""Agent 1 — Patient Listener.

Turns whatever the worker typed into a consistent encounter record, and flags
what is incomplete rather than guessing at it.
"""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent

from .vocabulary import extract_symptoms

VITAL_FIELDS = (
    "temperature_c",
    "pulse_bpm",
    "respiratory_rate",
    "systolic_bp",
    "diastolic_bp",
    "spo2",
)


class PatientListenerAgent(BaseAgent):
    name = "PatientListenerAgent"
    display_name = "Patient Listener"
    purpose = "Structured the reported symptoms and patient information."
    layer = "RURALCARE"
    stage = "DOMAIN_REASONING"

    def summarise_output(self, output: dict[str, Any]) -> str:
        encounter = output.get("encounter", {})
        completeness = output.get("completeness", {})
        count = len(encounter.get("symptoms", []))
        vitals = [v for v in encounter.get("vitals", {}).values() if v is not None]

        parts = [
            f"Recorded {count} symptom{'s' if count != 1 else ''}"
            + (f" and {len(vitals)} vital sign(s)." if vitals else ".")
        ]
        unrecognised = encounter.get("unrecognised_entries") or []
        if unrecognised:
            parts.append(f"Kept as free text: {', '.join(unrecognised)}.")
        missing = completeness.get("missing_vitals") or []
        if missing:
            parts.append(f"{len(missing)} vital sign(s) not recorded.")
        return " ".join(parts)

    def summarise_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Deliberately no name, no patient code, no free text in the audit row.
        return {
            "symptom_count": len(payload.get("symptoms") or []),
            "has_free_text": bool(payload.get("raw_symptom_text")),
            "vitals_supplied": [f for f in VITAL_FIELDS if payload.get(f) is not None],
        }

    def handle(self, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        symptoms, unrecognised = extract_symptoms(
            payload.get("symptoms") or [], payload.get("raw_symptom_text", "")
        )

        vitals = {f: payload.get(f) for f in VITAL_FIELDS}
        missing_vitals = [f for f, v in vitals.items() if v is None]

        duration_days = payload.get("duration_days")
        try:
            duration_days = int(duration_days) if duration_days is not None else 0
        except (TypeError, ValueError):
            duration_days = 0

        completeness_notes = []
        if not symptoms:
            completeness_notes.append("No recognised symptom recorded.")
        if unrecognised:
            completeness_notes.append(
                f"Unrecognised entries kept as free text: {', '.join(unrecognised)}."
            )
        if missing_vitals:
            completeness_notes.append(
                f"Vitals not recorded: {', '.join(missing_vitals)}."
            )
        if duration_days == 0:
            completeness_notes.append("Duration not stated.")

        return {
            "encounter": {
                "symptoms": symptoms,
                "unrecognised_entries": unrecognised,
                "duration_days": duration_days,
                "vitals": vitals,
                "age_months": payload.get("age_months"),
                "history": payload.get("history") or [],
            },
            "completeness": {
                "recognised_symptoms": len(symptoms),
                "missing_vitals": missing_vitals,
                "notes": completeness_notes,
                "is_complete": not completeness_notes,
            },
        }
