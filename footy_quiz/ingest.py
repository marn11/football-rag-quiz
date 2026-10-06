"""Loads the vendored StatsBomb JSON (competitions/matches/lineups) into DuckDB.

Deliberately skips data/events/** -- the co-appearance riddle mechanic only needs
who played alongside whom, for which team, in which competition/season.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VENDOR_DIR = ROOT / "vendor" / "open-data" / "data"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
DEFAULT_DB_PATH = ROOT / "data" / "footy_quiz.duckdb"


def build(db_path: Path = DEFAULT_DB_PATH, vendor_dir: Path = DEFAULT_VENDOR_DIR) -> None:
    """(Re)builds the DuckDB file from scratch from the vendored JSON data."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    con = duckdb.connect(str(db_path))
    try:
        con.execute(SCHEMA_PATH.read_text())
        _load_competitions(con, vendor_dir)
        _load_teams_and_matches(con, vendor_dir)
        _load_players_and_appearances(con, vendor_dir)
    finally:
        con.close()


def _load_competitions(con: duckdb.DuckDBPyConnection, vendor_dir: Path) -> None:
    # Men's football only.
    path = vendor_dir / "competitions.json"
    con.execute(
        f"""
        INSERT INTO competitions
        SELECT competition_id, season_id, competition_name, season_name,
               country_name, competition_gender, competition_international
        FROM read_json_auto('{path.as_posix()}')
        WHERE competition_gender = 'male'
        """
    )


def _load_teams_and_matches(con: duckdb.DuckDBPyConnection, vendor_dir: Path) -> None:
    # Inner join against the (already male-only) `competitions` table: this is the single
    # source of truth for the gender filter, and guarantees every match's (competition_id,
    # season_id) satisfies the `matches` table's FOREIGN KEY by construction.
    matches_glob = (vendor_dir / "matches" / "*" / "*.json").as_posix()
    con.execute(
        f"""
        CREATE TEMP TABLE _raw_matches AS
        SELECT m.*
        FROM read_json_auto('{matches_glob}') m
        JOIN competitions c
          ON c.competition_id = m.competition.competition_id
         AND c.season_id = m.season.season_id
        """
    )

    con.execute(
        """
        INSERT INTO teams
        SELECT team_id, any_value(team_name), any_value(country_name), any_value(team_gender)
        FROM (
            SELECT home_team.home_team_id AS team_id,
                   home_team.home_team_name AS team_name,
                   home_team.country.name AS country_name,
                   home_team.home_team_gender AS team_gender
            FROM _raw_matches
            UNION ALL
            SELECT away_team.away_team_id,
                   away_team.away_team_name,
                   away_team.country.name,
                   away_team.away_team_gender
            FROM _raw_matches
        )
        GROUP BY team_id
        """
    )

    con.execute(
        """
        INSERT INTO matches
        SELECT match_id,
               competition.competition_id,
               season.season_id,
               CAST(match_date AS DATE),
               competition_stage.name,
               home_team.home_team_id,
               away_team.away_team_id,
               home_score,
               away_score
        FROM _raw_matches
        """
    )


def _load_players_and_appearances(con: duckdb.DuckDBPyConnection, vendor_dir: Path) -> None:
    lineups_glob = (vendor_dir / "lineups" / "*.json").as_posix()
    con.execute(
        f"CREATE TEMP TABLE _raw_lineups AS "
        f"SELECT *, filename FROM read_json_auto('{lineups_glob}', filename=true)"
    )

    # One row per (match_id, team_id, player) named in that match's squad list. "Played
    # with" means shared a squad list for a match -- it does NOT require both players to
    # have actually featured (positions can be empty for an unused substitute); only
    # orphaned match_ids (lineup files with no matching record in `matches`, including
    # women's football matches now that `matches` is men's-only) are excluded.
    con.execute(
        """
        CREATE TEMP TABLE _lineup_entries AS
        SELECT
            CAST(regexp_extract(filename, '(\\d+)\\.json$', 1) AS INTEGER) AS match_id,
            team_id,
            p.player_id AS player_id,
            p.player_name AS player_name,
            p.player_nickname AS player_nickname,
            p.country.name AS country_name,
            p.jersey_number AS jersey_number,
            CASE WHEN len(p.positions) > 0 THEN p.positions[1].position ELSE NULL END
                AS primary_position
        FROM _raw_lineups, UNNEST(lineup) AS t(p)
        """
    )

    n_total = con.execute("SELECT COUNT(*) FROM _lineup_entries").fetchone()[0]
    con.execute(
        """
        CREATE TEMP TABLE _in_scope AS
        SELECT * FROM _lineup_entries
        WHERE match_id IN (SELECT match_id FROM matches)
        """
    )
    n_in_scope = con.execute("SELECT COUNT(*) FROM _in_scope").fetchone()[0]
    logger.info(
        "lineup entries: %d total, %d in scope (orphan/women's-football match_ids excluded: %d)",
        n_total,
        n_in_scope,
        n_total - n_in_scope,
    )

    con.execute(
        """
        INSERT INTO players
        SELECT player_id,
               mode(player_name),
               mode(player_nickname),
               lower(strip_accents(mode(player_name))),
               mode(country_name)
        FROM _in_scope
        GROUP BY player_id
        """
    )

    con.execute(
        """
        INSERT INTO appearances
        SELECT DISTINCT match_id, team_id, player_id, jersey_number, primary_position
        FROM _in_scope
        """
    )
