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

#: Shown to the worker wherever the optional free-text detail is displayed.
SUPPLEMENTARY_NOTE = (
    "Recorded with the assessment as supplementary context. Triage support and "
    "the deterministic safety checks are based on the recorded symptoms, "
    "duration and vital signs — free text is not interpreted as a symptom."
)


def _clean_timeline(raw: Any) -> list[dict[str, Any]]:
    """Normalise the optional day-wise entries; drop anything empty.

    Deliberately forgiving: an entry that is malformed is skipped rather than
    failing the encounter, because this field is optional extra detail and must
    never be able to stop a worker recording a patient.
    """

    cleaned: list[dict[str, Any]] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        detail = str(entry.get("detail") or "").strip()
        if not detail:
            continue
        try:
            day = int(entry.get("day"))
        except (TypeError, ValueError):
            continue
        cleaned.append({"day": day, "detail": detail})
    return sorted(cleaned, key=lambda e: e["day"])


class PatientListenerAgent(BaseAgent):
    name = "PatientListenerAgent"
    display_name = "Patient Listener"
    purpose = "Structured the reported symptoms and patient information."
    layer = "RURALCARE"
    stage = "DOMAIN_REASONING"

    def summarise_output(self, output: dict[str, Any]) -> str:
        encounter = output.get("encounter", {})
        completeness = output.get("completeness", {})
        supplementary = output.get("supplementary_context", {})
        count = len(encounter.get("symptoms", []))
        vitals = [v for v in encounter.get("vitals", {}).values() if v is not None]

        parts = [
            f"Recorded {count} symptom{'s' if count != 1 else ''}"
            + (f" and {len(vitals)} vital sign(s)." if vitals else ".")
        ]
        unrecognised = encounter.get("unrecognised_entries") or []
        if unrecognised:
            parts.append(f"Kept as free text: {', '.join(unrecognised)}.")

        extras = []
        if supplementary.get("other_symptom_text"):
            extras.append("a described 'other' symptom")
        days = supplementary.get("symptom_timeline") or []
        if days:
            extras.append(f"{len(days)} day(s) of symptom history")
        if extras:
            parts.append(
                f"Also kept {' and '.join(extras)} as supplementary context, "
                "not interpreted as symptom codes."
            )

        missing = completeness.get("missing_vitals") or []
        if missing:
            parts.append(f"{len(missing)} vital sign(s) not recorded.")
        return " ".join(parts)

    def summarise_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Deliberately no name, no patient code, no free text in the audit row.
        return {
            "symptom_count": len(payload.get("symptoms") or []),
            "has_free_text": bool(payload.get("raw_symptom_text")),
            "has_other_symptom_text": bool(payload.get("other_symptom_text")),
            "day_wise_entries": len(_clean_timeline(payload.get("symptom_timeline"))),
            "vitals_supplied": [f for f in VITAL_FIELDS if payload.get(f) is not None],
        }

    def handle(self, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        symptoms, unrecognised = extract_symptoms(
            payload.get("symptoms") or [], payload.get("raw_symptom_text", "")
        )

        # The optional 'Other' description and day-wise history are carried
        # alongside the encounter, never folded into the symptom codes. The
        # triage scorer and the red-flag rule set therefore see exactly what
        # they saw before this field existed, which is what keeps the
        # deterministic behaviour deterministic.
        other_symptom_text = str(payload.get("other_symptom_text") or "").strip()
        timeline = _clean_timeline(payload.get("symptom_timeline"))
        has_supplementary = bool(other_symptom_text or timeline)

        vitals = {f: payload.get(f) for f in VITAL_FIELDS}
        missing_vitals = [f for f, v in vitals.items() if v is None]

        duration_days = payload.get("duration_days")
        try:
            duration_days = int(duration_days) if duration_days is not None else 0
        except (TypeError, ValueError):
            duration_days = 0

        completeness_notes = []
        if not symptoms and not has_supplementary:
            completeness_notes.append("No recognised symptom recorded.")
        elif not symptoms:
            completeness_notes.append(
                "No symptom from the standard list was selected; only the "
                "described detail was recorded."
            )
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
            "supplementary_context": {
                "other_symptom_text": other_symptom_text,
                "symptom_timeline": timeline,
                "has_supplementary_detail": has_supplementary,
                "interpreted_by_triage": False,
                "note": SUPPLEMENTARY_NOTE if has_supplementary else "",
            },
            "completeness": {
                "recognised_symptoms": len(symptoms),
                "missing_vitals": missing_vitals,
                "notes": completeness_notes,
                "is_complete": not completeness_notes,
            },
        }
