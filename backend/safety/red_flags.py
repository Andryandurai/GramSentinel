"""Individual-level red-flag rule set (Safety Rule 9).

A fixed, non-overridable set of symptom/vital combinations that force
escalation regardless of what the model concluded. The LLM cannot suppress
these: this module never reads model output except to record what it was
overriding.

This is decision support for a health worker, not a diagnosis and not a
treatment instruction.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .types import IndividualCase, RuleResult, RuleSeverity


@dataclass(frozen=True)
class RedFlag:
    code: str
    label: str
    predicate: Callable[[IndividualCase], bool]
    rationale: str


def _has(case: IndividualCase, *names: str) -> bool:
    present = {s.lower() for s in case.symptoms}
    return any(name in present for name in names)


RED_FLAGS: tuple[RedFlag, ...] = (
    RedFlag(
        "RF_ALTERED_CONSCIOUSNESS",
        "Altered consciousness or unresponsiveness",
        lambda c: _has(c, "altered_consciousness", "unconscious", "confusion", "drowsy"),
        "Reduced consciousness needs same-day professional evaluation.",
    ),
    RedFlag(
        "RF_SEIZURE",
        "Seizure",
        lambda c: _has(c, "seizure", "convulsion", "fits"),
        "Seizure activity requires urgent professional evaluation.",
    ),
    RedFlag(
        "RF_FEVER_NECK_STIFFNESS",
        "Fever with neck stiffness",
        lambda c: _has(c, "fever", "high_fever") and _has(c, "neck_stiffness", "stiff_neck"),
        "This combination is on the urgent-referral list.",
    ),
    RedFlag(
        "RF_LOW_SPO2",
        "Oxygen saturation below 92%",
        lambda c: c.spo2 is not None and c.spo2 < 92,
        "Hypoxia requires urgent evaluation.",
    ),
    RedFlag(
        "RF_HIGH_RESP_RATE",
        "Respiratory rate above 30/min",
        lambda c: c.respiratory_rate is not None and c.respiratory_rate > 30,
        "Marked tachypnoea requires urgent evaluation.",
    ),
    RedFlag(
        "RF_LOW_BP",
        "Systolic blood pressure below 90 mmHg",
        lambda c: c.systolic_bp is not None and c.systolic_bp < 90,
        "Hypotension requires urgent evaluation.",
    ),
    RedFlag(
        "RF_VERY_HIGH_FEVER",
        "Temperature 40.0 °C or above",
        lambda c: c.temperature_c is not None and c.temperature_c >= 40.0,
        "Very high recorded temperature requires urgent evaluation.",
    ),
    RedFlag(
        "RF_CHEST_PAIN_BREATHLESSNESS",
        "Chest pain with breathlessness",
        lambda c: _has(c, "chest_pain") and _has(c, "breathlessness", "shortness_of_breath"),
        "This combination is on the urgent-referral list.",
    ),
    RedFlag(
        "RF_BLEEDING",
        "Active or unexplained bleeding",
        lambda c: _has(c, "bleeding", "bleeding_gums", "blood_in_stool", "blood_in_vomit"),
        "Bleeding requires urgent evaluation.",
    ),
    RedFlag(
        "RF_SEVERE_DEHYDRATION",
        "Diarrhoea with signs of severe dehydration",
        lambda c: _has(c, "diarrhoea") and _has(c, "severe_dehydration", "unable_to_drink", "sunken_eyes"),
        "Severe dehydration requires urgent evaluation.",
    ),
    RedFlag(
        "RF_YOUNG_INFANT_FEVER",
        "Fever in an infant under 2 months",
        lambda c: (
            c.age_months is not None
            and c.age_months < 2
            and _has(c, "fever", "high_fever")
        ),
        "Fever at this age is escalated by rule regardless of other findings.",
    ),
    RedFlag(
        "RF_PROLONGED_FEVER",
        "Fever persisting 7 days or longer",
        lambda c: _has(c, "fever", "high_fever") and c.duration_days >= 7,
        "Prolonged fever requires professional evaluation.",
    ),
)


def evaluate_red_flags(case: IndividualCase) -> tuple[list[dict], RuleResult]:
    """Return the triggered flags and the Rule 9 result.

    `passed=True` here means 'no red flag present'. A failure is not an error —
    it is the rule set doing its job and forcing an escalation.
    """

    triggered = [
        {"code": flag.code, "label": flag.label, "rationale": flag.rationale}
        for flag in RED_FLAGS
        if flag.predicate(case)
    ]

    if triggered:
        labels = ", ".join(f["label"] for f in triggered)
        detail = (
            f"Red-flag combination present ({labels}). Escalation to URGENT is "
            "forced by the deterministic rule set and cannot be suppressed by "
            f"the model, whose own assessment was {case.model_triage_level}."
        )
    else:
        detail = "No red-flag combination detected in the fixed rule set."

    result = RuleResult(
        code="R9",
        name="Individual red-flag escalation",
        passed=not triggered,
        severity=RuleSeverity.BLOCKING,
        detail=detail,
    )
    return triggered, result
