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
    # Men's football only -- 13 of the 80 competitions in the raw data are women's.
    assert con.sql("SELECT COUNT(*) FROM competitions").fetchone()[0] == 67
    assert con.sql("SELECT DISTINCT competition_gender FROM competitions").fetchall() == [
        ("male",)
    ]


def test_matches_count(con):
    # Ground truth from the vendored data (men's competitions only), not the 4235
    # lineup-file count -- some lineup files reference match_ids absent from
    # matches/*/*.json entirely (upstream data gap) or belong to women's competitions.
    assert con.sql("SELECT COUNT(*) FROM matches").fetchone()[0] == 2651


def test_appearances_in_expected_range(con):
    n = con.sql("SELECT COUNT(*) FROM appearances").fetchone()[0]
    assert 90_000 <= n <= 110_000


def test_2019_ucl_final_appearances(con):
    # match_id 22912 = 2019 Champions League final. "Played with" = shared a squad list,
    # so the full 23-man squads count, not just the players who actually featured.
    rows = con.sql(
        "SELECT team_id, COUNT(*) FROM appearances WHERE match_id = 22912 GROUP BY team_id"
    ).fetchall()
    counts = {team_id: n for team_id, n in rows}
    assert len(counts) == 2
    assert all(n == 23 for n in counts.values())


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
