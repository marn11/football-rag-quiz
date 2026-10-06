"""Target-player selection for "guess the player" mode.

A player is a good riddle subject if they have teammates we can build clues from. How
*good* those connections are determines difficulty, not eligibility: even a one-match
cameo has teammates from that single match, so every player with at least one appearance
alongside someone else qualifies for at least "extreme" difficulty. See config.py's
DIFFICULTY_PRESETS for exactly what each band requires.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import duckdb

import config
from footy_quiz.db import connect


@dataclass
class PlayerCandidate:
    player_id: int
    player_name: str
    n_matches: int
    n_clubs: int
    n_rich_clubs: int
    difficulty: str
    score: float


def _build_base_tables(con: duckdb.DuckDBPyConnection) -> None:
    """(Re)builds the preset-independent temp tables: per-player stats and symmetric edges.

    Clubs only: national-team appearances (competition_international) are excluded from
    both n_matches/n_clubs here and from teammate_edges (see graph.py) -- a player's
    difficulty band should reflect only the club career a riddle can actually draw clues
    from, not caps that inflate their stats but never appear in any clue.
    """
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _player_stats AS
        SELECT a.player_id,
               COUNT(*) AS n_matches,
               COUNT(DISTINCT a.team_id) AS n_clubs
        FROM appearances a
        JOIN matches m ON m.match_id = a.match_id
        JOIN competitions c ON c.competition_id = m.competition_id AND c.season_id = m.season_id
        WHERE NOT c.competition_international
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


def _rich_club_counts(con: duckdb.DuckDBPyConnection, preset: dict) -> dict[int, int]:
    """Per-player count of "rich" clubs under one difficulty preset's thresholds."""
    rows = con.execute(
        f"""
        WITH club_strength AS (
            SELECT e.player_id, e.team_id,
                   COUNT(*) FILTER (
                       WHERE e.shared_matches >= {preset["min_shared_matches_for_strong_teammate"]}
                         AND ps.n_matches >= {preset["min_matches_for_strong_teammate"]}
                   ) AS n_strong_teammates
            FROM _edges_sym e
            JOIN _player_stats ps ON ps.player_id = e.teammate_id
            GROUP BY e.player_id, e.team_id
        )
        SELECT player_id, COUNT(*) AS n_rich_clubs
        FROM club_strength
        WHERE n_strong_teammates >= {preset["min_strong_teammates_per_rich_club"]}
        GROUP BY player_id
        """
    ).fetchall()
    return dict(rows)


def rank_candidates(
    con: duckdb.DuckDBPyConnection,
    difficulty: str = "any",
    competition_ids: Optional[list[int]] = None,
    limit: int = 500,
) -> list[PlayerCandidate]:
    """Full ranked candidate list with debug info (name/difficulty/score) -- the basis for
    `list_candidate_target_players`, exposed separately so callers can eyeball *why* a
    player was banded where they were.

    Each player is assigned the STRICTEST difficulty preset (see config.DIFFICULTY_ORDER)
    whose thresholds they satisfy, so bands are mutually exclusive.
    """
    _build_base_tables(con)
    rich_by_preset = {
        name: _rich_club_counts(con, preset) for name, preset in config.DIFFICULTY_PRESETS.items()
    }

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
        SELECT p.player_id, p.player_name, ps.n_matches, ps.n_clubs
        FROM players p
        JOIN _player_stats ps ON ps.player_id = p.player_id
        WHERE 1=1 {competition_filter}
        """
    ).fetchall()

    candidates: list[PlayerCandidate] = []
    for player_id, player_name, n_matches, n_clubs in rows:
        assigned_difficulty = None
        assigned_n_rich = 0
        for name in config.DIFFICULTY_ORDER:
            preset = config.DIFFICULTY_PRESETS[name]
            n_rich = rich_by_preset[name].get(player_id, 0)
            if n_matches >= preset["min_matches"] and n_rich >= preset["min_rich_clubs"]:
                assigned_difficulty = name
                assigned_n_rich = n_rich
                break

        if assigned_difficulty is None:
            continue  # no teammate connection at all, under even the loosest preset
        if difficulty != "any" and assigned_difficulty != difficulty:
            continue

        score = 3 * assigned_n_rich + 2 * math.log(n_matches + 1)
        candidates.append(
            PlayerCandidate(
                player_id, player_name, n_matches, n_clubs, assigned_n_rich, assigned_difficulty, score
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:limit]


def list_candidate_target_players(
    difficulty: str = "normal",
    competition_ids: Optional[list[int]] = None,
    limit: int = 500,
) -> list[int]:
    """Public contract function: ranked target-player ids for one difficulty band,
    best riddle subjects (within that band) first."""
    con = connect()
    try:
        candidates = rank_candidates(con, difficulty, competition_ids, limit)
    finally:
        con.close()
    return [c.player_id for c in candidates]


def get_difficulty(con: duckdb.DuckDBPyConnection, player_id: int) -> Optional[str]:
    """The single difficulty band one player is assigned -- used by riddle.get_riddle()
    to know which preset's thresholds to re-derive clue material with. None if the player
    doesn't qualify for any band (no teammate connection at all, even under "extreme")."""
    for c in rank_candidates(con, difficulty="any", limit=100_000):
        if c.player_id == player_id:
            return c.difficulty
    return None
