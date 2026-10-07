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
from footy_quiz.hints.retrieval import contains_name, extract_aka_nickname, specificity

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384  # tied to EMBEDDING_MODEL_NAME; changing the model needs a re-embed

_model = None  # lazy-loaded singleton -- importing sentence-transformers eagerly is slow


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model


def _float_array_literal(values) -> str:
    """Formats floats as a DuckDB array SQL literal ("[0.1,0.2,...]") for inlining
    directly into a query, instead of binding as a parameter.

    Only ever used for embeddings we generate ourselves -- never external/user input,
    so there's no injection risk (every element is forced through float() first, which
    raises on anything that isn't numeric). This isn't a style choice: confirmed by
    direct measurement that DuckDB's Python parameter binding for array-typed values
    (FLOAT[N], DOUBLE[N], and even variable-length FLOAT[]) is catastrophically slower
    than inlining the same data as a literal -- ~36ms per row either way (single insert,
    executemany, or one big multi-row INSERT all showed the same per-array cost) vs
    ~0.5ms per row inlined. For a player with ~400-500 chunks, that's the difference
    between a ~15s insert loop and a sub-second one -- this was the dominant cost in
    both "New Game" latency and the hint-corpus background pre-warm."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


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
    row = con.execute(
        "SELECT p.player_name, p.player_nickname, pw.wiki_title "
        "FROM players p JOIN player_wiki pw USING (player_id) WHERE p.player_id = ?",
        [player_id],
    ).fetchone()
    if not row or not row[2]:
        return 0
    player_name, player_nickname, title = row

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

    aka = extract_aka_nickname(extract[:300])

    embeddings = _get_model().encode(chunks, normalize_embeddings=True)
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        vec_literal = _float_array_literal(emb)
        con.execute(
            f"INSERT INTO wiki_chunks VALUES (?, ?, ?, {vec_literal}::FLOAT[{EMBEDDING_DIM}], ?, ?)",
            [
                player_id,
                i,
                chunk,
                contains_name(chunk, player_name, player_nickname, aka),
                specificity(chunk),
            ],
        )
    return len(chunks)


def retrieve(
    con: duckdb.DuckDBPyConnection,
    player_id: int,
    query: str,
    k: int = 3,
    max_specificity: Optional[int] = None,
    exclude_chunk_indices: Optional[set[int]] = None,
) -> list[tuple[int, str, float]]:
    """Top-k (chunk_index, text, distance) for this player by cosine distance to the
    query (smaller = closer). contains_name=TRUE chunks are always excluded -- that's a
    hard spoiler-safety rule, not a difficulty knob. max_specificity/exclude_chunk_indices
    are session-level difficulty-progression/no-repeat controls (checkpoint 11)."""
    query_embedding = _get_model().encode([query], normalize_embeddings=True)[0]
    query_vec_literal = _float_array_literal(query_embedding)

    where_clauses = ["player_id = ?", "NOT contains_name"]
    where_params: list = [player_id]
    if max_specificity is not None:
        where_clauses.append("specificity <= ?")
        where_params.append(max_specificity)
    if exclude_chunk_indices:
        placeholders = ", ".join("?" for _ in exclude_chunk_indices)
        where_clauses.append(f"chunk_index NOT IN ({placeholders})")
        where_params.extend(exclude_chunk_indices)

    sql = f"""
        SELECT chunk_index, text,
               array_cosine_distance(embedding, {query_vec_literal}::FLOAT[{EMBEDDING_DIM}]) AS distance
        FROM wiki_chunks
        WHERE {" AND ".join(where_clauses)}
        ORDER BY distance ASC
        LIMIT ?
    """
    return con.execute(sql, [*where_params, k]).fetchall()
