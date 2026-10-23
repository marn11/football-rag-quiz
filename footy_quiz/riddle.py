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
    competition_id: str
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


def _best_context(
    con: duckdb.DuckDBPyConnection,
    target_player_id: int,
    teammate_id: int,
    team_id: int,
    used_years: tuple[int, ...] = (),
    rng: Optional[random.Random] = None,
) -> Optional[tuple[str, int, str, str]]:
    """A (competition_id, season_id, competition_name, season_name) for this (target,
    teammate, club) triple. Among the seasons they genuinely overlapped in (at least half
    as well-attested as the best one, so we never cite a 1-match cameo season over a real
    stint), prefers the one FARTHEST from `used_years` (seasons already used by other clues
    in this riddle) -- otherwise clues from a player's career tend to read as consecutive
    years. With no years used yet, picks randomly (rng) or the best-attested (no rng)."""
    player_id_a, player_id_b = sorted((target_player_id, teammate_id))
    rows = con.execute(
        """
        SELECT ctx.competition_id, ctx.season_id, c.competition_name, c.season_name,
               ctx.matches_in_context
        FROM teammate_edge_contexts ctx
        JOIN competitions c ON c.competition_id = ctx.competition_id AND c.season_id = ctx.season_id
        WHERE ctx.player_id_a = ? AND ctx.player_id_b = ? AND ctx.team_id = ?
        ORDER BY ctx.matches_in_context DESC, c.season_name ASC
        """,
        [player_id_a, player_id_b, team_id],
    ).fetchall()
    if not rows:
        return None
    best = rows[0][4]
    eligible = [r for r in rows if r[4] * 2 >= best]
    if used_years:
        chosen = max(eligible, key=lambda r: (min(abs(r[1] - y) for y in used_years), r[4]))
    elif rng is not None:
        chosen = rng.choice(eligible)
    else:
        chosen = eligible[0]
    return chosen[:4]


def _club_years(con: duckdb.DuckDBPyConnection, target_player_id: int) -> dict[int, list[int]]:
    """team_id -> seasons the target has any shared-squad context at that club."""
    years: dict[int, list[int]] = {}
    rows = con.execute(
        """
        SELECT DISTINCT team_id, season_id FROM teammate_edge_contexts
        WHERE player_id_a = ? OR player_id_b = ?
        """,
        [target_player_id, target_player_id],
    ).fetchall()
    for team_id, season_id in rows:
        years.setdefault(team_id, []).append(season_id)
    return years


def _season_start_year(season_name: str) -> int:
    # season_name is like "2016/2017" or a bare "2016" -- take the leading digits.
    digits = "".join(ch for ch in season_name[:4] if ch.isdigit())
    return int(digits) if digits else 0


def _spread_club_order(
    clubs: list[int],
    years_by_club: dict[int, list[int]],
    used_clubs: set[int],
    rng: random.Random,
) -> list[int]:
    """Greedy reorder so each next club's seasons are as far as possible from the seasons
    of the clubs already picked -- a riddle whose clues are 2023, 2024, 2025 is far less
    interesting than one spanning a whole career. `clubs` arrives shuffled, so ties (and
    the first pick) stay random."""
    picked_years = [y for t in used_clubs for y in years_by_club.get(t, [])]
    remaining = list(clubs)
    ordered: list[int] = []
    while remaining:
        def gap(tid: int) -> int:
            ys = years_by_club.get(tid, [])
            if not ys or not picked_years:
                return 0
            return max(min(abs(y - p) for p in picked_years) for y in ys)

        best_gap = max(gap(t) for t in remaining)
        nxt = next(t for t in remaining if gap(t) == best_gap)
        remaining.remove(nxt)
        ordered.append(nxt)
        picked_years.extend(years_by_club.get(nxt, []))
    return ordered


