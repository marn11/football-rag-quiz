"""Sanity checks on the teammate-graph tables. Requires build_db.py + build_graph.py to have run."""

import pytest

from footy_quiz import db
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


def test_no_edges_from_international_competitions(con):
    # Clubs only -- a riddle must never read "played with X for France". Every edge
    # context's competition must be a club competition (competition_international = false).
    bad = con.sql(
        """
        SELECT COUNT(*) FROM teammate_edge_contexts ctx
        JOIN competitions c
          ON c.competition_id = ctx.competition_id AND c.season_id = ctx.season_id
        WHERE c.competition_international
        """
    ).fetchone()[0]
    assert bad == 0


def test_pairs_are_canonically_ordered(con):
    assert con.sql(
        "SELECT COUNT(*) FROM teammate_edges WHERE player_id_a >= player_id_b"
    ).fetchone()[0] == 0


def test_no_duplicate_edges(con):
    dupes = con.sql(
        "SELECT COUNT(*) FROM "
        "(SELECT 1 FROM teammate_edges GROUP BY player_id_a, player_id_b, team_id "
        "HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    assert dupes == 0


def test_shared_matches_matches_manual_recount(con):
    # Cristiano Ronaldo & Marcelo at Real Madrid (team_id 220) -- a well-known, long-running
    # pairing, used as a ground-truth spot check against a hand-written recount.
    ronaldo, marcelo, real_madrid = 5207, 5552, 220
    claimed = con.sql(
        "SELECT shared_matches FROM teammate_edges "
        f"WHERE player_id_a = {ronaldo} AND player_id_b = {marcelo} AND team_id = {real_madrid}"
    ).fetchone()[0]
    manual = con.sql(
        f"""
        SELECT COUNT(*) FROM appearances a1
        JOIN appearances a2 ON a1.match_id = a2.match_id AND a1.team_id = a2.team_id
        WHERE a1.player_id = {ronaldo} AND a2.player_id = {marcelo} AND a1.team_id = {real_madrid}
        """
    ).fetchone()[0]
    assert claimed == manual == 48


def test_contexts_sum_to_edge_totals(con):
    mismatches = con.sql(
        """
        SELECT COUNT(*) FROM (
            SELECT e.shared_matches, SUM(c.matches_in_context) AS summed
            FROM teammate_edges e
            JOIN teammate_edge_contexts c USING (player_id_a, player_id_b, team_id)
            GROUP BY e.player_id_a, e.player_id_b, e.team_id, e.shared_matches
            HAVING e.shared_matches != summed
        )
        """
    ).fetchone()[0]
    assert mismatches == 0
