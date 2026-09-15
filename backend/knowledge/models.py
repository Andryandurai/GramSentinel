"""The RAG knowledge base — a side-car, not a decision-maker.

Nothing in this module is read by any deterministic agent, the Safety
Engine, or alert-creation logic (`safety/`, `alerts/services.py`,
`agents/orchestration/`). It exists solely to be retrieved *after* those
have already produced a result, so an explanation can be grounded in
curated documents. See `knowledge/rag_service.py`'s module docstring and
`RAG_ARCHITECTURE.md` for the full boundary.

Schema is written to work unchanged on both SQLite (local/dev/test) and
PostgreSQL (production) — `KnowledgeChunk.embedding` is a plain JSON list
of floats rather than a Postgres-only `pgvector.VectorField`, so retrieval
is identical on both. See `knowledge/embeddings.py` and
`knowledge/retrieval.py` for why, and RAG_ARCHITECTURE.md for the
documented production upgrade path (a real pgvector column + ANN index)
once the curated document set is large enough that brute-force cosine
similarity over a JSON column stops being the right tradeoff.
"""

from __future__ import annotations

import hashlib

from django.db import models


class KnowledgeTopic(models.TextChoices):
    """Controlled vocabulary — retrieval is filtered by this, not by
    vector similarity alone, so a high-similarity but wrong-domain chunk
    (e.g. a CHW-education sentence surfacing in a surveillance query)
    cannot be retrieved just because the wording happens to be close."""

    CLINICAL = "CLINICAL", "Clinical guidance"
    PUBLIC_HEALTH = "PUBLIC_HEALTH", "Public health"
    SURVEILLANCE = "SURVEILLANCE", "Surveillance"
    CHW_ASHA = "CHW_ASHA", "CHW / ASHA guidance"
    REFERRAL = "REFERRAL", "Referral guidance"
    TERMINOLOGY = "TERMINOLOGY", "Terminology reference"
    INVESTIGATION = "INVESTIGATION", "Investigation guidance"
    GRAMSENTINEL_INTERNAL = "GRAMSENTINEL_INTERNAL", "GramSentinel application documentation"


class DocumentType(models.TextChoices):
    GUIDELINE = "GUIDELINE", "Clinical guideline"
    SURVEILLANCE_GUIDANCE = "SURVEILLANCE_GUIDANCE", "Surveillance guidance"
    CHW_GUIDANCE = "CHW_GUIDANCE", "CHW / ASHA guidance"
    REFERRAL_GUIDANCE = "REFERRAL_GUIDANCE", "Referral guidance"
    TERMINOLOGY_REFERENCE = "TERMINOLOGY_REFERENCE", "Terminology reference"
    INVESTIGATION_GUIDANCE = "INVESTIGATION_GUIDANCE", "Investigation guidance"
    APPLICATION_DOCUMENTATION = "APPLICATION_DOCUMENTATION", "Application documentation"


class DocumentAuthority(models.TextChoices):
    """How authoritative this document actually is — checked before every
    citation is shown, so the UI can never present reference material as
    if it were verbatim official guidance.

    Nothing ingested by this project's own seed content is OFFICIAL. That
    level exists for a real deployment that ingests verified, licensed
    documents obtained directly from WHO/MoHFW/NHM/an equivalent body —
    doing so is explicitly out of scope for this environment (see
    RAG_ARCHITECTURE.md's "Knowledge Sources" section for why).
    """

    OFFICIAL = "OFFICIAL", "Official published guidance from the named organization"
    REFERENCE = "REFERENCE", "General reference material — not verbatim official text"
    INTERNAL = "INTERNAL", "GramSentinel's own application documentation"


class KnowledgeDocument(models.Model):
    title = models.CharField(max_length=300)
    organization = models.CharField(
        max_length=160,
        help_text="Who this document is attributed to — never shown as a "
        "citation source unless it matches reality (see authority field).",
    )
    authority = models.CharField(max_length=16, choices=DocumentAuthority.choices)
    document_type = models.CharField(max_length=32, choices=DocumentType.choices)
    topic = models.CharField(max_length=32, choices=KnowledgeTopic.choices)
    subtopic = models.CharField(max_length=120, blank=True)

    source_url = models.URLField(blank=True)
    version = models.CharField(max_length=32, default="1")
    published_date = models.DateField(null=True, blank=True)
    effective_date = models.DateField(null=True, blank=True)
    language = models.CharField(max_length=8, default="en")
    jurisdiction = models.CharField(max_length=120, blank=True, default="")
    license_note = models.CharField(max_length=200, blank=True, default="")

    #: sha256 of the full raw text, before chunking — the duplicate-detection
    #: key `ingestion.py` checks before re-ingesting the same document.
    checksum = models.CharField(max_length=64, unique=True, editable=False)
    #: A superseded version stays in the database (never deleted) so a
    #: chunk retrieved in the past remains traceable to the exact version it
    #: came from — only `active` documents are ever retrieved going forward.
    active = models.BooleanField(default=True)
    #: Set when a newer version of the same (organization, title, topic)
    #: replaces this one — see ingestion.py::ingest_document().
    superseded_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="supersedes"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization", "title", "-version"]
        indexes = [
            models.Index(fields=["topic", "document_type", "active"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.organization}, v{self.version})"

    @staticmethod
    def compute_checksum(raw_text: str) -> str:
        return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


class KnowledgeChunk(models.Model):
    document = models.ForeignKey(
        KnowledgeDocument, on_delete=models.CASCADE, related_name="chunks"
    )
    chunk_index = models.PositiveIntegerField()
    chunk_text = models.TextField()
    section_title = models.CharField(max_length=200, blank=True, default="")
    page_number = models.PositiveIntegerField(null=True, blank=True)

    #: A plain JSON list of floats — see module docstring for why this is
    #: not a Postgres-only pgvector column. `embedding_model`/`embedding_dim`
    #: are stored per-chunk (not assumed global) so re-embedding with a new
    #: provider/model can coexist with older chunks during a migration.
    embedding = models.JSONField(default=list, blank=True)
    embedding_model = models.CharField(max_length=64, blank=True, default="")
    embedding_dim = models.PositiveIntegerField(default=0)

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["document_id", "chunk_index"]
        unique_together = [("document", "chunk_index")]

    def __str__(self) -> str:
        return f"{self.document_id}#{self.chunk_index}"


class RagQueryLog(models.Model):
    """Audit trail — Section 44 of the task. Deliberately thin: records
    which query type ran, by whom, what was retrieved, never the raw
    question text or any patient-identifying content (the callers in
    `knowledge/queries.py` never construct one from patient data in the
    first place, so there is nothing sensitive to accidentally log here)."""

    query_type = models.CharField(max_length=32)
    user = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    user_role = models.CharField(max_length=32, blank=True)
    topic = models.CharField(max_length=32, blank=True)
    retrieved_document_ids = models.JSONField(default=list)
    retrieved_chunk_ids = models.JSONField(default=list)
    grounded = models.BooleanField(
        default=False, help_text="True if relevance cleared RAG_MIN_RELEVANCE."
    )
    used_llm = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.query_type} @ {self.created_at:%Y-%m-%d %H:%M}"
