"""Document -> chunks, preserving structure rather than splitting blindly.

Input documents in this project's seed content are already authored as a
list of `(section_title, page_number, paragraph_text)` tuples (see
`knowledge/seed_content.py`) — real ingestion of a plain-text/markdown
document reduces to the same shape via `sections_from_plain_text()` below.
Either way, a chunk never crosses a section boundary, and page/section
metadata always travels with the text it came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: A paragraph longer than this is split on sentence boundaries so no
#: single chunk becomes too large for a useful embedding/retrieval unit —
#: without cutting mid-sentence, which would break semantic context.
MAX_CHUNK_CHARS = 800
MIN_CHUNK_CHARS = 40


@dataclass
class RawSection:
    section_title: str
    page_number: int | None
    text: str


@dataclass
class Chunk:
    chunk_index: int
    section_title: str
    page_number: int | None
    text: str
    metadata: dict = field(default_factory=dict)


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _split_long_paragraph(text: str) -> list[str]:
    """Greedily pack whole sentences into <= MAX_CHUNK_CHARS pieces."""

    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip()
        if len(candidate) > MAX_CHUNK_CHARS and current:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces or [text]


def chunk_sections(sections: list[RawSection]) -> list[Chunk]:
    """One chunk per paragraph/section, splitting only when a paragraph on
    its own exceeds MAX_CHUNK_CHARS. Section title and page number are
    carried onto every chunk produced from that section — this is the
    provenance `knowledge/provenance.py` later turns into a citation."""

    chunks: list[Chunk] = []
    index = 0
    for section in sections:
        text = section.text.strip()
        if len(text) < MIN_CHUNK_CHARS:
            continue
        pieces = (
            _split_long_paragraph(text) if len(text) > MAX_CHUNK_CHARS else [text]
        )
        for piece in pieces:
            chunks.append(
                Chunk(
                    chunk_index=index,
                    section_title=section.section_title,
                    page_number=section.page_number,
                    text=piece,
                )
            )
            index += 1
    return chunks


def sections_from_plain_text(raw_text: str) -> list[RawSection]:
    """Fallback for a document with no pre-structured section list: treat
    blank-line-separated paragraphs as sections, no page numbers (plain
    text carries none). Prefer supplying real `RawSection`s (as the seed
    content does) whenever section/page structure is actually known —
    this exists only so `ingest_document()` has *something* correct to do
    with an arbitrary plain-text upload rather than refusing it outright."""

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw_text) if p.strip()]
    return [RawSection(section_title="", page_number=None, text=p) for p in paragraphs]
