#!/usr/bin/env python3
"""Smoke-tests Wikipedia resolution against real, deliberately tricky players/teams from
our own data: common names needing nickname/search fallback, a club name that collides
with a city, and a national team name that collides with the country.

Usage: uv run scripts/test_resolution.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb

from footy_quiz import media
from footy_quiz.ingest import DEFAULT_DB_PATH

# (player_id, label) -- picked from our own players table for known-tricky cases.
PLAYER_CASES = [
    (5503, "Messi -- direct hit, unambiguous full name"),
    (3063, "Danilo Luiz da Silva -- common nickname 'Danilo', needs search fallback"),
    (3054, "Fernando Luiz Rosa -- nickname 'Fernandinho', needs search fallback"),
    (5558, "Rafael Márquez Álvarez -- nickname resolves directly"),
]

# (team_id, label) -- a plain club, a club name colliding with a city, a national team
# colliding with the country name.
TEAM_CASES = [
    (220, "Real Madrid -- direct hit"),
]


def _find_team_id(con: duckdb.DuckDBPyConnection, name_like: str) -> int | None:
    row = con.execute(
        "SELECT team_id FROM teams WHERE team_name ILIKE ? LIMIT 1", [f"%{name_like}%"]
    ).fetchone()
    return row[0] if row else None


def main() -> None:
    con = duckdb.connect(str(DEFAULT_DB_PATH))

    barcelona_id = _find_team_id(con, "Barcelona")
    portugal_id = _find_team_id(con, "Portugal")
    team_cases = TEAM_CASES + [
        (barcelona_id, "Barcelona -- collides with the city, needs 'FC Barcelona'"),
        (portugal_id, "Portugal -- collides with the country, needs national-team form"),
    ]

    print("=== Players ===")
    for player_id, label in PLAYER_CASES:
        photo_url = media.get_or_fetch_player_photo(con, player_id)
        method, title = con.execute(
            "SELECT resolution_method, wiki_title FROM player_wiki WHERE player_id = ?",
            [player_id],
        ).fetchone()
        print(f"{label}\n  -> method={method} title={title!r}\n  -> photo={photo_url}\n")

    print("=== Teams ===")
    for team_id, label in team_cases:
        if team_id is None:
            print(f"{label}\n  -> SKIPPED (team not found in this dataset)\n")
            continue
        crest_url = media.get_or_fetch_team_crest(con, team_id)
        method, title = con.execute(
            "SELECT resolution_method, wiki_title FROM team_wiki WHERE team_id = ?", [team_id]
        ).fetchone()
        print(f"{label}\n  -> method={method} title={title!r}\n  -> crest={crest_url}\n")

    con.close()


if __name__ == "__main__":
    main()
