"""Document -> chunks -> embeddings -> stored, with duplicate detection
and version supersession. This module is the ONLY place `KnowledgeDocument`/
`KnowledgeChunk` rows are ever created — never at request time (Section 27:
"Document ingestion happens separately. Runtime should only retrieve
already-ingested knowledge")."""

from __future__ import annotations

import datetime as dt

from django.db import transaction

from .chunking import RawSection, chunk_sections
from .embeddings import get_embedding_service
from .models import KnowledgeChunk, KnowledgeDocument


class DuplicateDocumentError(Exception):
    """Raised when the exact same document content has already been
    ingested — the caller (management command) reports this, it is not
    silently treated as success or as an error that stops the whole run."""


@transaction.atomic
def ingest_document(
    *,
    title: str,
    organization: str,
    authority: str,
    document_type: str,
    topic: str,
    sections: list[RawSection],
    subtopic: str = "",
    source_url: str = "",
    version: str = "1",
    published_date: dt.date | None = None,
    effective_date: dt.date | None = None,
    jurisdiction: str = "",
    license_note: str = "",
) -> KnowledgeDocument:
    raw_text = "\n\n".join(s.text for s in sections)
    checksum = KnowledgeDocument.compute_checksum(raw_text)

    existing = KnowledgeDocument.objects.filter(checksum=checksum).first()
    if existing is not None:
        raise DuplicateDocumentError(
            f"Identical content already ingested as document #{existing.id} "
            f"({existing.title}, v{existing.version})."
        )

    # A different version of the same (organization, title, topic): the old
    # one is superseded, not deleted — its chunks remain queryable by id for
    # historical provenance, but `active=False` means retrieval never
    # surfaces them for a new citation again (Section 43).
    previous = KnowledgeDocument.objects.filter(
        organization=organization, title=title, topic=topic, active=True
    ).first()

    document = KnowledgeDocument.objects.create(
        title=title,
        organization=organization,
        authority=authority,
        document_type=document_type,
        topic=topic,
        subtopic=subtopic,
        source_url=source_url,
        version=version,
        published_date=published_date,
        effective_date=effective_date,
        jurisdiction=jurisdiction,
        license_note=license_note,
        checksum=checksum,
    )

    if previous is not None:
        previous.active = False
        previous.superseded_by = document
        previous.save(update_fields=["active", "superseded_by"])

    embedder = get_embedding_service()
    chunks = chunk_sections(sections)
    for chunk in chunks:
        vector = embedder.embed(chunk.text)
        KnowledgeChunk.objects.create(
            document=document,
            chunk_index=chunk.chunk_index,
            chunk_text=chunk.text,
            section_title=chunk.section_title,
            page_number=chunk.page_number,
            embedding=vector,
            embedding_model=embedder.model_name,
            embedding_dim=len(vector),
        )

    return document
