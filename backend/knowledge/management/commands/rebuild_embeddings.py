"""python manage.py rebuild_embeddings

Re-embeds every existing chunk with the currently-configured embedding
provider — needed after changing RAG_EMBEDDING_PROVIDER/RAG_EMBEDDING_MODEL,
since older chunks otherwise keep whatever vector they were ingested with
(each chunk records its own `embedding_model`, so a mixed-provider
knowledge base is detectable, but retrieval compares vectors directly and
assumes a consistent space — this command restores that)."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from knowledge.embeddings import get_embedding_service
from knowledge.models import KnowledgeChunk


class Command(BaseCommand):
    help = "Re-embed every KnowledgeChunk with the current embedding provider."

    def handle(self, *args, **options):
        embedder = get_embedding_service()
        chunks = KnowledgeChunk.objects.all()
        total = chunks.count()
        self.stdout.write(f"Re-embedding {total} chunk(s) with {embedder.model_name}...")

        for chunk in chunks.iterator():
            vector = embedder.embed(chunk.chunk_text)
            chunk.embedding = vector
            chunk.embedding_model = embedder.model_name
            chunk.embedding_dim = len(vector)
            chunk.save(update_fields=["embedding", "embedding_model", "embedding_dim"])

        self.stdout.write(self.style.SUCCESS(f"Done. {total} chunk(s) re-embedded."))
