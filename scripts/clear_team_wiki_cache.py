#!/usr/bin/env python3
"""Clears the team_wiki cache so every club crest gets freshly re-resolved next time
it's needed (lazy, on-demand -- nothing is bulk-refetched by running this).

Use this after a fix to footy_quiz.media's team resolution logic (keyword list,
country-mismatch check, etc.) -- a code fix alone doesn't correct already-cached rows,
since get_or_fetch_team_crest returns from cache before ever re-resolving.

Stop any server/script holding the DB connection before running this (DuckDB only
allows one read-write connection to a file at a time).

Usage: uv run scripts/clear_team_wiki_cache.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb

from footy_quiz.ingest import DEFAULT_DB_PATH


def main() -> None:
    con = duckdb.connect(str(DEFAULT_DB_PATH))
    try:
        (n,) = con.execute("SELECT COUNT(*) FROM team_wiki").fetchone()
        con.execute("DELETE FROM team_wiki")
        print(f"Cleared {n} cached team_wiki row(s). Crests will re-resolve on next use.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