def _select_clue_pairs(
    qualifying: list[tuple[int, int, int]],
    max_clues: int,
    prefer_recurring: bool = True,
    rng: Optional[random.Random] = None,
    years_by_club: Optional[dict[int, list[int]]] = None,
) -> list[tuple[int, int]]:
    """Picks up to max_clues (teammate_id, team_id) pairs from every qualifying
    (teammate, club) connection -- pure selection logic, no DB access, so it's directly
    unit-testable. Any club with at least one qualifying teammate is a valid clue source
    (not just "rich" clubs, selection.py's difficulty-TIERING concept), so a well-traveled
    player's riddle reflects the breadth of clubs they actually played for.

    1. If prefer_recurring: a recurring co-star (same teammate shared across >=2 clubs),
       one clue per club they share. get_riddle only turns this on for a minority of
       riddles -- with full-career data nearly every player has such a co-star, so making
       it the default turned almost every riddle into "X, X, Y".
    2. One clue per still-unused DISTINCT club, preferring a teammate not already shown.

    No same-club backfill: two clues both saying "X at PSG, 2021/22" and "Y at PSG,
    2021/22" reads as arbitrary padding, not information. A player with fewer qualifying
    clubs than max_clues just gets fewer, honest clues.

    rng=None is fully deterministic (strongest teammate per club, strongest clubs first --
    what the unit tests rely on). Given an rng, clubs are shuffled and each club's
    teammate is drawn from its top 3, so the same player doesn't get the same riddle
    every time.
    """
    clubs_by_teammate: dict[int, set[int]] = {}
    strength_by_teammate: dict[int, int] = {}
    for teammate_id, team_id, shared_matches in qualifying:
        clubs_by_teammate.setdefault(teammate_id, set()).add(team_id)
        strength_by_teammate[teammate_id] = strength_by_teammate.get(teammate_id, 0) + shared_matches

    # Fully deterministic tie-break (qualifying's row order comes from an unordered query).
    recurring = sorted(
        (tid for tid, clubs in clubs_by_teammate.items() if len(clubs) >= 2),
        key=lambda tid: (-len(clubs_by_teammate[tid]), -strength_by_teammate[tid], tid),
    )

    chosen: list[tuple[int, int]] = []  # (teammate_id, team_id), one per clue
    used_clubs: set[int] = set()
    used_teammates: set[int] = set()

    if prefer_recurring and recurring:
        co_star = recurring[0]
        for team_id in sorted(clubs_by_teammate[co_star]):
            if len(chosen) >= max_clues:
                break
            chosen.append((co_star, team_id))
            used_clubs.add(team_id)
            used_teammates.add(co_star)

    candidates_by_club: dict[int, list[tuple[int, int]]] = {}  # team_id -> [(shared, teammate)]
    for teammate_id, team_id, shared_matches in qualifying:
        if team_id not in used_clubs:
            candidates_by_club.setdefault(team_id, []).append((shared_matches, teammate_id))
    for cands in candidates_by_club.values():
        cands.sort(key=lambda c: (-c[0], c[1]))

    club_order = sorted(candidates_by_club, key=lambda tid: (-candidates_by_club[tid][0][0], tid))
    if rng is not None:
        rng.shuffle(club_order)
        if years_by_club:
            club_order = _spread_club_order(club_order, years_by_club, used_clubs, rng)

    for team_id in club_order:
        if len(chosen) >= max_clues:
            break
        cands = candidates_by_club[team_id]
        fresh = [c for c in cands if c[1] not in used_teammates] or cands
        pool = fresh[:3] if rng is not None else fresh[:1]
        _, teammate_id = rng.choice(pool) if rng is not None else pool[0]
        chosen.append((teammate_id, team_id))
        used_clubs.add(team_id)
        used_teammates.add(teammate_id)

    return chosen


RECURRING_COSTAR_PROBABILITY = 0.2
MIN_CLUES, MAX_CLUES = 2, 5


def get_riddle(
    target_player_id: int,
    max_clues: Optional[int] = None,
    difficulty: Optional[str] = None,
    prefer_recurring: Optional[bool] = None,
    rng: Optional[random.Random] = None,
) -> Riddle:
    """`difficulty`, if already known (e.g. the API layer just picked this player from
    an already difficulty-filtered candidate list), skips re-deriving it via
    selection.get_difficulty() -- that re-runs rank_candidates() over every player in
    the dataset, which is wasteful to pay for twice in the same request."""
    con = connect()
    try:
        if difficulty is None:
            difficulty = selection.get_difficulty(con, target_player_id)
            if difficulty is None:
                raise ValueError(f"player {target_player_id} has no qualifying teammate connections")
        preset = config.DIFFICULTY_PRESETS[difficulty]

        qualifying = _qualifying_teammates(con, target_player_id, preset)
        rng = rng or random.Random()
        if max_clues is None:
            # Uniform 2-5, so riddle length varies; a player with fewer qualifying clubs
            # than this still just gets fewer, honest clues.
            max_clues = rng.randint(MIN_CLUES, MAX_CLUES)
        if prefer_recurring is None:
            prefer_recurring = rng.random() < RECURRING_COSTAR_PROBABILITY
        chosen = _select_clue_pairs(
            qualifying, max_clues, prefer_recurring, rng, _club_years(con, target_player_id)
        )

        clues: list[Clue] = []
        used_years: list[int] = []
        for teammate_id, team_id in chosen:
            context = _best_context(
                con, target_player_id, teammate_id, team_id, tuple(used_years), rng
            )
            if context is None:
                continue
            used_years.append(context[1])
            competition_id, season_id, competition_name, season_name = context

            (team_name, team_crest_url) = con.execute(
                "SELECT team_name, crest_url FROM teams WHERE team_id = ?", [team_id]
            ).fetchone()
            (teammate_name, teammate_photo_url) = con.execute(
                "SELECT COALESCE(player_nickname, player_name), photo_url FROM players WHERE player_id = ?",
                [teammate_id],
            ).fetchone()
            # players.photo_url is the direct transfermarkt photo (the common case); the
            # player's linked Wikidata photo is the fallback when that's just a placeholder.
            if teammate_photo_url is None:
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
