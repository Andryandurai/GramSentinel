"""The rules themselves — one function per rule, each returning a RuleResult.

Every rule is an explicit written threshold, not a learned judgement. Same
evidence in, same result out, every time. No sampling, no temperature, no
model call anywhere in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from .types import EvidenceRecord, Hypothesis, RuleResult, RuleSeverity

#: Defaults; the engine overrides these from settings at construction time so
#: thresholds are configurable without editing rule logic.
MIN_INDEPENDENT_SOURCES = 2
TEMPORAL_WINDOW_DAYS = 10
MIN_DATA_QUALITY_RATIO = 0.6

ACCEPTABLE_QUALITY = frozenset({"GOOD", "PARTIAL"})

PROHIBITED_TERMS = (
    "outbreak confirmed",
    "confirmed outbreak",
    "outbreak declared",
    "declare an outbreak",
    "declaring an outbreak",
    "epidemic confirmed",
    "diagnosed with",
    "the diagnosis is",
    "confirmed case of",
    "guaranteed",
    "definitely",
)

PERMITTED_HYPOTHESIS_KINDS = frozenset({"correlation_hypothesis"})


def corroborating(records: Sequence[EvidenceRecord]) -> list[EvidenceRecord]:
    """Anomalous records from source kinds that count as independent evidence.

    Weather is excluded by construction: `is_corroborating` is set False for it
    upstream, because heavy rainfall is context, not evidence of a health event.
    """

    return [r for r in records if r.is_corroborating and r.is_anomalous]


def rule_1_single_source_ceiling(
    records: Sequence[EvidenceRecord],
) -> RuleResult:
    """R1 — one anomalous source alone cannot produce a high-confidence alert."""

    count = len(corroborating(records))
    passed = count != 1
    if count == 1:
        detail = (
            "Exactly one independent source is anomalous. A single source can be "
            "wrong, mistyped, or locally explained; confidence is capped and the "
            "finding cannot be raised as high priority."
        )
    elif count == 0:
        detail = "No independent source is anomalous; nothing to escalate."
    else:
        detail = f"{count} independent sources are anomalous, so the ceiling does not apply."
    return RuleResult(
        code="R1",
        name="Single-source ceiling",
        passed=passed,
        severity=RuleSeverity.DOWNGRADING,
        detail=detail,
    )


def rule_2_corroboration_threshold(
    records: Sequence[EvidenceRecord],
    minimum: int = MIN_INDEPENDENT_SOURCES,
) -> RuleResult:
    """R2 — a high-impact alert requires at least two independent sources."""

    hits = corroborating(records)
    count = len(hits)
    passed = count >= minimum
    kinds = sorted({r.source_kind for r in hits})
    detail = (
        f"{count} independent corroborating source(s) "
        f"({', '.join(kinds) if kinds else 'none'}); minimum required is {minimum}."
    )
    return RuleResult(
        code="R2",
        name="Corroboration threshold",
        passed=passed,
        severity=RuleSeverity.DOWNGRADING,
        detail=detail,
    )


def rule_3_geographic_consistency(
    records: Sequence[EvidenceRecord],
) -> RuleResult:
    """R3 — contributing signals must belong to the same geographic cluster."""

    clusters = {r.cluster for r in records if r.is_anomalous}
    passed = len(clusters) <= 1
    if passed:
        detail = (
            f"All anomalous signals fall in {next(iter(clusters))}."
            if clusters
            else "No anomalous signals to place geographically."
        )
    else:
        detail = (
            "Anomalous signals span more than one cluster "
            f"({', '.join(sorted(clusters))}). A trend in one block does not "
            "corroborate a trend in another."
        )
    return RuleResult(
        code="R3",
        name="Geographic consistency",
        passed=passed,
        severity=RuleSeverity.DOWNGRADING,
        detail=detail,
    )


def rule_4_temporal_consistency(
    records: Sequence[EvidenceRecord],
    window_days: int = TEMPORAL_WINDOW_DAYS,
) -> RuleResult:
    """R4 — contributing signals must fall inside the defined time window."""

    anomalous = [r for r in records if r.is_anomalous]
    if not anomalous:
        return RuleResult(
            code="R4",
            name="Temporal window consistency",
            passed=True,
            severity=RuleSeverity.DOWNGRADING,
            detail="No anomalous signals to place in time.",
        )

    earliest = min(r.period_start for r in anomalous)
    latest = max(r.period_end for r in anomalous)
    span = (latest - earliest).days
    passed = span <= window_days
    detail = (
        f"Anomalous signals span {span} day(s) ({earliest} to {latest}); "
        f"the defined window is {window_days} day(s)."
    )
    if not passed:
        detail += " Signals separated by this much are not evidence of one event."
    return RuleResult(
        code="R4",
        name="Temporal window consistency",
        passed=passed,
        severity=RuleSeverity.DOWNGRADING,
        detail=detail,
    )


def rule_5_data_quality_sufficiency(
    records: Sequence[EvidenceRecord],
    min_ratio: float = MIN_DATA_QUALITY_RATIO,
) -> RuleResult:
    """R5 — poor or insufficient data reduces confidence or forces verification."""

    hits = corroborating(records)
    if not hits:
        return RuleResult(
            code="R5",
            name="Data quality sufficiency",
            passed=False,
            severity=RuleSeverity.DOWNGRADING,
            detail="No corroborating evidence of any quality to assess.",
        )

    usable = [r for r in hits if r.data_quality in ACCEPTABLE_QUALITY]
    ratio = len(usable) / len(hits)
    degraded = sorted(
        {r.source_kind for r in hits if r.data_quality not in ACCEPTABLE_QUALITY}
    )
    passed = ratio >= min_ratio
    detail = (
        f"{len(usable)}/{len(hits)} corroborating sources have acceptable data "
        f"quality (ratio {ratio:.2f}, minimum {min_ratio:.2f})."
    )
    if degraded:
        detail += f" Degraded: {', '.join(degraded)}."
    if not passed:
        detail += " A conclusion drawn from incomplete submissions is not safe."
    return RuleResult(
        code="R5",
        name="Data quality sufficiency",
        passed=passed,
        severity=RuleSeverity.DOWNGRADING,
        detail=detail,
    )


def rule_6_no_automatic_outbreak_declaration(
    hypothesis: Hypothesis,
) -> RuleResult:
    """R6 — the system must never automatically declare an outbreak.

    Two checks: the hypothesis must be of the one permitted type, and its
    narrative must not contain declaratory or diagnostic language. This is the
    rule that catches an LLM narrative that overstepped.
    """

    problems: list[str] = []

    if hypothesis.kind not in PERMITTED_HYPOTHESIS_KINDS:
        problems.append(
            f"hypothesis type '{hypothesis.kind}' is not a correlation hypothesis"
        )

    haystack = f"{hypothesis.narrative} {hypothesis.cross_level_statement}".lower()
    for term in PROHIBITED_TERMS:
        if term in haystack:
            problems.append(f"prohibited phrase '{term}' present in narrative")

    passed = not problems
    detail = (
        "Output is a correlation hypothesis and contains no declaratory or "
        "diagnostic language."
        if passed
        else "Prohibited output detected: " + "; ".join(problems)
    )
    return RuleResult(
        code="R6",
        name="No automatic outbreak declaration",
        passed=passed,
        severity=RuleSeverity.BLOCKING,
        detail=detail,
    )


def rule_7_human_review_required() -> RuleResult:
    """R7 — high-impact action requires human review.

    There is no state in which the system satisfies this on its own. It is
    recorded as an obligation attached to every finding that leaves the engine.
    """

    return RuleResult(
        code="R7",
        name="Human review required",
        passed=True,
        severity=RuleSeverity.ADVISORY,
        detail=(
            "Finding is released as a request for human attention only. No "
            "automated public-health action is taken."
        ),
    )


def rule_8_missing_data_never_zero(
    records: Sequence[EvidenceRecord],
) -> RuleResult:
    """R8 — absence of a report is not absence of cases.

    Blocking, because a non-reporting source silently carrying the value 0 is a
    data-integrity defect that would make every downstream number wrong.
    """

    violations = [
        r.source_kind
        for r in records
        if not r.is_reported and r.current_value is not None
    ]
    not_reported = sorted({r.source_kind for r in records if not r.is_reported})
    passed = not violations
    if passed:
        detail = (
            f"Non-reporting sources are recorded as missing, not zero: "
            f"{', '.join(not_reported)}."
            if not_reported
            else "All contributing sources submitted data for this window."
        )
    else:
        detail = (
            "Data-integrity violation: non-reporting source(s) "
            f"{', '.join(sorted(set(violations)))} carry a numeric value. "
            "Missing data must never be interpreted as zero."
        )
    return RuleResult(
        code="R8",
        name="Missing data never treated as zero",
        passed=passed,
        severity=RuleSeverity.BLOCKING,
        detail=detail,
    )
