"""The standardised internal symptom taxonomy.

Free-text and checkbox entries from the worker portal are mapped onto these
codes so that every downstream agent — and the red-flag rule set — is talking
about the same thing.
"""

from __future__ import annotations

import re

#: canonical code -> accepted surface forms
SYMPTOM_SYNONYMS: dict[str, tuple[str, ...]] = {
    "fever": ("fever", "temperature", "pyrexia", "jvaram", "bukhar"),
    "high_fever": ("high fever", "very high fever"),
    "chills": ("chills", "rigors", "shivering"),
    "headache": ("headache", "head ache", "head pain"),
    "body_pain": ("body pain", "body ache", "myalgia", "muscle pain", "joint pain"),
    "cough": ("cough", "dry cough", "productive cough"),
    "sore_throat": ("sore throat", "throat pain"),
    "breathlessness": ("breathlessness", "shortness of breath", "difficulty breathing", "sob"),
    "chest_pain": ("chest pain", "chest discomfort"),
    "diarrhoea": ("diarrhoea", "diarrhea", "loose motion", "loose stools"),
    "vomiting": ("vomiting", "vomit", "throwing up"),
    "abdominal_pain": ("abdominal pain", "stomach pain", "belly pain"),
    "severe_dehydration": ("severe dehydration", "very dry mouth"),
    "unable_to_drink": ("unable to drink", "not drinking", "refusing feeds"),
    "sunken_eyes": ("sunken eyes",),
    "rash": ("rash", "skin rash"),
    "neck_stiffness": ("neck stiffness", "stiff neck"),
    "altered_consciousness": ("altered consciousness", "confusion", "disoriented", "drowsy"),
    "unconscious": ("unconscious", "unresponsive"),
    "seizure": ("seizure", "convulsion", "fits"),
    "bleeding": ("bleeding", "haemorrhage"),
    "bleeding_gums": ("bleeding gums",),
    "blood_in_stool": ("blood in stool", "bloody stool"),
    "blood_in_vomit": ("blood in vomit",),
    "fatigue": ("fatigue", "weakness", "tiredness"),
    "loss_of_appetite": ("loss of appetite", "not eating"),
    "jaundice": ("jaundice", "yellow eyes"),
}

#: Severity weight used by the triage scorer. Higher means more concerning.
SYMPTOM_WEIGHT: dict[str, float] = {
    "fever": 2.0,
    "high_fever": 3.0,
    "chills": 1.0,
    "headache": 1.0,
    "body_pain": 1.0,
    "cough": 1.0,
    "sore_throat": 0.5,
    "breathlessness": 4.0,
    "chest_pain": 3.5,
    "diarrhoea": 2.0,
    "vomiting": 1.5,
    "abdominal_pain": 1.5,
    "severe_dehydration": 4.0,
    "unable_to_drink": 3.5,
    "sunken_eyes": 2.5,
    "rash": 1.0,
    "neck_stiffness": 4.0,
    "altered_consciousness": 5.0,
    "unconscious": 6.0,
    "seizure": 6.0,
    "bleeding": 4.5,
    "bleeding_gums": 3.5,
    "blood_in_stool": 3.5,
    "blood_in_vomit": 4.0,
    "fatigue": 0.5,
    "loss_of_appetite": 0.5,
    "jaundice": 2.5,
}

SYNDROME_GROUPS: dict[str, tuple[str, ...]] = {
    "febrile": ("fever", "high_fever", "chills"),
    "respiratory": ("cough", "sore_throat", "breathlessness", "chest_pain"),
    "gastrointestinal": (
        "diarrhoea",
        "vomiting",
        "abdominal_pain",
        "severe_dehydration",
        "unable_to_drink",
    ),
    "neurological": ("headache", "neck_stiffness", "altered_consciousness", "seizure", "unconscious"),
    "haemorrhagic": ("bleeding", "bleeding_gums", "blood_in_stool", "blood_in_vomit"),
}

_SURFACE_TO_CODE = {
    surface: code
    for code, surfaces in SYMPTOM_SYNONYMS.items()
    for surface in surfaces
}


def normalise_symptom(raw: str) -> str | None:
    """Map one surface form to a canonical code, or None if unrecognised."""

    cleaned = re.sub(r"[^a-z ]+", " ", raw.strip().lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    if cleaned.replace(" ", "_") in SYMPTOM_SYNONYMS:
        return cleaned.replace(" ", "_")
    return _SURFACE_TO_CODE.get(cleaned)


def extract_symptoms(items: list[str], free_text: str = "") -> tuple[list[str], list[str]]:
    """Return (recognised codes, unrecognised entries).

    Unrecognised entries are surfaced rather than silently dropped — a worker
    should be able to see that something they typed was not understood.
    """

    found: list[str] = []
    unknown: list[str] = []

    for item in items or []:
        code = normalise_symptom(str(item))
        if code:
            if code not in found:
                found.append(code)
        elif str(item).strip():
            unknown.append(str(item).strip())

    lowered = f" {re.sub(r'[^a-z ]+', ' ', (free_text or '').lower())} "
    for surface, code in _SURFACE_TO_CODE.items():
        if f" {surface} " in lowered and code not in found:
            found.append(code)

    return found, unknown
