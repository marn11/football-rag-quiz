"""Sanity checks on the built DuckDB file. Requires `uv run scripts/build_db.py` to have run."""

import pytest

from footy_quiz import db
from footy_quiz.ingest import DEFAULT_DB_PATH


@pytest.fixture(scope="module")
def con():
    if not DEFAULT_DB_PATH.exists():
        pytest.skip(f"{DEFAULT_DB_PATH} not built yet -- run scripts/build_db.py first")
    conn = db.connect()
    yield conn
    conn.close()


def test_competitions_count(con):
    # Top-flight domestic leagues (one row per competition-season) plus the in-scope
    # international/continental competitions -- see footy_quiz/ingest.py's
    # _IN_SCOPE_SUB_TYPES. Men's professional football only -- the source has no
    # women's competitions at all, so no gender filter is needed at ingest time.
    n = con.sql("SELECT COUNT(*) FROM competitions").fetchone()[0]
    assert n > 200
    assert con.sql("SELECT DISTINCT competition_gender FROM competitions").fetchall() == [
        ("male",)
    ]


def test_matches_count(con):
    n = con.sql("SELECT COUNT(*) FROM matches").fetchone()[0]
    assert n > 60_000


def test_appearances_in_expected_range(con):
    n = con.sql("SELECT COUNT(*) FROM appearances").fetchone()[0]
    assert 2_000_000 <= n <= 3_000_000


def test_squad_sizes_are_plausible(con):
    # "Played with" = shared a squad list (starting lineup + bench), so the vast majority
    # of (match, team) squads should look like a real matchday squad, not a handful of
    # players or an absurdly bloated one. A small minority (~0.4%) fall outside this --
    # real upstream data gaps for some older/obscure matches, not a bug -- so this checks
    # the bulk of the distribution, not a strict universal bound.
    rows = con.sql(
        "SELECT COUNT(*) AS n FROM appearances GROUP BY match_id, team_id"
    ).fetchall()
    counts = [n for (n,) in rows]
    assert counts  # non-empty
    assert max(counts) <= 30
    in_range = sum(1 for n in counts if 10 <= n <= 30)
    assert in_range / len(counts) > 0.99


def test_no_orphan_foreign_keys(con):
    orphans = con.sql(
        "SELECT COUNT(*) FROM appearances a LEFT JOIN matches m USING (match_id) "
        "WHERE m.match_id IS NULL"
    ).fetchone()[0]
    assert orphans == 0


def test_players_have_normalized_names(con):
    bad = con.sql(
        "SELECT COUNT(*) FROM players WHERE normalized_name IS NULL OR normalized_name = ''"
    ).fetchone()[0]
    assert bad == 0


def test_teams_have_crest_urls(con):
    bad = con.sql("SELECT COUNT(*) FROM teams WHERE crest_url IS NULL").fetchone()[0]
    assert bad == 0
