"""Loads the vendored transfermarkt-datasets DuckDB file (CC0, dcaribou/transfermarkt-
datasets) into our own schema via ATTACH + INSERT...SELECT -- no JSON/CSV parsing needed,
the source is already a DuckDB file.

Scoped to top-flight domestic leagues plus the major international/continental
competitions (World Cup, Euro, Copa América, AFCON, Asian Cup, Champions League, Europa
League) -- see _IN_SCOPE_SUB_TYPES. Domestic cups, super cups, qualifiers and playoffs are
deliberately excluded: lower value for the riddle's teammate-connection graph, and a lot
of extra data for little extra signal.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VENDOR_PATH = ROOT / "vendor" / "transfermarkt" / "transfermarkt-datasets.duckdb"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
DEFAULT_DB_PATH = ROOT / "data" / "footy_quiz.duckdb"

# competitions.sub_type values to keep -- see footy_quiz/ingest.py's module docstring.
_IN_SCOPE_SUB_TYPES = (
    "first_tier",
    "world_cup",
    "uefa_euro",
    "copa_america",
    "africa_cup_of_nations",
    "afc_asian_cup",
    "uefa_champions_league",
    "uefa_europa_league",
)

# Transfermarkt's crest/badge CDN is keyed directly by team id (works uniformly for both
# club and national-team ids) -- confirmed by direct request, no lookup/disambiguation
# needed, unlike footy_quiz.media's Wikipedia-backed player-photo fallback.
_CREST_URL_TEMPLATE = "https://tmssl.akamaized.net/images/wappen/head/{team_id}.png"


def _prettify_competition_name(slug: str) -> str:
    """Transfermarkt's `name` is a URL slug ('premier-league', 'uefa-champions-league') --
    title-case it and fix up the acronyms that title-casing mangles."""
    words = slug.replace("-", " ").title().split()
    fixups = {
        "Uefa": "UEFA", "Fifa": "FIFA", "Mls": "MLS", "Afc": "AFC", "Dfb": "DFB",
        "Laliga": "LaLiga", "Of": "of",
    }
    return " ".join(fixups.get(w, w) for w in words)


def build(db_path: Path = DEFAULT_DB_PATH, vendor_path: Path = DEFAULT_VENDOR_PATH) -> None:
    """(Re)builds the DuckDB file from scratch from the vendored transfermarkt-datasets file."""
    if not vendor_path.exists():
        raise FileNotFoundError(f"{vendor_path} not found -- run scripts/vendor_transfermarkt.sh first")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    con = duckdb.connect(str(db_path))
    try:
        con.execute(SCHEMA_PATH.read_text())
        con.execute(f"ATTACH '{vendor_path.as_posix()}' AS src (READ_ONLY)")

        sub_types_sql = ",".join(f"'{s}'" for s in _IN_SCOPE_SUB_TYPES)
        con.execute(
            f"""
            CREATE TEMP TABLE _in_scope_competitions AS
            SELECT competition_id, name, country_name, type, sub_type
            FROM src.competitions
            WHERE sub_type IN ({sub_types_sql})
            """
        )
        con.execute(
            f"""
            CREATE TEMP TABLE _in_scope_games AS
            SELECT g.*
            FROM src.games g
            JOIN _in_scope_competitions c ON c.competition_id = g.competition_id
            WHERE g.home_club_id IS NOT NULL AND g.away_club_id IS NOT NULL
            """
        )

        _load_competitions(con)
        _load_teams(con)
        _load_matches(con)
        _load_players_and_appearances(con)

        con.execute("DETACH src")
    finally:
        con.close()


def _load_competitions(con: duckdb.DuckDBPyConnection) -> None:
    rows = con.execute(
        """
        SELECT DISTINCT g.competition_id, CAST(g.season AS INTEGER) AS season_id,
               c.name, c.country_name, c.type
        FROM _in_scope_games g
        JOIN _in_scope_competitions c ON c.competition_id = g.competition_id
        """
    ).fetchall()
    con.executemany(
        "INSERT INTO competitions VALUES (?, ?, ?, ?, ?, 'male', ?)",
        [
            (comp_id, season_id, _prettify_competition_name(name), str(season_id), country, type_ == "national_team_competition")
            for comp_id, season_id, name, country, type_ in rows
        ],
    )


def _load_teams(con: duckdb.DuckDBPyConnection) -> None:
    # Clubs (country via their domestic competition) + national teams (country direct) +
    # a fallback for the small number of game participants (~1% of in-scope games) whose
    # id isn't in either source table -- using the name/id the game itself recorded rather
    # than dropping those games and their lineups entirely.
    con.execute(
        """
        INSERT INTO teams (team_id, team_name, country_name, team_gender)
        SELECT * FROM (
            SELECT CAST(cl.club_id AS INTEGER) AS team_id, cl.name AS team_name,
                   comp.country_name, 'male' AS team_gender
            FROM src.clubs cl
            LEFT JOIN src.competitions comp ON comp.competition_id = cl.domestic_competition_id
            UNION ALL
            SELECT CAST(nt.national_team_id AS INTEGER), nt.name, nt.country_name, 'male'
            FROM src.national_teams nt
            UNION ALL
            SELECT DISTINCT home_club_id, home_club_name, NULL, 'male'
            FROM _in_scope_games
            WHERE home_club_id NOT IN (SELECT CAST(club_id AS INTEGER) FROM src.clubs)
              AND home_club_id NOT IN (SELECT CAST(national_team_id AS INTEGER) FROM src.national_teams)
            UNION ALL
            SELECT DISTINCT away_club_id, away_club_name, NULL, 'male'
            FROM _in_scope_games
            WHERE away_club_id NOT IN (SELECT CAST(club_id AS INTEGER) FROM src.clubs)
              AND away_club_id NOT IN (SELECT CAST(national_team_id AS INTEGER) FROM src.national_teams)
        )
        -- a handful of ids appear in both the fallback branches (one game as home, another
        -- as away) -- dedupe to satisfy teams' PRIMARY KEY.
        QUALIFY ROW_NUMBER() OVER (PARTITION BY team_id ORDER BY team_name) = 1
        """
    )
    prefix, suffix = _CREST_URL_TEMPLATE.split("{team_id}")
    con.execute(f"UPDATE teams SET crest_url = '{prefix}' || team_id || '{suffix}'")


def _load_matches(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        INSERT INTO matches
        SELECT CAST(game_id AS INTEGER), competition_id, CAST(season AS INTEGER),
               date, round, home_club_id, away_club_id, home_club_goals, away_club_goals
        FROM _in_scope_games
        """
    )


