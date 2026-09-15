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
      (no client configured, LLMUnavailable, any exception, or an
       empty/whitespace response)
            |
            v
    {"status": "unavailable", "answer": "", "sources": [], ...}
            |
      (otherwise)
            v
    {"status": "grounded", "answer": <LLM text>, "sources": [...], ...}

    always returns a dict — NEVER raises. A caller that ignores the return
    value entirely still gets the same triage/alert/safety result it would
    have gotten without this module existing at all (Section 33).

    IMPORTANT — "grounded" means an LLM actually produced wording. Retrieval
    succeeding on its own is not grounding: raw retrieved chunk text is
    never returned as `answer`. It was, once — a `_template_explanation()`
    helper stitched retrieved chunk previews into a "Retrieved guidance
    (LLM wording unavailable):" string and that was returned under
    `status: "grounded"`, which leaked straight into the Health Worker's
    New Assessment screen as a wall of raw source text. That helper is
    gone; "no usable LLM wording" now correctly reports `status:
    "unavailable"` with no answer text and no sources, so the frontend
    shows its own clean "temporarily unavailable" message instead.

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
    if not client.available:
        # No LLM configured at all — this is the ordinary state in this
        # environment (no API key), and it is a genuinely different fact
        # from "nothing relevant was found": relevant material exists, but
        # there is no wording engine available to explain it right now.
        _log(query_type=query_type, user=user, topic=topic, results=results, grounded=False, used_llm=False)
        return {**empty, "status": "unavailable"}

    try:
        answer = client.summarise(
            GROUNDING_SYSTEM_PROMPT,
            build_user_prompt(
                application_result=application_result, question=question, chunks=results
            ),
            max_tokens=settings.RAG_MAX_TOKENS,
        )
    except LLMUnavailable as exc:
        logger.info("RAG explanation unavailable (%s), no answer returned to caller.", exc)
        _log(query_type=query_type, user=user, topic=topic, results=results, grounded=False, used_llm=False)
        return {**empty, "status": "unavailable"}

    if not answer or not answer.strip():
        # An empty/whitespace LLM response is treated the same as no LLM at
        # all — never fabricate placeholder wording, and never fall back to
        # showing the raw retrieved text in its place.
        logger.warning("RAG LLM call returned an empty response for query_type=%s", query_type)
        _log(query_type=query_type, user=user, topic=topic, results=results, grounded=False, used_llm=False)
        return {**empty, "status": "unavailable"}

    _log(query_type=query_type, user=user, topic=topic, results=results, grounded=True, used_llm=True)

    return {
        "status": "grounded",
        "grounded": True,
        "answer": answer,
        "sources": citations_for(results),
        "retrieved_chunks": [_chunk_preview(r) for r in results],
        "knowledge_topic": topic,
        "used_llm": True,
    }
