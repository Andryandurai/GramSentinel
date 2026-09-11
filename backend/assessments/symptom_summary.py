"""Community symptom summary for the CHW / PHC worker's own dashboard.

What this is: a count of **people with reported symptoms**, derived from the
assessments the worker has already recorded through New Assessment. What it is
not: confirmed cases, diagnosed patients or confirmed diseases. Nothing here
interprets a symptom — it only counts what was written down.

Two rules make the counts honest:

  * A person is counted once per symptom group, however many symptoms or
    assessments they have. One patient with fever *and* headache adds one to
    Fever and one to Headache, but only one to the total people assessed.
  * The groups are built from the taxonomy the agent chain already uses
    (`agents.ruralcare.vocabulary.SYNDROME_GROUPS`), so a symptom recorded in
    New Assessment lands in the same place here as it does everywhere else.

Anything the taxonomy does not place — including a symptom the worker typed in
their own words under "Other" — is counted under Other, so nothing recorded is
silently dropped from the summary.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from agents.ruralcare.vocabulary import SYNDROME_GROUPS
from core.constants import SignalCategory

OTHER_KEY = "OTHER"

#: Diarrhoeal/gastrointestinal presentation. The agent chain's existing
#: gastrointestinal group plus bloody stool, which is recorded separately in
#: the taxonomy but reads as the same reported problem to a worker.
_DIARRHOEAL = tuple(SYNDROME_GROUPS["gastrointestinal"]) + ("blood_in_stool",)

#: Display order is the order a worker reads them in. `report_category` is the
#: existing community-report category this group corresponds to, or None where
#: the community vocabulary has no equivalent (headache is a symptom, not a
#: reportable community signal category — so it is shown but never prefilled).
SYMPTOM_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "key": "FEVER",
        "label": "Fever",
        "symptoms": tuple(SYNDROME_GROUPS["febrile"]),
        "report_category": SignalCategory.FEVER.value,
    },
    {
        "key": "RESPIRATORY",
        "label": "Respiratory symptoms",
        "symptoms": tuple(SYNDROME_GROUPS["respiratory"]),
        "report_category": SignalCategory.RESPIRATORY.value,
    },
    {
        "key": "HEADACHE",
        "label": "Headache",
        "symptoms": ("headache",),
        "report_category": None,
    },
    {
        "key": "DIARRHOEAL",
        "label": "Diarrhoeal symptoms",
        "symptoms": _DIARRHOEAL,
        "report_category": SignalCategory.DIARRHOEAL.value,
    },
    {
        "key": "SKIN",
        "label": "Skin-related symptoms",
        "symptoms": ("rash",),
        "report_category": SignalCategory.SKIN.value,
    },
    {
        "key": OTHER_KEY,
        "label": "Other",
        "symptoms": (),
        "report_category": SignalCategory.OTHER.value,
    },
)

_GROUP_BY_KEY = {group["key"]: group for group in SYMPTOM_GROUPS}

_CODE_TO_GROUP: dict[str, str] = {
    code: group["key"] for group in SYMPTOM_GROUPS for code in group["symptoms"]
}

SUMMARY_NOTE = (
    "People with reported symptoms, counted from the assessments recorded in "
    "this area. Reported symptoms only — not confirmed cases or diagnoses."
)

OTHER_HINT = "Includes symptoms recorded under “Other” and anything not listed above."


def group_for_symptom(raw: Any) -> str:
    """Which summary group one recorded symptom code belongs to."""

    code = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not code:
        return OTHER_KEY
    return _CODE_TO_GROUP.get(code, OTHER_KEY)


def groups_for_assessment(symptoms: Any, other_symptom_text: Any = "") -> set[str]:
    """The distinct summary groups one recorded assessment contributes to."""

    keys: set[str] = set()

    # `symptoms` is a JSON column: tolerate anything that is not a clean list
    # rather than letting a malformed row break a whole dashboard.
    if isinstance(symptoms, (list, tuple, set)):
        for entry in symptoms:
            keys.add(group_for_symptom(entry))
    elif isinstance(symptoms, str) and symptoms.strip():
        keys.add(group_for_symptom(symptoms))

    if str(other_symptom_text or "").strip():
        keys.add(OTHER_KEY)

    return keys


def summarise_assessments(rows: Iterable[Sequence[Any]]) -> dict[str, Any]:
    """Aggregate `(patient_id, symptoms, other_symptom_text)` rows.

    The caller is responsible for scoping the rows — village permissions first,
    then the selected week — so this function never widens what is counted.
    """

    per_person: dict[Any, set[str]] = {}
    assessment_count = 0
    described_other = 0

    for row in rows:
        try:
            patient_id, symptoms, other_text = row[0], row[1], row[2]
        except (IndexError, TypeError):
            continue

        assessment_count += 1
        if str(other_text or "").strip():
            described_other += 1

        bucket = per_person.setdefault(patient_id, set())
        bucket |= groups_for_assessment(symptoms, other_text)

    counts = {group["key"]: 0 for group in SYMPTOM_GROUPS}
    for keys in per_person.values():
        for key in keys:
            counts[key] = counts.get(key, 0) + 1

    total_people = len(per_person)

    result_rows = [
        {
            "key": group["key"],
            "label": group["label"],
            "count": counts.get(group["key"], 0),
            "report_category": group["report_category"],
            "hint": OTHER_HINT if group["key"] == OTHER_KEY else "",
        }
        for group in SYMPTOM_GROUPS
        if counts.get(group["key"], 0) > 0
    ]

    return {
        "rows": result_rows,
        "total_people_assessed": total_people,
        "assessment_count": assessment_count,
        "described_other_count": described_other,
        "is_empty": total_people == 0,
        "empty_message": "No assessments recorded for this period yet.",
        "note": SUMMARY_NOTE,
        # What the community report form would be prefilled with. Only groups
        # that map onto an existing community category are offered; the worker
        # still reviews and submits the report themselves.
        "report_prefill": [
            {
                "category": _GROUP_BY_KEY[row["key"]]["report_category"],
                "case_count": row["count"],
                "label": row["label"],
            }
            for row in result_rows
            if _GROUP_BY_KEY[row["key"]]["report_category"]
        ],
    }
