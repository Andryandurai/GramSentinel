"""The Deterministic Safety Engine.

Structurally the last thing between a hypothesis and a human. It receives
structured evidence, applies fixed rules, and returns PASS / DOWNGRADE / BLOCK
with a per-rule record explaining exactly which rule produced the verdict.

Properties this file is responsible for upholding:

* Deterministic  — identical input always yields identical output.
* Independent    — no LLM client is imported and no model output is consulted.
* Non-overridable— nothing here accepts a caller-supplied override or bypass.
* Auditable      — every evaluation returns all rule results, passed or failed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from . import rules as R
from .red_flags import evaluate_red_flags
from .types import (
    EvidenceRecord,
    Hypothesis,
    IndividualCase,
    RuleResult,
    RuleSeverity,
    SafetyResult,
)

logger = logging.getLogger("gramsentinel.safety")

ENGINE_VERSION = "1.0.0"

VERDICT_PASS = "PASS"
VERDICT_DOWNGRADE = "DOWNGRADE"
VERDICT_BLOCK = "BLOCK"

STATUS_REQUIRES_HUMAN_REVIEW = "REQUIRES_HUMAN_REVIEW"
STATUS_REQUIRES_VERIFICATION = "REQUIRES_VERIFICATION"
STATUS_MONITOR_ONLY = "MONITOR_ONLY"
STATUS_BLOCKED = "BLOCKED"


class SafetyEngine:
    """Ordinary software. No temperature, no sampling, no variance."""

    def __init__(
        self,
        min_independent_sources: int = R.MIN_INDEPENDENT_SOURCES,
        temporal_window_days: int = R.TEMPORAL_WINDOW_DAYS,
        min_data_quality_ratio: float = R.MIN_DATA_QUALITY_RATIO,
    ) -> None:
        self.min_independent_sources = min_independent_sources
        self.temporal_window_days = temporal_window_days
        self.min_data_quality_ratio = min_data_quality_ratio

    # ------------------------------------------------------------------
    # Community scope
    # ------------------------------------------------------------------
    def evaluate_community(
        self,
        hypothesis: Hypothesis,
        records: Sequence[EvidenceRecord] | None = None,
    ) -> SafetyResult:
        records = list(records if records is not None else hypothesis.contributing)

        checks: list[RuleResult] = [
            R.rule_1_single_source_ceiling(records),
            R.rule_2_corroboration_threshold(records, self.min_independent_sources),
            R.rule_3_geographic_consistency(records),
            R.rule_4_temporal_consistency(records, self.temporal_window_days),
            R.rule_5_data_quality_sufficiency(records, self.min_data_quality_ratio),
            R.rule_6_no_automatic_outbreak_declaration(hypothesis),
            R.rule_7_human_review_required(),
            R.rule_8_missing_data_never_zero(records),
        ]

        blocking_failures = [
            c for c in checks if not c.passed and c.severity is RuleSeverity.BLOCKING
        ]
        downgrading_failures = [
            c for c in checks if not c.passed and c.severity is RuleSeverity.DOWNGRADING
        ]

        corroborating_count = len(R.corroborating(records))

        if blocking_failures:
            verdict, status = VERDICT_BLOCK, STATUS_BLOCKED
            severity = None
        elif downgrading_failures:
            verdict = VERDICT_DOWNGRADE
            severity = "LOW" if corroborating_count <= 1 else "MODERATE"
            status = (
                STATUS_MONITOR_ONLY
                if corroborating_count <= 1
                else STATUS_REQUIRES_VERIFICATION
            )
        else:
            verdict, status = VERDICT_PASS, STATUS_REQUIRES_HUMAN_REVIEW
            severity = "HIGH" if corroborating_count >= 4 else "MODERATE"

        reasons = tuple(
            f"{c.code} {c.name}: {c.detail}" for c in checks if not c.passed
        ) or (
            "All deterministic rules satisfied. Released for human review.",
        )

        result = SafetyResult(
            verdict=verdict,
            passed=verdict == VERDICT_PASS,
            status=status,
            rules=tuple(checks),
            reasons=reasons,
            severity=severity,
            confidence=self._confidence(records, checks, hypothesis, verdict),
            corroborating_source_count=corroborating_count,
            engine_version=ENGINE_VERSION,
            requires_human_review=True,
        )

        logger.info(
            "[SAFETY ENGINE] %s/%s -> %s (%s), %d corroborating source(s)",
            hypothesis.cluster,
            hypothesis.week_label,
            verdict,
            status,
            corroborating_count,
        )
        return result

    # ------------------------------------------------------------------
    # Individual scope
    # ------------------------------------------------------------------
    def evaluate_individual(self, case: IndividualCase) -> tuple[SafetyResult, list[dict]]:
        """Apply the red-flag rule set. Returns (result, triggered flags).

        A failure of R9 is the intended behaviour when a red flag is present:
        the verdict is BLOCK on the *model's* conclusion, and the escalation is
        forced.
        """

        triggered, rule9 = evaluate_red_flags(case)
        checks = [rule9, R.rule_7_human_review_required()]

        if triggered:
            verdict = VERDICT_BLOCK
            status = "ESCALATION_FORCED"
            reasons = (
                f"R9 Individual red-flag escalation: {rule9.detail}",
            )
        else:
            verdict = VERDICT_PASS
            status = STATUS_REQUIRES_HUMAN_REVIEW
            reasons = (
                "No red-flag combination present. Output released to the health "
                "worker as decision support requiring their judgement.",
            )

        result = SafetyResult(
            verdict=verdict,
            passed=not triggered,
            status=status,
            rules=tuple(checks),
            reasons=reasons,
            severity="URGENT" if triggered else None,
            confidence=0.0,
            corroborating_source_count=0,
            engine_version=ENGINE_VERSION,
            requires_human_review=True,
        )
        return result, triggered

    # ------------------------------------------------------------------
    def _confidence(
        self,
        records: Sequence[EvidenceRecord],
        checks: Sequence[RuleResult],
        hypothesis: Hypothesis,
        verdict: str,
    ) -> float:
        """A transparent arithmetic score, not a learned one.

        Deliberately capped below 1.0: the platform never expresses certainty
        about a community health pattern.
        """

        if verdict == VERDICT_BLOCK:
            return 0.0

        hits = R.corroborating(records)
        score = 0.20 + 0.15 * min(len(hits), 4)

        if any(r.source_kind == "LAB" for r in hits):
            score += 0.10  # laboratory confirmation is high-specificity evidence

        if hypothesis.cross_level_verdict == "CONSISTENT":
            score += 0.15
        elif hypothesis.cross_level_verdict == "CONTRADICTORY":
            score -= 0.20

        degraded = [r for r in hits if r.data_quality not in R.ACCEPTABLE_QUALITY]
        score -= 0.08 * len(degraded)

        for check in checks:
            if not check.passed and check.severity is RuleSeverity.DOWNGRADING:
                score -= 0.15

        return round(max(0.0, min(score, 0.95)), 2)
