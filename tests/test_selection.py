"""Sanity checks on target-player selection. Requires build_db.py + build_graph.py to have run."""

import duckdb
import pytest

from footy_quiz import selection
from footy_quiz.ingest import DEFAULT_DB_PATH


@pytest.fixture(scope="module")
def con():
    if not DEFAULT_DB_PATH.exists():
        pytest.skip(f"{DEFAULT_DB_PATH} not built yet -- run scripts/build_db.py first")
    conn = duckdb.connect(str(DEFAULT_DB_PATH), read_only=True)
    if conn.sql("SELECT COUNT(*) FROM teammate_edges").fetchone()[0] == 0:
        pytest.skip("teammate_edges is empty -- run scripts/build_graph.py first")
    yield conn
    conn.close()


def test_cameo_sub_excluded(con):
    # Sergi Canós: exactly 1 appearance in this dataset -- below MIN_MATCHES_FOR_TARGET.
    candidates = selection.rank_candidates(con, limit=100_000)
    assert 4762 not in {c.player_id for c in candidates}


def test_messi_is_multi_club_tier(con):
    candidates = selection.rank_candidates(con, limit=100_000)
    by_id = {c.player_id: c for c in candidates}
    assert 5503 in by_id
    messi = by_id[5503]
    assert messi.tier == "multi_club"
    assert messi.n_rich_clubs >= 2


def test_tiers_are_well_formed(con):
    candidates = selection.rank_candidates(con, limit=1000)
    assert all(c.tier in ("multi_club", "single_club") for c in candidates)
    assert any(c.tier == "multi_club" for c in candidates)
    assert any(c.tier == "single_club" for c in candidates)
    # multi_club candidates must have >=2 rich clubs, single_club exactly 1
    for c in candidates:
        if c.tier == "multi_club":
            assert c.n_rich_clubs >= 2
        else:
            assert c.n_rich_clubs == 1


def test_candidates_sorted_descending_by_score(con):
    candidates = selection.rank_candidates(con, limit=200)
    scores = [c.score for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_tier_filter_only_returns_requested_tier(con):
    single_only = selection.rank_candidates(con, tier="single_club", limit=200)
    assert all(c.tier == "single_club" for c in single_only)
