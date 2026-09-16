"""Pregnancy orchestration — reuses `OrchestrationContext`, the same
audit-trace machinery `RuralCareOrchestrator`/`CommunityOrchestrator` use, so
a pregnancy visit's agent trace is recorded the same way every other
encounter's is (task §9: "integrate into the existing AI assistance
architecture, do not create an unrelated second AI system").

`run_pregnancy_guidance` never calls `pregnancy.rules` itself — the caller
(views.py) evaluates the deterministic rules first and passes the result in,
so the rules layer stays the single, independently-testable authority and
this module only sequences the one explanatory agent.
"""

from __future__ import annotations

from typing import Any

from agents.orchestration.context import OrchestrationContext

from .guidance import PregnancyGuidanceAgent


def run_pregnancy_guidance(payload: dict[str, Any], *, village_code: str = "") -> dict[str, Any]:
    ctx = OrchestrationContext(scope="PREGNANCY", village_code=village_code)
    ctx.begin_stage("STAGE_3_DOMAIN_REASONING")

    result = ctx.record(PregnancyGuidanceAgent().run(payload, ctx))
    if result.status != "OK":
        return {
            "ok": False,
            "error": "Pregnancy guidance could not be produced.",
            "agent_trace": ctx.trace_as_dicts(),
        }

    return {
        "ok": True,
        "guidance": result.output,
        "used_llm": ctx.used_llm,
        "agent_trace": ctx.trace_as_dicts(),
    }
