"""The one orchestration function every RAG endpoint/query builder calls.

    application_result (already computed, fixed)
            |
    knowledge/queries.py builds a topic-scoped, non-identifying question
            |
            v
       retrieval.retrieve()  -- metadata filter + vector + keyword + rerank
            |
            v
    is_sufficiently_relevant()?  --no--> {"status": "no_grounding", ...}
            |yes
            v
    agents.llm.get_llm_client().summarise(GROUNDING_SYSTEM_PROMPT, ...)
            |
      (LLMUnavailable, any exception, or RAG_ENABLED=False)
            |
            v
    always returns a dict — NEVER raises. A caller that ignores the return
    value entirely still gets the same triage/alert/safety result it would
    have gotten without this module existing at all (Section 33).

This function is the ONLY place `agents.llm.get_llm_client` is imported in
this app — reusing the existing LLM client (least-disruptive option A from
Section 36 of the task) rather than adding a second HTTP client, a second
API-key setting, or a second fallback mechanism. `LLMClient.summarise()` is
already a generic (system_prompt, user_prompt) -> text call, so no change
to agents/llm/client.py was needed at all.
"""

from __future__ import annotations

import logging

from django.conf import settings

from agents.llm import LLMUnavailable, get_llm_client

from .models import RagQueryLog
from .prompts import GROUNDING_SYSTEM_PROMPT, build_user_prompt
from .provenance import citations_for
from .retrieval import RetrievedChunk, is_sufficiently_relevant, retrieve

logger = logging.getLogger("gramsentinel.knowledge")


def _chunk_preview(result: RetrievedChunk) -> dict:
    text = result.chunk.chunk_text
    return {
        "chunk_id": result.chunk.id,
        "preview": text[:220] + ("…" if len(text) > 220 else ""),
        "vector_score": round(result.vector_score, 3),
        "keyword_score": round(result.keyword_score, 3),
        "combined_score": round(result.combined_score, 3),
    }


def _template_explanation(results: list[RetrievedChunk]) -> str:
    """Used when no LLM is configured/available — the same "deterministic
    template, never a blank screen" contract every existing LLM call site
    in this project already follows. Not a synthesis, just the retrieved
    text itself, clearly presented as such."""

    lines = [
        f"[{i + 1}] {r.chunk.document.organization} — {r.chunk.document.title}: "
        f"{r.chunk.chunk_text[:280]}"
        for i, r in enumerate(results)
    ]
    return "Retrieved guidance (LLM wording unavailable):\n" + "\n".join(lines)


def _log(
    *,
    query_type: str,
    user,
    topic: str,
    results: list[RetrievedChunk],
    grounded: bool,
    used_llm: bool,
) -> None:
    try:
        RagQueryLog.objects.create(
            query_type=query_type,
            user=user if getattr(user, "is_authenticated", False) else None,
            user_role=getattr(user, "role", "") or "",
            topic=topic or "",
            retrieved_document_ids=list({r.chunk.document_id for r in results}),
            retrieved_chunk_ids=[r.chunk.id for r in results],
            grounded=grounded,
            used_llm=used_llm,
        )
    except Exception as exc:  # noqa: BLE001 - audit logging must never break RAG
        logger.warning("RAG audit log write failed: %s", exc)


def get_grounded_explanation(
    *,
    query_type: str,
    application_result: str,
    question: str,
    topic: str,
    document_type: str | None = None,
    jurisdiction: str | None = None,
    user=None,
    top_k: int | None = None,
) -> dict:
    """Returns a dict shaped exactly per Section 13 of the task
    (`answer`, `sources`, `retrieved_chunks`, `knowledge_topic`), plus a
    `status`/`grounded`/`used_llm` triple the frontend's loading/success/
    no-results/failure states (Section 59) map onto directly."""

    empty = {
        "status": "disabled",
        "grounded": False,
        "answer": "",
        "sources": [],
        "retrieved_chunks": [],
        "knowledge_topic": topic,
        "used_llm": False,
    }

    if not settings.RAG_ENABLED:
        return empty

    try:
        results = retrieve(
            question, topic=topic, document_type=document_type, jurisdiction=jurisdiction, top_k=top_k
        )
    except Exception as exc:  # noqa: BLE001 - retrieval failure must never break the caller
        logger.warning("RAG retrieval failed: %s", exc)
        return {**empty, "status": "unavailable"}

    if not is_sufficiently_relevant(results):
        _log(query_type=query_type, user=user, topic=topic, results=results, grounded=False, used_llm=False)
        return {
            **empty,
            "status": "no_grounding",
            "answer": "No sufficiently relevant approved guidance was retrieved.",
            "retrieved_chunks": [_chunk_preview(r) for r in results],
        }

    client = get_llm_client()
    used_llm = False
    if client.available:
        try:
            answer = client.summarise(
                GROUNDING_SYSTEM_PROMPT,
                build_user_prompt(
                    application_result=application_result, question=question, chunks=results
                ),
                max_tokens=settings.RAG_MAX_TOKENS,
            )
            used_llm = True
        except LLMUnavailable:
            answer = _template_explanation(results)
    else:
        answer = _template_explanation(results)

    _log(query_type=query_type, user=user, topic=topic, results=results, grounded=True, used_llm=used_llm)

    return {
        "status": "grounded",
        "grounded": True,
        "answer": answer,
        "sources": citations_for(results),
        "retrieved_chunks": [_chunk_preview(r) for r in results],
        "knowledge_topic": topic,
        "used_llm": used_llm,
    }
