"""Tests footy_quiz.hints.store's pipeline logic with the embedding model and Wikipedia
fetch mocked out -- no real network calls or ML model loading, so this stays fast.
"""

import duckdb
import pytest

from footy_quiz.hints import store

KEYWORDS = ["apple", "banana", "carrot"]


class FakeModel:
    """Deterministic one-hot-ish embeddings: dimension i is 1.0 if KEYWORDS[i] appears in
    the text, else 0.0, scaled to unit length -- so cosine distance is exactly 0 for a
    shared keyword and 1 (orthogonal) otherwise."""

    def encode(self, texts, normalize_embeddings=True):
        import numpy as np

        vectors = []
        for text in texts:
            vec = np.zeros(store.EMBEDDING_DIM, dtype="float32")
            for i, kw in enumerate(KEYWORDS):
                if kw in text.lower():
                    vec[i] = 1.0
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            vectors.append(vec)
        return np.array(vectors)


@pytest.fixture
def con(monkeypatch):
    monkeypatch.setattr(store, "_get_model", lambda: FakeModel())

    conn = duckdb.connect()
    conn.execute("CREATE TABLE players (player_id INTEGER, player_name VARCHAR, player_nickname VARCHAR)")
    conn.execute(
        """
        CREATE TABLE player_wiki (
            player_id INTEGER, wiki_title VARCHAR, resolution_method VARCHAR,
            photo_url VARCHAR, fetched_at TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE TABLE wiki_pages (player_id INTEGER, wiki_title VARCHAR, raw_extract VARCHAR, fetched_at TIMESTAMP)"
    )
    conn.execute(
        f"CREATE TABLE wiki_chunks (player_id INTEGER, chunk_index INTEGER, text VARCHAR, "
        f"embedding FLOAT[{store.EMBEDDING_DIM}], contains_name BOOLEAN, specificity SMALLINT)"
    )
    conn.execute("INSERT INTO players VALUES (1, 'Test Player', 'Tester')")
    yield conn
    conn.close()


def test_ensure_player_chunks_fetches_and_embeds(con, monkeypatch):
    monkeypatch.setattr(store.media, "get_or_fetch_player_photo", lambda c, pid: None)
    con.execute("INSERT INTO player_wiki VALUES (1, 'Test Player', 'direct', NULL, NULL)")
    # Each sentence is long enough (>=8 words) to flush as its own chunk rather than
    # merging with the next -- see footy_quiz.hints.chunking's MIN_CHUNK_WORDS.
    monkeypatch.setattr(
        store.media,
        "fetch_full_extract",
        lambda title: (
            "He spent his childhood growing apples on his family's small orchard. "
            "Later in life he became locally famous for growing banana trees in his garden."
        ),
    )

    n = store.ensure_player_chunks(con, 1)
    assert n == 2
    assert con.execute("SELECT COUNT(*) FROM wiki_pages WHERE player_id = 1").fetchone()[0] == 1


def test_ensure_player_chunks_is_cached_on_second_call(con, monkeypatch):
    monkeypatch.setattr(store.media, "get_or_fetch_player_photo", lambda c, pid: None)
    con.execute("INSERT INTO player_wiki VALUES (1, 'Test Player', 'direct', NULL, NULL)")
    call_count = 0

    def fake_extract(title):
        nonlocal call_count
        call_count += 1
        return "He loves apple pie."

    monkeypatch.setattr(store.media, "fetch_full_extract", fake_extract)

    store.ensure_player_chunks(con, 1)
    store.ensure_player_chunks(con, 1)
    assert call_count == 1  # second call hit the cache


def test_ensure_player_chunks_returns_zero_when_unresolved(con, monkeypatch):
    monkeypatch.setattr(store.media, "get_or_fetch_player_photo", lambda c, pid: None)
    con.execute("INSERT INTO player_wiki VALUES (1, NULL, 'unresolved', NULL, NULL)")
    n = store.ensure_player_chunks(con, 1)
    assert n == 0


def test_retrieve_returns_most_relevant_chunk_first(con):
    con.execute(
        "INSERT INTO wiki_chunks VALUES (1, 0, 'A story about apple orchards', ?, false, 1)",
        [[1.0, 0.0, 0.0] + [0.0] * (store.EMBEDDING_DIM - 3)],
    )
    con.execute(
        "INSERT INTO wiki_chunks VALUES (1, 1, 'A story about banana farms', ?, false, 1)",
        [[0.0, 1.0, 0.0] + [0.0] * (store.EMBEDDING_DIM - 3)],
    )
    con.execute(
        "INSERT INTO wiki_chunks VALUES (1, 2, 'A story about carrot fields', ?, false, 1)",
        [[0.0, 0.0, 1.0] + [0.0] * (store.EMBEDDING_DIM - 3)],
    )

    results = store.retrieve(con, 1, "tell me about banana", k=2)
    chunk_index, text, distance = results[0]
    assert text == "A story about banana farms"
    assert distance < results[1][2]  # closest result has the smallest distance


def test_retrieve_excludes_name_containing_chunks(con):
    con.execute(
        "INSERT INTO wiki_chunks VALUES (1, 0, 'A story about banana farms', ?, true, 1)",
        [[0.0, 1.0, 0.0] + [0.0] * (store.EMBEDDING_DIM - 3)],
    )
    con.execute(
        "INSERT INTO wiki_chunks VALUES (1, 1, 'A different fact entirely', ?, false, 1)",
        [[0.0, 0.0, 0.0] + [0.0] * (store.EMBEDDING_DIM - 3)],
    )

    results = store.retrieve(con, 1, "tell me about banana", k=5)
    assert all(text != "A story about banana farms" for _, text, _ in results)


def test_retrieve_respects_specificity_ceiling(con):
    con.execute(
        "INSERT INTO wiki_chunks VALUES (1, 0, 'A vague fact', ?, false, 1)",
        [[0.0, 1.0, 0.0] + [0.0] * (store.EMBEDDING_DIM - 3)],
    )
    con.execute(
        "INSERT INTO wiki_chunks VALUES (1, 1, 'A very specific fact', ?, false, 3)",
        [[0.0, 1.0, 0.0] + [0.0] * (store.EMBEDDING_DIM - 3)],
    )

    results = store.retrieve(con, 1, "tell me about banana", k=5, max_specificity=1)
    assert len(results) == 1
    assert results[0][1] == "A vague fact"


def test_retrieve_respects_exclude_chunk_indices(con):
    con.execute(
        "INSERT INTO wiki_chunks VALUES (1, 0, 'First banana fact', ?, false, 1)",
        [[0.0, 1.0, 0.0] + [0.0] * (store.EMBEDDING_DIM - 3)],
    )
    con.execute(
        "INSERT INTO wiki_chunks VALUES (1, 1, 'Second banana fact', ?, false, 1)",
        [[0.0, 1.0, 0.0] + [0.0] * (store.EMBEDDING_DIM - 3)],
    )

    results = store.retrieve(con, 1, "tell me about banana", k=5, exclude_chunk_indices={0})
    assert [r[0] for r in results] == [1]
