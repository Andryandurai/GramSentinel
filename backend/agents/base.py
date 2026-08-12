"""Shared agent contract.

Every agent takes a structured input and returns a structured output plus a
short input summary for the audit trail. Nothing returns prose as its primary
payload.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("gramsentinel.agents")


@dataclass
class AgentResult:
    agent_name: str
    layer: str
    stage: str
    output: dict[str, Any]
    input_summary: dict[str, Any] = field(default_factory=dict)
    status: str = "OK"
    duration_ms: float = 0.0
    used_llm: bool = False
    #: Human-readable label, purpose and result. Derived from the real output
    #: above — this is what worker-facing screens render instead of raw JSON.
    display_name: str = ""
    purpose: str = ""
    result_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent_name,
            "display_name": self.display_name or self.agent_name,
            "purpose": self.purpose,
            "result_summary": self.result_summary,
            "layer": self.layer,
            "stage": self.stage,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 2),
            "used_llm": self.used_llm,
            "input_summary": self.input_summary,
            "output": self.output,
        }


class BaseAgent(ABC):
    name: str = "UnnamedAgent"
    #: Plain-language name and one-line purpose shown to a health worker.
    display_name: str = ""
    purpose: str = ""
    layer: str = "GENERIC"
    stage: str = "DOMAIN_REASONING"

    @abstractmethod
    def handle(self, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        """Do the agent's one job. Returns its structured output."""

    def summarise_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        """What to record about the input. Overridden to avoid logging PII."""
        return {"keys": sorted(payload.keys())}

    def summarise_output(self, output: dict[str, Any]) -> str:
        """One plain sentence describing what this agent actually produced.

        Overridden per agent so the sentence reflects the real result rather
        than a generic placeholder. The agent knows what it did, so the
        sentence is written here rather than reconstructed in the frontend.
        """
        return "Completed."

    def run(self, payload: dict[str, Any], context: Any = None) -> AgentResult:
        started = time.perf_counter()
        used_llm = False
        try:
            output = self.handle(payload, context)
            status = "OK"
            used_llm = bool(output.pop("_used_llm", False))
        except Exception as exc:  # noqa: BLE001 - agent failure must be contained
            logger.warning("[AGENT %s] failed: %s", self.name, exc)
            output = {"error": str(exc)}
            status = "FAILED"

        duration_ms = (time.perf_counter() - started) * 1000

        if status == "OK":
            try:
                result_summary = self.summarise_output(output)
            except Exception:  # noqa: BLE001 - a summary must never break a run
                result_summary = "Completed."
        else:
            result_summary = "This step could not be completed."

        result = AgentResult(
            agent_name=self.name,
            layer=self.layer,
            stage=self.stage,
            output=output,
            input_summary=self.summarise_input(payload),
            status=status,
            duration_ms=duration_ms,
            used_llm=used_llm,
            display_name=self.display_name or self.name,
            purpose=self.purpose,
            result_summary=result_summary,
        )
        logger.info(
            "[AGENT %s] %s in %.1fms", self.name, status, duration_ms
        )
        return result
