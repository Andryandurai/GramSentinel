"""Hybrid retrieval: metadata filter -> vector similarity + keyword overlap
-> combined score -> rerank -> top-k -> relevance gate.

    Query + filters
        |
        v
    KnowledgeChunk.objects.filter(document__topic=..., document__active=True, ...)
        |
        v
    for each candidate: cosine(query_vec, chunk_vec)  +  keyword overlap
        |
        v
    combined = VECTOR_WEIGHT * vector_score + KEYWORD_WEIGHT * keyword_score
        |
        v
    reranking.rerank()  (section-title match bonus)
        |
        v
    sorted, top RAG_TOP_K
        |
        v
    best score < RAG_MIN_RELEVANCE?  -> [] (Section 34: no forced answer)
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from .embeddings import cosine_similarity, get_embedding_service
from .models import KnowledgeChunk
from .reranking import rerank

VECTOR_WEIGHT = 0.6
KEYWORD_WEIGHT = 0.4


@dataclass
class RetrievedChunk:
    chunk: KnowledgeChunk
    vector_score: float
    keyword_score: float
    combined_score: float


def _keyword_score(query_tokens: set[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    text_tokens = set(text.lower().split())
    overlap = query_tokens & text_tokens
    return len(overlap) / len(query_tokens)


def retrieve(
    query: str,
    *,
    topic: str | list[str] | None = None,
    document_type: str | None = None,
    jurisdiction: str | None = None,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    """The one retrieval entry point every query builder in queries.py
    goes through. `topic`/`document_type`/`jurisdiction` are metadata
    filters applied BEFORE any similarity scoring (Section 12) — a
    high-similarity chunk from the wrong topic is never a candidate at
    all, not merely down-ranked. `topic` accepts a list where one UI
    surface intentionally spans more than one knowledge topic (e.g. the
    RuralCare panel showing clinical + referral guidance together)."""

    top_k = top_k or settings.RAG_TOP_K

    candidates = KnowledgeChunk.objects.filter(document__active=True).select_related(
        "document"
    )
    if isinstance(topic, (list, tuple, set)):
        candidates = candidates.filter(document__topic__in=list(topic))
    elif topic:
        candidates = candidates.filter(document__topic=topic)
    if document_type:
        candidates = candidates.filter(document__document_type=document_type)
    if jurisdiction:
        candidates = candidates.filter(document__jurisdiction=jurisdiction)

    candidates = list(candidates)
    if not candidates:
        return []

    embedder = get_embedding_service()
    query_vector = embedder.embed(query)
    query_tokens = set(query.lower().split())

    scored: list[RetrievedChunk] = []
    for chunk in candidates:
        vector_score = cosine_similarity(query_vector, chunk.embedding)
        keyword_score = _keyword_score(query_tokens, chunk.chunk_text)
        combined = VECTOR_WEIGHT * vector_score + KEYWORD_WEIGHT * keyword_score
        scored.append(
            RetrievedChunk(
                chunk=chunk,
                vector_score=vector_score,
                keyword_score=keyword_score,
                combined_score=combined,
            )
        )

    scored = rerank(query, scored)
    scored.sort(key=lambda r: r.combined_score, reverse=True)
    return scored[:top_k]


def is_sufficiently_relevant(results: list[RetrievedChunk]) -> bool:
    if not results:
        return False
    return results[0].combined_score >= settings.RAG_MIN_RELEVANCE
