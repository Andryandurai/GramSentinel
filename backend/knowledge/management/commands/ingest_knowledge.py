"""python manage.py ingest_knowledge

Loads the curated document set from `knowledge/seed_content.py` into the
knowledge base. Idempotent: a document whose exact content has already
been ingested is skipped (reported as a duplicate), never re-created.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from knowledge.ingestion import DuplicateDocumentError, ingest_document
from knowledge.seed_content import DOCUMENTS


class Command(BaseCommand):
    help = "Ingest the curated RAG knowledge base (idempotent)."

    def handle(self, *args, **options):
        self.stdout.write("Ingesting GramSentinel knowledge base...")
        ingested = duplicates = 0

        for spec in DOCUMENTS:
            try:
                document = ingest_document(**spec)
                ingested += 1
                self.stdout.write(
                    f"  + {document.title} ({document.organization}, "
                    f"{len(document.chunks.all())} chunks)"
                )
            except DuplicateDocumentError as exc:
                duplicates += 1
                self.stdout.write(f"  = skipped (unchanged): {spec['title']} — {exc}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {ingested} document(s) ingested, {duplicates} unchanged."
            )
        )
