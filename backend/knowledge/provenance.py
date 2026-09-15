"""Turn a retrieved chunk into exactly what Section 14 of the task asks
for — a citation the UI can show without ever inventing a page or section
that isn't actually there."""

from __future__ import annotations

from .retrieval import RetrievedChunk


def citation_for(result: RetrievedChunk) -> dict:
    document = result.chunk.document
    return {
        "document_id": document.id,
        "title": document.title,
        "organization": document.organization,
        "authority": document.authority,
        "authority_label": document.get_authority_display(),
        "document_type": document.document_type,
        # Omitted (None), never fabricated, when the source document simply
        # doesn't carry that piece of metadata (Section 14: "If page/section
        # metadata is unavailable, omit it rather than fabricate it").
        "section": result.chunk.section_title or None,
        "page": result.chunk.page_number,
        "version": document.version,
        "source_url": document.source_url or None,
        "jurisdiction": document.jurisdiction or None,
        "relevance_score": round(result.combined_score, 3),
    }


def citations_for(results: list[RetrievedChunk]) -> list[dict]:
    return [citation_for(r) for r in results]
