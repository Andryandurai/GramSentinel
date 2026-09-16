"""Deterministic Pregnancy Safety / Follow-up rules — never overridden by the
AI guidance agent (task §12/§37). The LLM may explain a flag raised here; it
cannot suppress, soften, or add one.

Mirrors the shape of `simulation.safety.rules`/`safety.rules`: a fixed set of
named rules, each independently evaluated against already-known facts (never
re-deriving a triage judgement, never consulting an LLM).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from .models import PicmeRchStatus, PregnancyStatus
from .questionnaire import TARGET_VISIT_COUNT, warning_sign_keys

URGENT_CLINICAL_REVIEW = "URGENT_CLINICAL_REVIEW"
FOLLOW_UP_OVERDUE = "FOLLOW_UP_OVERDUE"
MISSING_NEXT_CHECKUP = "MISSING_NEXT_CHECKUP"
LOW_VISIT_COMPLETION_FOR_STAGE = "LOW_VISIT_COMPLETION_FOR_STAGE"
ANC_4PLUS_TARGET_NOT_YET_REACHED = "ANC_4PLUS_TARGET_NOT_YET_REACHED"
MISSING_PICME = "MISSING_PICME"
MISSING_INFORMATION = "MISSING_INFORMATION"

RULE_LABELS: dict[str, str] = {
    URGENT_CLINICAL_REVIEW: "Urgent clinical review recommended",
    FOLLOW_UP_OVERDUE: "Follow-up overdue",
    MISSING_NEXT_CHECKUP: "Next check-up date not recorded",
    LOW_VISIT_COMPLETION_FOR_STAGE: "Fewer visits than expected for this stage",
    ANC_4PLUS_TARGET_NOT_YET_REACHED: "4+ ANC visits target not yet reached",
    MISSING_PICME: "PICME/RCH ID not yet recorded",
    MISSING_INFORMATION: "Key pregnancy information missing",
}

#: Rough, clearly-labelled MONITORING windows only — never a clinical
#: determination of gestational risk. Used only when LMP is actually known
#: (task §17: "if the project cannot safely determine gestational stage, use
#: '4+ ANC visits target not yet reached' rather than claiming overdue").
_STAGE_WEEK_BOUNDS: tuple[tuple[int, int], ...] = (
    (13, 1),  # < 13 weeks: Visit 1 expected
    (26, 2),  # < 26 weeks: Visit 1-2 expected
    (36, 3),  # < 36 weeks: Visit 1-3 expected
)


def expected_visits_for_gestational_week(weeks: int) -> int:
    for bound, expected in _STAGE_WEEK_BOUNDS:
        if weeks < bound:
            return expected
    return TARGET_VISIT_COUNT


def warning_signs_in_responses(visit_number: int, responses: dict[str, str]) -> list[str]:
    """Question keys this visit's response set answered YES to, restricted
    to the fixed warning-sign questions for that visit (`pregnancy
    .questionnaire`). Never inspects free text — only the controlled
    YES/NO/UNKNOWN vocabulary."""

    signs = warning_sign_keys(visit_number)
    return sorted(key for key, value in responses.items() if key in signs and value == "YES")


def evaluate_profile_rules(
    *,
    status: str,
    next_checkup_date: dt.date | None,
    lmp: dt.date | None,
    picme_rch_status: str,
    completed_visit_count: int,
    latest_warning_signs: list[str],
    today: dt.date | None = None,
) -> list[dict[str, Any]]:
    """The authoritative flag list for one pregnancy profile. Order is
    priority order — urgent first — but every consumer should treat this as
    a set, not assume only the first entry matters."""

    today = today or dt.date.today()
    flags: list[dict[str, Any]] = []

    if latest_warning_signs:
        flags.append(
            {
                "rule": URGENT_CLINICAL_REVIEW,
                "label": RULE_LABELS[URGENT_CLINICAL_REVIEW],
                "detail": (
                    "Prompt evaluation by a qualified healthcare professional "
                    "is required for the reported warning sign(s). Do not "
                    "wait for the next scheduled visit."
                ),
                "warning_signs": latest_warning_signs,
            }
        )

    if status == PregnancyStatus.ACTIVE:
        if next_checkup_date is None:
            flags.append(
                {
                    "rule": MISSING_NEXT_CHECKUP,
                    "label": RULE_LABELS[MISSING_NEXT_CHECKUP],
                    "detail": "No next check-up date has been recorded for this pregnancy.",
                }
            )
        elif next_checkup_date < today:
            flags.append(
                {
                    "rule": FOLLOW_UP_OVERDUE,
                    "label": RULE_LABELS[FOLLOW_UP_OVERDUE],
                    "detail": (
                        f"The scheduled check-up on {next_checkup_date.isoformat()} "
                        "has passed."
                    ),
                    "overdue_by_days": (today - next_checkup_date).days,
                }
            )

    if lmp is not None:
        weeks = (today - lmp).days // 7
        expected = expected_visits_for_gestational_week(weeks)
        if completed_visit_count < expected:
            flags.append(
                {
                    "rule": LOW_VISIT_COMPLETION_FOR_STAGE,
                    "label": RULE_LABELS[LOW_VISIT_COMPLETION_FOR_STAGE],
                    "detail": (
                        f"{completed_visit_count} of an expected {expected} "
                        f"visit(s) completed for approximately {weeks} weeks "
                        "into this pregnancy."
                    ),
                    "gestational_weeks": weeks,
                    "expected_visit_count": expected,
                }
            )
    elif completed_visit_count < TARGET_VISIT_COUNT:
        flags.append(
            {
                "rule": ANC_4PLUS_TARGET_NOT_YET_REACHED,
                "label": RULE_LABELS[ANC_4PLUS_TARGET_NOT_YET_REACHED],
                "detail": (
                    f"{completed_visit_count} of the {TARGET_VISIT_COUNT}+ ANC "
                    "visit monitoring target completed. Gestational stage is "
                    "not recorded, so this is a coverage target, not an "
                    "overdue determination."
                ),
            }
        )

    if picme_rch_status != PicmeRchStatus.AVAILABLE:
        flags.append(
            {
                "rule": MISSING_PICME,
                "label": RULE_LABELS[MISSING_PICME],
                "detail": "No PICME/RCH ID is recorded as available for this pregnancy.",
            }
        )

    return flags


def has_urgent_flag(flags: list[dict[str, Any]]) -> bool:
    return any(f["rule"] == URGENT_CLINICAL_REVIEW for f in flags)


def has_overdue_flag(flags: list[dict[str, Any]]) -> bool:
    return any(f["rule"] == FOLLOW_UP_OVERDUE for f in flags)