def _load_players_and_appearances(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TEMP TABLE _in_scope_lineups AS
        SELECT gl.game_id, gl.club_id, gl.player_id, gl.player_name, gl.position,
               TRY_CAST(gl.number AS INTEGER) AS jersey_number
        FROM src.game_lineups gl
        JOIN _in_scope_games g ON CAST(gl.game_id AS VARCHAR) = g.game_id
        -- ~0.6% of in-scope lineup rows reference a player_id with no profile at all in
        -- src.players (youth/reserve squad members never fully scraped) -- dropped rather
        -- than synthesized, since there's no usable name/metadata source for them beyond
        -- this one row, and losing a handful of bit-part appearances doesn't meaningfully
        -- thin out any real squad's connections.
        WHERE gl.player_id IN (SELECT player_id FROM src.players)
        """
    )
    n_total = con.execute("SELECT COUNT(*) FROM src.game_lineups").fetchone()[0]
    n_in_scope = con.execute("SELECT COUNT(*) FROM _in_scope_lineups").fetchone()[0]
    logger.info("game_lineups: %d total, %d in scope (out-of-scope competitions/orphan players excluded: %d)",
                n_total, n_in_scope, n_total - n_in_scope)

    con.execute(
        """
        INSERT INTO players
        SELECT p.player_id, p.name, NULL,
               lower(strip_accents(p.name)),
               p.country_of_citizenship,
               CASE WHEN p.image_url LIKE '%default.jpg%' THEN NULL ELSE p.image_url END
        FROM src.players p
        WHERE p.player_id IN (SELECT DISTINCT player_id FROM _in_scope_lineups)
        """
    )

    con.execute(
        """
        INSERT INTO appearances
        SELECT DISTINCT CAST(game_id AS INTEGER), club_id, player_id, jersey_number, position
        FROM _in_scope_lineups
        """
    )
