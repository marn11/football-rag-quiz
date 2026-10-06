"""Deterministic riddle generation for "guess the player" mode.

Given a target player (already chosen via footy_quiz.selection), builds up to
`max_clues` clue cards: each names one teammate the target shared a club with, plus
the club's crest and the teammate's photo (footy_quiz.media), and the actual
competition/season the connection happened in. Clues are returned SHUFFLED, not
chronological or fame-ordered -- recognizing a player's career trajectory is itself a
strong signal, so a "reorder chronologically" hint is more interesting if the default
view scrambles it (the frontend re-sorts client-side using each clue's season_start_year;
no backend call needed for that).

Teammates who shared the target with >=2 different clubs ("recurring co-star", e.g.
Di María & Ramos: Real Madrid, then PSG) are deliberately preferred over diversifying
across different random teammates -- it's a stronger, more memorable clue.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

import duckdb

import config
from footy_quiz import media, selection
from footy_quiz.db import connect


@dataclass
class Clue:
    team_id: int
    team_name: str
    team_crest_url: Optional[str]
    teammate_player_id: int
    teammate_display_name: str
    teammate_photo_url: Optional[str]
    competition_id: int
    season_id: int
    competition_name: str
    season_name: str
    season_start_year: int  # for client-side chronological sorting ("reorder" hint)
    text: str


@dataclass
class Riddle:
    target_player_id: int
    difficulty: str
    clues: list[Clue]


def _qualifying_teammates(
    con: duckdb.DuckDBPyConnection, target_player_id: int, preset: dict
) -> list[tuple[int, int, int]]:
    """(teammate_id, team_id, shared_matches) triples meeting one difficulty preset's
    "strong teammate" thresholds -- mirrors selection.py's logic but scoped to one player
    (selection.py ranks everyone at once; here we just need one player's own detail)."""
    rows = con.execute(
        f"""
        WITH teammate_stats AS (
            SELECT a.player_id, COUNT(*) AS n_matches
            FROM appearances a
            JOIN matches m ON m.match_id = a.match_id
            JOIN competitions c ON c.competition_id = m.competition_id AND c.season_id = m.season_id
            WHERE NOT c.competition_international
            GROUP BY a.player_id
        ),
        target_edges AS (
            SELECT CASE WHEN player_id_a = ? THEN player_id_b ELSE player_id_a END AS teammate_id,
                   team_id, shared_matches
            FROM teammate_edges
            WHERE player_id_a = ? OR player_id_b = ?
        )
        SELECT te.teammate_id, te.team_id, te.shared_matches
        FROM target_edges te
        JOIN teammate_stats ts ON ts.player_id = te.teammate_id
        WHERE te.shared_matches >= {preset["min_shared_matches_for_strong_teammate"]}
          AND ts.n_matches >= {preset["min_matches_for_strong_teammate"]}
        """,
        [target_player_id, target_player_id, target_player_id],
    ).fetchall()
    return rows


def _rich_clubs(qualifying: list[tuple[int, int, int]], min_strong_teammates: int) -> set[int]:
    teammates_by_club: dict[int, set[int]] = {}
    for teammate_id, team_id, _ in qualifying:
        teammates_by_club.setdefault(team_id, set()).add(teammate_id)
    return {tid for tid, mates in teammates_by_club.items() if len(mates) >= min_strong_teammates}


def _best_context(
    con: duckdb.DuckDBPyConnection, target_player_id: int, teammate_id: int, team_id: int
) -> Optional[tuple[int, int, str, str]]:
    """The (competition_id, season_id, competition_name, season_name) with the most shared
    matches for this (target, teammate, club) triple -- tie-break earliest season."""
    player_id_a, player_id_b = sorted((target_player_id, teammate_id))
    return con.execute(
        """
        SELECT ctx.competition_id, ctx.season_id, c.competition_name, c.season_name
        FROM teammate_edge_contexts ctx
        JOIN competitions c ON c.competition_id = ctx.competition_id AND c.season_id = ctx.season_id
        WHERE ctx.player_id_a = ? AND ctx.player_id_b = ? AND ctx.team_id = ?
        ORDER BY ctx.matches_in_context DESC, c.season_name ASC
        LIMIT 1
        """,
        [player_id_a, player_id_b, team_id],
    ).fetchone()


def _season_start_year(season_name: str) -> int:
    # season_name is like "2016/2017" or a bare "2016" -- take the leading digits.
    digits = "".join(ch for ch in season_name[:4] if ch.isdigit())
    return int(digits) if digits else 0


def get_riddle(target_player_id: int, max_clues: int = 3) -> Riddle:
    con = connect(read_only=False)  # media lookups may need to write a cache entry
    try:
        difficulty = selection.get_difficulty(con, target_player_id)
        if difficulty is None:
            raise ValueError(f"player {target_player_id} has no qualifying teammate connections")
        preset = config.DIFFICULTY_PRESETS[difficulty]

        qualifying = _qualifying_teammates(con, target_player_id, preset)
        rich_clubs = _rich_clubs(qualifying, preset["min_strong_teammates_per_rich_club"])
        qualifying = [row for row in qualifying if row[1] in rich_clubs]

        # Recurring co-star detection: teammate_id -> the rich clubs they share with target.
        clubs_by_teammate: dict[int, set[int]] = {}
        for teammate_id, team_id, _ in qualifying:
            clubs_by_teammate.setdefault(teammate_id, set()).add(team_id)

        recurring = sorted(
            (tid for tid, clubs in clubs_by_teammate.items() if len(clubs) >= 2),
            key=lambda tid: -len(clubs_by_teammate[tid]),
        )

        chosen: list[tuple[int, int]] = []  # (teammate_id, team_id), one per clue
        used_clubs: set[int] = set()

        if recurring:
            co_star = recurring[0]
            for team_id in sorted(clubs_by_teammate[co_star]):
                if len(chosen) >= max_clues:
                    break
                chosen.append((co_star, team_id))
                used_clubs.add(team_id)

        # Fill remaining slots: strongest teammate at each still-unused rich club,
        # richest clubs (by that teammate's shared_matches) first.
        best_per_club: dict[int, tuple[int, int]] = {}  # team_id -> (teammate_id, shared_matches)
        for teammate_id, team_id, shared_matches in qualifying:
            if team_id in used_clubs:
                continue
            current = best_per_club.get(team_id)
            if current is None or shared_matches > current[1]:
                best_per_club[team_id] = (teammate_id, shared_matches)

        for team_id in sorted(best_per_club, key=lambda tid: -best_per_club[tid][1]):
            if len(chosen) >= max_clues:
                break
            teammate_id, _ = best_per_club[team_id]
            chosen.append((teammate_id, team_id))
            used_clubs.add(team_id)

        clues: list[Clue] = []
        for teammate_id, team_id in chosen:
            context = _best_context(con, target_player_id, teammate_id, team_id)
            if context is None:
                continue
            competition_id, season_id, competition_name, season_name = context

            (team_name,) = con.execute(
                "SELECT team_name FROM teams WHERE team_id = ?", [team_id]
            ).fetchone()
            (teammate_name,) = con.execute(
                "SELECT COALESCE(player_nickname, player_name) FROM players WHERE player_id = ?",
                [teammate_id],
            ).fetchone()

            team_crest_url = media.get_or_fetch_team_crest(con, team_id)
            teammate_photo_url = media.get_or_fetch_player_photo(con, teammate_id)

            clues.append(
                Clue(
                    team_id=team_id,
                    team_name=team_name,
                    team_crest_url=team_crest_url,
                    teammate_player_id=teammate_id,
                    teammate_display_name=teammate_name,
                    teammate_photo_url=teammate_photo_url,
                    competition_id=competition_id,
                    season_id=season_id,
                    competition_name=competition_name,
                    season_name=season_name,
                    season_start_year=_season_start_year(season_name),
                    text=(
                        f"Played alongside {teammate_name} while at {team_name} "
                        f"in the {season_name} {competition_name}."
                    ),
                )
            )

        random.shuffle(clues)
        return Riddle(target_player_id=target_player_id, difficulty=difficulty, clues=clues)
    finally:
        con.close()
