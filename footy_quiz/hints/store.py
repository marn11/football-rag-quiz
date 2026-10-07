"""Fetches, chunks, and embeds a player's Wikipedia prose for the RAG hint pipeline.

Reuses footy_quiz.media's resolved title (Checkpoint 5's player_wiki cache) instead of
re-resolving -- that endpoint only returns a short summary (used for the photo/football
keyword check); this module fetches the FULL article body via a different endpoint
(media.fetch_full_extract), chunks it, and embeds each chunk with a local
sentence-transformers model (no API cost, no network dependency beyond Wikipedia itself).

Embedding/retrieval is genuine RAG: chunks are embedded once and cached (wiki_chunks),
then retrieve() does a live similarity search per query -- there's no fixed hint list,
the relevant chunks depend on what's asked for at request time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import duckdb

from footy_quiz import media
from footy_quiz.hints.chunking import chunk_text

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384  # tied to EMBEDDING_MODEL_NAME; changing the model needs a re-embed

_model = None  # lazy-loaded singleton -- importing sentence-transformers eagerly is slow


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model


def ensure_player_chunks(con: duckdb.DuckDBPyConnection, player_id: int) -> int:
    """Fetches + chunks + embeds this player's Wikipedia prose if not already cached.
    Returns the chunk count (0 if no Wikipedia page could be resolved or fetched)."""
    (cached,) = con.execute(
        "SELECT COUNT(*) FROM wiki_chunks WHERE player_id = ?", [player_id]
    ).fetchone()
    if cached:
        return cached

    # Ensures Checkpoint 5's title resolution has run (and is cached) for this player.
    media.get_or_fetch_player_photo(con, player_id)
    title_row = con.execute(
        "SELECT wiki_title FROM player_wiki WHERE player_id = ?", [player_id]
    ).fetchone()
    if not title_row or not title_row[0]:
        return 0
    title = title_row[0]

    extract = media.fetch_full_extract(title)
    if not extract:
        return 0

    con.execute(
        "INSERT INTO wiki_pages VALUES (?, ?, ?, ?)",
        [player_id, title, extract, datetime.now(timezone.utc)],
    )

    chunks = chunk_text(extract)
    if not chunks:
        return 0

    embeddings = _get_model().encode(chunks, normalize_embeddings=True)
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        con.execute(
            "INSERT INTO wiki_chunks VALUES (?, ?, ?, ?)",
            [player_id, i, chunk, emb.tolist()],
        )
    return len(chunks)


def retrieve(
    con: duckdb.DuckDBPyConnection, player_id: int, query: str, k: int = 3
) -> list[tuple[str, float]]:
    """Top-k chunks for this player by cosine distance to the query (smaller = closer)."""
    query_embedding = _get_model().encode([query], normalize_embeddings=True)[0].tolist()
    return con.execute(
        f"""
        SELECT text, array_cosine_distance(embedding, ?::FLOAT[{EMBEDDING_DIM}]) AS distance
        FROM wiki_chunks
        WHERE player_id = ?
        ORDER BY distance ASC
        LIMIT ?
        """,
        [query_embedding, player_id, k],
    ).fetchall()
