"""Builds the co-appearance ("teammate") graph from `appearances`.

Two players are connected if they were named in the same team's squad list for the same
match (see footy_quiz.ingest for exactly what counts as an "appearance"). This is plain SQL
self-joins, not a graph library -- `appearances` is small enough (~100k rows) that DuckDB
resolves the grouped self-join in well under a second, so networkx et al. would just be
dead weight here.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from footy_quiz.ingest import DEFAULT_DB_PATH

# Shared by both queries below: pairs up every two players who appear in the same
# (match_id, team_id) squad list, with player_id_a < player_id_b so each unordered pair
# is produced once, not twice (a1/a2 would otherwise double-count (x,y) and (y,x)).
_PAIR_JOIN = """
    FROM appearances a1
    JOIN appearances a2
      ON a1.match_id = a2.match_id
     AND a1.team_id = a2.team_id
     AND a1.player_id < a2.player_id
    JOIN matches m ON m.match_id = a1.match_id
"""


def build(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("DELETE FROM teammate_edge_contexts")
    con.execute("DELETE FROM teammate_edges")

    con.execute(
        f"""
        INSERT INTO teammate_edges
        SELECT a1.player_id AS player_id_a,
               a2.player_id AS player_id_b,
               a1.team_id,
               COUNT(*) AS shared_matches,
               MIN(m.match_date) AS first_shared_date,
               MAX(m.match_date) AS last_shared_date
        {_PAIR_JOIN}
        GROUP BY a1.player_id, a2.player_id, a1.team_id
        """
    )

    con.execute(
        f"""
        INSERT INTO teammate_edge_contexts
        SELECT a1.player_id AS player_id_a,
               a2.player_id AS player_id_b,
               a1.team_id,
               m.competition_id,
               m.season_id,
               COUNT(*) AS matches_in_context
        {_PAIR_JOIN}
        GROUP BY a1.player_id, a2.player_id, a1.team_id, m.competition_id, m.season_id
        """
    )

    # Serve-time lookups are "neighbors of player X" -- accelerate both sides of the pair.
    con.execute("CREATE INDEX IF NOT EXISTS idx_teammate_edges_a ON teammate_edges (player_id_a)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_teammate_edges_b ON teammate_edges (player_id_b)")


def main(db_path: Path = DEFAULT_DB_PATH) -> None:
    con = duckdb.connect(str(db_path))
    try:
        build(con)
    finally:
        con.close()


if __name__ == "__main__":
    main()
