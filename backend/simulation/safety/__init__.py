"""Phase 6 — the deterministic simulation Safety Engine.

Physically separate from every other package in this project (task §4):
nothing here imports an LLM client, and nothing outside `simulation`
imports from here except `simulation.services` (persistence) and
`simulation.views` (the `/safety/` endpoint). See `engine.py` and
`rules.py` for the actual logic.
"""

from .engine import SafetyEngine, finalize_evidence_strength
from .rules import RULE_ORDER, RULES, SafetyContext, SafetyRuleResult

__all__ = [
    "SafetyEngine",
    "finalize_evidence_strength",
    "RULE_ORDER",
    "RULES",
    "SafetyContext",
    "SafetyRuleResult",
]
