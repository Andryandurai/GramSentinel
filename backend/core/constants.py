"""Vocabulary shared by the agents, the safety engine and the API.

Kept in one place so an evidence card produced by the Pharmacy Signal Agent and
a rule evaluated by the Safety Engine are talking about the same categories.
"""

from django.db import models


class SignalCategory(models.TextChoices):
    """Community health **signal** categories — not diagnoses.

    Every label is deliberately phrased as an observation or an indicator
    ("reported", "suspected", "indicators"). A CHW reporting six skin
    complaints is recording what was observed in the community, not confirming
    a condition. Confirmation is a clinical and epidemiological determination
    made by qualified people outside this platform.

    The first three plus OTHER are the original set and are preserved exactly;
    the rest extend the vocabulary for broader rural reporting.
    """

    # --- original categories (unchanged values) -------------------------
    FEVER = "FEVER", "Fever / febrile illness"
    RESPIRATORY = "RESPIRATORY", "Respiratory illness"
    DIARRHOEAL = "DIARRHOEAL", "Diarrhoeal / gastrointestinal illness"

    # --- extended community signal categories ---------------------------
    SKIN = "SKIN", "Skin conditions / infections"
    EYE = "EYE", "Eye-related conditions"
    VECTOR_BORNE = "VECTOR_BORNE", "Vector-borne illness indicators"
    MOSQUITO_BORNE = "MOSQUITO_BORNE", "Mosquito-borne illness indicators"
    WATER_BORNE = "WATER_BORNE", "Water-borne illness indicators"
    FOOD_BORNE = "FOOD_BORNE", "Food-borne illness indicators"
    ANIMAL_BITE = "ANIMAL_BITE", "Animal / insect bite incidents"
    POISONING = "POISONING", "Suspected poisoning"
    INJURY = "INJURY", "Injuries / accidents"
    MATERNAL = "MATERNAL", "Maternal health concerns"
    CHILD_HEALTH = "CHILD_HEALTH", "Child health concerns"
    MALNUTRITION = "MALNUTRITION", "Malnutrition-related concerns"
    DEHYDRATION = "DEHYDRATION", "Dehydration"
    HEAT_RELATED = "HEAT_RELATED", "Heat-related illness"
    MENTAL_HEALTH = "MENTAL_HEALTH", "Mental health concerns"
    OTHER_COMMUNICABLE = "OTHER_COMMUNICABLE", "Other communicable illness indicators"
    OTHER_NON_COMMUNICABLE = (
        "OTHER_NON_COMMUNICABLE",
        "Other non-communicable health concerns",
    )
    # Label stays neutral: it is shown in read-only views too, so a form
    # instruction like "(describe below)" would read oddly there. The form
    # signals the requirement via DESCRIPTION_REQUIRED_CATEGORIES instead.
    OTHER = "OTHER", "Other health concern"

    # --- system categories: not worker-selectable ------------------------
    ENVIRONMENT = "ENVIRONMENT", "Environmental"
    LAB_CONFIRMATION = "LAB_CONFIRMATION", "Laboratory confirmation"


#: Categories produced by the platform itself rather than reported by a worker.
SYSTEM_CATEGORIES = frozenset(
    {SignalCategory.ENVIRONMENT, SignalCategory.LAB_CONFIRMATION}
)

#: What a CHW may select on the community report form, in display order.
REPORTABLE_CATEGORIES: tuple[str, ...] = tuple(
    choice for choice in SignalCategory.values if choice not in SYSTEM_CATEGORIES
)

#: The four categories the original build stored as dedicated columns on
#: CommunityReport. Kept in sync so pre-existing rows and any code reading
#: those fields keep working.
LEGACY_REPORT_FIELDS: dict[str, str] = {
    "fever_cases": SignalCategory.FEVER,
    "respiratory_cases": SignalCategory.RESPIRATORY,
    "diarrhoeal_cases": SignalCategory.DIARRHOEAL,
    "other_cases": SignalCategory.OTHER,
}

