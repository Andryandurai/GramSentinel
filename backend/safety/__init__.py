"""Deterministic, non-LLM safety verification.

Nothing in this package imports an LLM client, and nothing in it consults model
output. It operates only on structured evidence records. It is ordinary Python
that a reader can check line by line.
"""

from .engine import SafetyEngine, ENGINE_VERSION
from .types import (
    EvidenceRecord,
    Hypothesis,
    IndividualCase,
    RuleResult,
    RuleSeverity,
    SafetyResult,
)

__all__ = [
    "SafetyEngine",
    "ENGINE_VERSION",
    "EvidenceRecord",
    "Hypothesis",
    "IndividualCase",
    "RuleResult",
    "RuleSeverity",
    "SafetyResult",
]
