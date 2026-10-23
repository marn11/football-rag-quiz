"""Sanity checks on target-player selection. Requires build_db.py + build_graph.py to have run."""

import pytest

from footy_quiz import db, selection
from footy_quiz.ingest import DEFAULT_DB_PATH


@pytest.fixture(scope="module")
def con():
    if not DEFAULT_DB_PATH.exists():
        pytest.skip(f"{DEFAULT_DB_PATH} not built yet -- run scripts/build_db.py first")
    conn = db.connect()
    if conn.sql("SELECT COUNT(*) FROM teammate_edges").fetchone()[0] == 0:
        pytest.skip("teammate_edges is empty -- run scripts/build_graph.py first")
    yield conn
    conn.close()


def test_cameo_sub_is_extreme_not_missing(con):
    # Ruan Teles: exactly 1 appearance -- too sparse for easy/normal/hard, but still
    # has teammates from that one match, so should land in "extreme", not disappear.
    candidates = selection.rank_candidates(con, difficulty="any", limit=100_000)
    by_id = {c.player_id: c for c in candidates}
    assert 520787 in by_id
    assert by_id[520787].difficulty == "extreme"


def test_messi_is_easy(con):
    candidates = selection.rank_candidates(con, difficulty="any", limit=100_000)
    by_id = {c.player_id: c for c in candidates}
    assert 28003 in by_id
    assert by_id[28003].difficulty == "easy"


def test_bands_are_mutually_exclusive_and_well_formed(con):
    # limit must be large enough to span every band -- rank_candidates sorts by score
    # globally, and "extreme" (minimal connections, by construction the lowest-scoring
    # tier) has thousands of members in this dataset but would never surface in a small
    # top-N cut dominated by higher-scoring easy/normal/hard candidates.
    candidates = selection.rank_candidates(con, difficulty="any", limit=100_000)
    assert all(c.difficulty in ("easy", "normal", "hard", "extreme") for c in candidates)
    seen_ids = [c.player_id for c in candidates]
    assert len(seen_ids) == len(set(seen_ids))  # each player appears in exactly one band
    for name in ("easy", "normal", "hard", "extreme"):
        assert any(c.difficulty == name for c in candidates), f"no candidates for {name}"


def test_candidates_sorted_descending_by_score(con):
    candidates = selection.rank_candidates(con, difficulty="any", limit=200)
    scores = [c.score for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_difficulty_filter_only_returns_requested_band(con):
    hard_only = selection.rank_candidates(con, difficulty="hard", limit=200)
    assert all(c.difficulty == "hard" for c in hard_only)