#: Categories that require the worker to describe what they observed, because
#: the label alone does not say enough for an officer to act on.
DESCRIPTION_REQUIRED_CATEGORIES = frozenset(
    {
        SignalCategory.OTHER,
        SignalCategory.OTHER_COMMUNICABLE,
        SignalCategory.OTHER_NON_COMMUNICABLE,
        SignalCategory.POISONING,
    }
)


class SourceKind(models.TextChoices):
    CHW = "CHW", "Community Health Worker reports"
    PHC = "PHC", "PHC aggregate trends"
    PHARMACY = "PHARMACY", "Pharmacy category trends"
    SCHOOL = "SCHOOL", "School absenteeism"
    WEATHER = "WEATHER", "Weather / environment"
    LAB = "LAB", "Laboratory evidence"
    RURALCARE_AGGREGATE = "RURALCARE_AGGREGATE", "Aggregated RuralCare signal"


class DataQuality(models.TextChoices):
    GOOD = "GOOD", "Good"
    PARTIAL = "PARTIAL", "Partial"
    POOR = "POOR", "Poor"
    MISSING = "MISSING", "Not submitted"


class EvidenceStatus(models.TextChoices):
    ANOMALY_DETECTED = "ANOMALY_DETECTED", "Anomaly detected"
    NORMAL = "NORMAL", "Within expected range"
    SUPPORTING_CONTEXT = "SUPPORTING_CONTEXT", "Supporting context"
    CORROBORATING = "CORROBORATING", "Corroborating evidence"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA", "Insufficient data"
    NOT_REPORTED = "NOT_REPORTED", "Not reported (never treated as zero)"


class TriageLevel(models.TextChoices):
    ROUTINE = "ROUTINE", "Routine"
    CONCERNING = "CONCERNING", "Concerning"
    URGENT = "URGENT", "Urgent"


class SafetyVerdict(models.TextChoices):
    PASS = "PASS", "Pass"
    DOWNGRADE = "DOWNGRADE", "Downgrade"
    BLOCK = "BLOCK", "Block"


#: Source kinds that count as *independent corroborating* evidence for the
#: Safety Engine's two-source rule.
#:
#: Two deliberate exclusions:
#:   WEATHER — environmental context. Heavy rainfall can make a pattern more
#:     plausible, but on its own it is not evidence of a health event.
#:   RURALCARE_AGGREGATE — the same encounters partly feed the CHW and PHC
#:     streams, so counting it again would double-count one population. It is
#:     used by the Cross-Level agent as an agreement check instead, where it
#:     adjusts confidence rather than the source count.
CORROBORATING_SOURCE_KINDS = frozenset(
    {
        SourceKind.CHW,
        SourceKind.PHC,
        SourceKind.PHARMACY,
        SourceKind.SCHOOL,
        SourceKind.LAB,
    }
)

CONTEXT_SOURCE_KINDS = frozenset(
    {SourceKind.WEATHER, SourceKind.RURALCARE_AGGREGATE}
)

#: Language the platform is never permitted to emit (Section 41 + Safety R6).
#: Checked deterministically against generated narrative before release.
PROHIBITED_OUTPUT_TERMS = (
    "outbreak confirmed",
    "confirmed outbreak",
    "outbreak declared",
    "declare an outbreak",
    "we declare",
    "epidemic confirmed",
    "diagnosis is",
    "diagnosed with",
    "the patient has dengue",
    "confirmed case of",
    "guaranteed",
)

#: Display labels for the demonstration areas.
#:
#: Kept here rather than as a database column: "Village A" is a label for the
#: demo environment, not a property of a real village, and adding a schema
#: field for it would be a change the feature does not need. Anything not
#: listed falls back to its own name.
DEMO_VILLAGE_LABELS: dict[str, str] = {
    "KVL": "Village A",
    "ARY": "Village B",
}


def village_label(code: str, fallback: str = "") -> str:
    return DEMO_VILLAGE_LABELS.get(code, fallback or code)


MEDICAL_DISCLAIMER = (
    "Decision-support only. Does not replace professional medical care. "
    "Human approval required."
)

DATA_NOTICE = "SYNTHETIC DEMONSTRATION DATA — NOT REAL PATIENT DATA."
