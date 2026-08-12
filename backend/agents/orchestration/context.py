"""Shared context and the audit trail for one orchestration run.

Every agent invocation is appended here in order, with what it received and
what it produced. That record is what the officer's Evidence View and the
`/api/alerts/{id}/evidence/` payload are built from — the handoffs are not
described, they are shown.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from agents.base import AgentResult

logger = logging.getLogger("gramsentinel.orchestrator")


@dataclass
class OrchestrationContext:
    """Carried through a run: scope, shared state, and the ordered trace."""

    run_id: uuid.UUID = field(default_factory=uuid.uuid4)
    village_code: str = ""
    village_name: str = ""
    cluster: str = ""
    week_label: str = ""
    scope: str = "COMMUNITY"
    shared: dict[str, Any] = field(default_factory=dict)
    trace: list[AgentResult] = field(default_factory=list)
    stage_log: list[str] = field(default_factory=list)

    def record(self, result: AgentResult) -> AgentResult:
        self.trace.append(result)
        logger.info(
            "[ORCHESTRATOR] %s -> %s (%s)",
            result.stage,
            result.agent_name,
            result.status,
        )
        return result

    def begin_stage(self, stage: str) -> None:
        self.stage_log.append(stage)
        logger.info("[ORCHESTRATOR] === STAGE: %s ===", stage)

    @property
    def used_llm(self) -> bool:
        return any(r.used_llm for r in self.trace)

    @property
    def failed_agents(self) -> list[str]:
        return [r.agent_name for r in self.trace if r.status != "OK"]

    def trace_as_dicts(self) -> list[dict[str, Any]]:
        return [
            {"sequence": index, **result.to_dict()}
            for index, result in enumerate(self.trace)
        ]

    def flow_diagram(self) -> list[str]:
        """A readable rendering of the handoff chain, for logs and the UI."""
        return [f"{r.stage} -> {r.agent_name}" for r in self.trace]
