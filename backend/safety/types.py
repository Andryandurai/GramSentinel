"""Structured records the Safety Engine operates on.

Deliberately plain dataclasses rather than Django models: the engine must be
testable without a database, and it must never be tempted to re-query or
reinterpret anything. It sees exactly what it is given.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RuleSeverity(str, Enum):
    #: Failing this rule blocks the finding outright.
    BLOCKING = "BLOCKING"
    #: Failing this rule downgrades the finding and demands verification.
    DOWNGRADING = "DOWNGRADING"
    #: Recorded for the audit trail; does not change the verdict on its own.
    ADVISORY = "ADVISORY"


@dataclass(frozen=True)
class EvidenceRecord:
    """One source's structured finding, as produced by a signal agent."""

    source_kind: str
    source_name: str
    category: str
    village_code: str
    cluster: str
    week_label: str
    period_start: dt.date
    period_end: dt.date
    status: str
    data_quality: str
    baseline: float | None = None
    current_value: float | None = None
    change_pct: float | None = None
    unit: str = ""
    is_corroborating: bool = False
    is_reported: bool = True
    explanation: str = ""
    produced_by_agent: str = ""

    @property
    def is_anomalous(self) -> bool:
        return self.status in {"ANOMALY_DETECTED", "CORROBORATING"}


@dataclass(frozen=True)
class Hypothesis:
    """The only output type the reasoning layers are permitted to produce."""

    kind: str  # must be "correlation_hypothesis"
    cluster: str
    category: str
    week_label: str
    narrative: str
    contributing: tuple[EvidenceRecord, ...] = ()
    cross_level_verdict: str = "SILENT"
    cross_level_statement: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IndividualCase:
    """Individual-level input to the red-flag rule set."""

    symptoms: tuple[str, ...]
    duration_days: int = 0
    age_months: int | None = None
    temperature_c: float | None = None
    pulse_bpm: int | None = None
    respiratory_rate: int | None = None
    systolic_bp: int | None = None
    spo2: int | None = None
    model_triage_level: str = "ROUTINE"


@dataclass(frozen=True)
class RuleResult:
    code: str
    name: str
    passed: bool
    severity: RuleSeverity
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "passed": self.passed,
            "severity": self.severity.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class SafetyResult:
    verdict: str  # PASS | DOWNGRADE | BLOCK
    passed: bool
    status: str
    rules: tuple[RuleResult, ...]
    reasons: tuple[str, ...]
    severity: str | None = None
    confidence: float = 0.0
    corroborating_source_count: int = 0
    engine_version: str = "1.0.0"
    requires_human_review: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "passed": self.passed,
            "status": self.status,
            "rules_checked": [r.to_dict() for r in self.rules],
            "reasons": list(self.reasons),
            "severity": self.severity,
            "confidence": self.confidence,
            "corroborating_source_count": self.corroborating_source_count,
            "engine_version": self.engine_version,
            "requires_human_review": self.requires_human_review,
        }
