"""The grounding contract every RAG explanation is generated under.

One shared system prompt (Section 35 of the task, implemented near-
verbatim) so every query type in `queries.py` carries the same hard
constraints, rather than each one having to remember to restate them.
"""

from __future__ import annotations

from .retrieval import RetrievedChunk

GROUNDING_SYSTEM_PROMPT = (
    "You explain retrieved knowledge in relation to a result a separate, "
    "deterministic system has already computed. Rules you must follow: "
    "use only the retrieved context below for any knowledge claim; do not "
    "invent citations, page numbers, organizations, or documents; do not "
    "diagnose a patient or name a disease; do not declare or imply an "
    "outbreak; do not state or imply a different triage level, referral, "
    "severity, or safety verdict than the one given to you — you are "
    "explaining it, not deciding it; clearly distinguish the application's "
    "own result from what the retrieved guidance says; if the retrieved "
    "context is thin or only partially relevant, say so plainly rather "
    "than filling the gap with your own general knowledge."
)


def build_user_prompt(
    *,
    application_result: str,
    question: str,
    chunks: list[RetrievedChunk],
) -> str:
    context_block = "\n\n".join(
        f"[{i + 1}] ({r.chunk.document.organization} — {r.chunk.document.title}"
        f"{f', {r.chunk.section_title}' if r.chunk.section_title else ''}"
        f"{f', p.{r.chunk.page_number}' if r.chunk.page_number else ''})\n"
        f"{r.chunk.text}"
        for i, r in enumerate(chunks)
    )
    return (
        f"APPLICATION RESULT (already computed, fixed, do not change):\n"
        f"{application_result}\n\n"
        f"RETRIEVED GUIDANCE:\n{context_block}\n\n"
        f"TASK: {question}\n"
        f"Explain how the retrieved guidance above relates to the "
        f"application result. Cite sources by their [n] marker. Do not "
        f"change the application result."
    )
