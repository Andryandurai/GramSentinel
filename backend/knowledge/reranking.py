"""A small, real reranking pass over already-scored candidates.

Deliberately simple and explainable rather than a second model: a chunk
whose section title shares a word with the query is a chunk a human
skimming a table of contents would also have picked — that is worth a
modest, fixed boost on top of the vector+keyword combined score, not a
learned re-ranker. Bounded (`RERANK_BONUS`) so this step can only ever
reorder among already-plausible candidates, never rescue an irrelevant one
past the relevance gate in `retrieval.py::is_sufficiently_relevant`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .retrieval import RetrievedChunk

RERANK_BONUS = 0.08


def rerank(query: str, results: list["RetrievedChunk"]) -> list["RetrievedChunk"]:
    query_tokens = set(query.lower().split())
    if not query_tokens:
        return results

    for result in results:
        section = (result.chunk.section_title or "").lower()
        if section and query_tokens & set(section.split()):
            result.combined_score = min(1.0, result.combined_score + RERANK_BONUS)
    return results
