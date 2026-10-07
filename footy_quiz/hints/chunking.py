"""Sentence-level chunking of Wikipedia prose for the hint pipeline.

Rule-based sentence boundary detection (pysbd) rather than an ML tokenizer -- it needs
no model download and handles the abbreviation patterns common in football bios ("St.",
initials) out of the box. Short fragments ("He retired in 2015.") carry little
standalone signal for embedding or as a hint, so they're merged with the next sentence;
chunks are capped at 2 sentences so none get too long either.
"""

from __future__ import annotations

import re

import pysbd

MIN_CHUNK_WORDS = 8
MAX_SENTENCES_PER_CHUNK = 2

# Wikipedia's explaintext=1 output keeps section headings as plain lines like
# "== Youth career ==" or "=== Barcelona ===" -- not prose, and pysbd sometimes glues
# adjacent headings into one "sentence" with no real content, which pollutes retrieval.
_HEADING_LINE = re.compile(r"^\s*=+\s*.*?\s*=+\s*$")

_segmenter = pysbd.Segmenter(language="en", clean=True)


def _strip_headings(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not _HEADING_LINE.match(line))


def chunk_text(text: str) -> list[str]:
    text = _strip_headings(text)
    sentences = [s.strip() for s in _segmenter.segment(text) if s.strip()]

    chunks: list[str] = []
    buffer: list[str] = []
    for sentence in sentences:
        buffer.append(sentence)
        word_count = sum(len(s.split()) for s in buffer)
        if word_count >= MIN_CHUNK_WORDS or len(buffer) >= MAX_SENTENCES_PER_CHUNK:
            chunks.append(" ".join(buffer))
            buffer = []

    if buffer:
        leftover = " ".join(buffer)
        if chunks and len(leftover.split()) < MIN_CHUNK_WORDS:
            chunks[-1] = f"{chunks[-1]} {leftover}"
        else:
            chunks.append(leftover)

    return chunks
