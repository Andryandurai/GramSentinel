"""Embedding generation — pluggable provider, same graceful-degradation
contract as `agents/llm/client.py`.

Two providers:

- "local" (default, always available): a deterministic hashed bag-of-words
  vectoriser (the "hashing trick" — the same technique Vowpal Wabbit and
  scikit-learn's own `HashingVectorizer` use). No network call, no API key,
  no ML library. Same text always produces the same vector, and vectors for
  texts sharing more words point in a more similar direction — enough for a
  small, curated knowledge base's retrieval to be meaningfully better than
  random, without pretending to be a trained semantic embedding model. This
  is the ONLY path exercised by this project's tests and by the seeded
  knowledge base in this environment.
- "openai": a real external embeddings API call (plain `requests`, no SDK —
  matching agents/llm/client.py's own approach), used only when
  RAG_EMBEDDING_PROVIDER=openai and RAG_EMBEDDING_API_KEY is set. Not
  exercised in this environment (no key configured here) — included so a
  real deployment has a working, documented upgrade path to genuine
  semantic embeddings without changing any caller of this module.

Never called with patient data — see knowledge/queries.py for what is
actually embedded/sent (only already-aggregated, non-identifying context,
mirroring the same rule agents/llm/client.py's docstring states for its
own LLM calls).
"""

from __future__ import annotations

import hashlib
import logging
import math
import re

from django.conf import settings

logger = logging.getLogger("gramsentinel.knowledge")

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class EmbeddingUnavailable(RuntimeError):
    """Raised internally when the configured provider can't be reached.
    Callers fall back to keyword-only retrieval — see retrieval.py."""


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _local_embed(text: str, dim: int) -> list[float]:
    tokens = _tokenize(text)
    # Unigrams plus adjacent-pair bigrams — bigrams give the hashed vector
    # a little word-order sensitivity ("blood sugar" != "sugar blood").
    grams = list(tokens) + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]

    vector = [0.0] * dim
    for gram in grams:
        digest = hashlib.sha256(gram.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign

    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


def _openai_embed(text: str) -> list[float]:
    try:
        import requests
    except ImportError as exc:  # pragma: no cover
        raise EmbeddingUnavailable("requests not installed") from exc

    try:
        response = requests.post(
            settings.RAG_EMBEDDING_API_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.RAG_EMBEDDING_API_KEY}",
            },
            json={"model": settings.RAG_EMBEDDING_MODEL, "input": text},
            timeout=12,
        )
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]
    except Exception as exc:  # noqa: BLE001 - any failure degrades gracefully
        logger.warning("Embedding call failed, falling back to local: %s", exc)
        raise EmbeddingUnavailable(str(exc)) from exc


class EmbeddingService:
    """`embed(text) -> (vector, model_name)`. Never raises — a provider
    failure silently falls back to the local vectoriser rather than
    breaking ingestion or a retrieval request."""

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        dim: int | None = None,
    ) -> None:
        self.provider = provider or settings.RAG_EMBEDDING_PROVIDER
        self.model = model or settings.RAG_EMBEDDING_MODEL
        self.dim = dim or settings.RAG_LOCAL_EMBEDDING_DIM

    @property
    def model_name(self) -> str:
        return self.model if self.provider == "openai" else f"local-hash-{self.dim}"

    def embed(self, text: str) -> list[float]:
        if self.provider == "openai" and settings.RAG_EMBEDDING_API_KEY:
            try:
                return _openai_embed(text)
            except EmbeddingUnavailable:
                pass
        return _local_embed(text, self.dim)


_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _service
    if _service is None:
        _service = EmbeddingService()
    return _service


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
