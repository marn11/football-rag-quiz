"""Target-player selection for "guess the player" mode.

A player is a good riddle subject if they have enough recognizable teammates at enough
different clubs for a multi-step clue chain. Sparsity in the open data (StatsBomb only
covers partial seasons/competitions) means many real careers are only partially
represented, so this tiers/scores candidates rather than hard-filtering on raw "played
for N clubs" counts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Optional

import duckdb

import config
from footy_quiz.db import connect

Tier = Literal["multi_club", "single_club", "reject"]


@dataclass
class PlayerCandidate:
    player_id: int
    player_name: str
    n_matches: int
    n_clubs: int
    n_rich_clubs: int
    tier: Tier
    score: float


def _build_stats_tables(con: duckdb.DuckDBPyConnection) -> None:
    """(Re)builds the temp tables the ranking query reads from, scoped to this connection."""
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _player_stats AS
        SELECT a.player_id,
               COUNT(*) AS n_matches,
               COUNT(DISTINCT a.team_id) AS n_clubs,
               MAX(CASE WHEN c.competition_international THEN 1 ELSE 0 END) AS has_international
        FROM appearances a
        JOIN matches m ON m.match_id = a.match_id
        JOIN competitions c ON c.competition_id = m.competition_id AND c.season_id = m.season_id
        GROUP BY a.player_id
        """
    )

    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _edges_sym AS
        SELECT player_id_a AS player_id, player_id_b AS teammate_id, team_id, shared_matches
        FROM teammate_edges
        UNION ALL
        SELECT player_id_b AS player_id, player_id_a AS teammate_id, team_id, shared_matches
        FROM teammate_edges
        """
    )

    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _player_club_strength AS
        SELECT e.player_id, e.team_id,
               COUNT(*) FILTER (
                   WHERE e.shared_matches >= {config.MIN_SHARED_MATCHES_FOR_STRONG_TEAMMATE}
                     AND ps.n_matches >= {config.MIN_MATCHES_FOR_STRONG_TEAMMATE}
               ) AS n_strong_teammates
        FROM _edges_sym e
        JOIN _player_stats ps ON ps.player_id = e.teammate_id
        GROUP BY e.player_id, e.team_id
        """
    )


def rank_candidates(
    con: duckdb.DuckDBPyConnection,
    min_matches: int = config.MIN_MATCHES_FOR_TARGET,
    min_strong_teammates_per_club: int = config.MIN_STRONG_TEAMMATES_PER_RICH_CLUB,
    tier: str = "any",
    competition_ids: Optional[list[int]] = None,
    limit: int = 500,
) -> list[PlayerCandidate]:
    """Full ranked candidate list with debug info (name/tier/score) -- the basis for
    `list_candidate_target_players`, exposed separately so callers can eyeball *why* a
    player was ranked where they were."""
    _build_stats_tables(con)

    competition_filter = ""
    if competition_ids:
        ids_csv = ",".join(str(i) for i in competition_ids)
        competition_filter = f"""
            AND EXISTS (
                SELECT 1 FROM appearances a2
                JOIN matches m2 ON m2.match_id = a2.match_id
                WHERE a2.player_id = p.player_id AND m2.competition_id IN ({ids_csv})
            )
        """

    rows = con.execute(
        f"""
        WITH rich_clubs AS (
            SELECT player_id, COUNT(*) AS n_rich_clubs
            FROM _player_club_strength
            WHERE n_strong_teammates >= {min_strong_teammates_per_club}
            GROUP BY player_id
        )
        SELECT p.player_id, p.player_name, ps.n_matches, ps.n_clubs,
               COALESCE(rc.n_rich_clubs, 0) AS n_rich_clubs, ps.has_international
        FROM players p
        JOIN _player_stats ps ON ps.player_id = p.player_id
        LEFT JOIN rich_clubs rc ON rc.player_id = p.player_id
        WHERE ps.n_matches >= {min_matches}
        {competition_filter}
        """
    ).fetchall()

    candidates: list[PlayerCandidate] = []
    for player_id, player_name, n_matches, n_clubs, n_rich_clubs, has_international in rows:
        if n_rich_clubs >= 2:
            tier_value: Tier = "multi_club"
        elif n_rich_clubs == 1:
            tier_value = "single_club"
        else:
            tier_value = "reject"

        if tier_value == "reject":
            continue
        if tier != "any" and tier_value != tier:
            continue

        score = 3 * n_rich_clubs + 2 * math.log(n_matches + 1) + (1 if has_international else 0)
        candidates.append(
            PlayerCandidate(
                player_id, player_name, n_matches, n_clubs, n_rich_clubs, tier_value, score
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:limit]


def list_candidate_target_players(
    min_matches: int = config.MIN_MATCHES_FOR_TARGET,
    min_strong_teammates_per_club: int = config.MIN_STRONG_TEAMMATES_PER_RICH_CLUB,
    tier: str = "any",
    competition_ids: Optional[list[int]] = None,
    limit: int = 500,
) -> list[int]:
    """Public contract function: ranked target-player ids, best riddle subjects first."""
    con = connect()
    try:
        candidates = rank_candidates(
            con, min_matches, min_strong_teammates_per_club, tier, competition_ids, limit
        )
    finally:
        con.close()
    return [c.player_id for c in candidates]
