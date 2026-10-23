#!/usr/bin/env python3
"""One-time batch job: computes trailing-12-month en.wikipedia pageviews for every player
who structurally qualifies for "easy" or "normal" difficulty (config.DIFFICULTY_PRESETS),
caching the result in player_wiki.popularity_views so footy_quiz.selection can band by
real-world fame without a live network call per candidate -- see config.py's
min_popularity_views docs and footy_quiz/media.py's get_or_fetch_player_popularity.

Idempotent: migrates the popularity_views column in if it isn't there yet, and skips any
player it already has a cached value for, so it's safe to re-run (e.g. after the vendored
dataset changes and pulls in new candidates).

Stop any server/script holding the DB connection before running this (DuckDB only allows
one read-write connection to a file at a time).

Usage: uv run scripts/build_popularity.py
"""

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb

import config
from footy_quiz import media
from footy_quiz.ingest import DEFAULT_DB_PATH
from footy_quiz.selection import _build_base_tables, _club_counts

# The real cost here is network latency (2-3 Wikipedia HTTP round trips per candidate),
# not CPU or the DB itself -- each worker thread releases the GIL during I/O wait, and
# gets its own cursor (DuckDB's documented pattern for concurrent use of one connection:
# cursors serialize actual query execution but are safe to drive from multiple threads).
# At tens of thousands of candidates, sequential fetching would take hours; this cuts
# wall-clock time by roughly the worker count while staying well within "a reasonable
# number of concurrent requests" for a single client against Wikipedia's API.
WORKERS = 5


def _structural_candidates(con: duckdb.DuckDBPyConnection) -> list[int]:
    """Player ids satisfying "easy" or "normal"'s STRUCTURAL thresholds only (ignoring
    popularity, which is exactly what this script is about to go compute), ordered by
    n_matches descending. A candidate needing the full search-fallback chain (several
    sequential Wikipedia requests) costs far more than a lucky direct hit, so with tens
    of thousands of candidates this can run long -- processing highest-n_matches first
    (strongly correlated with selection.rank_candidates' own score formula, so also the
    players most likely to actually be served) means an interrupted run still leaves the
    highest-value candidates resolved."""
    _build_base_tables(con)
    stats = dict(con.execute("SELECT player_id, n_matches FROM _player_stats").fetchall())

    candidates: set[int] = set()
    for name in ("easy", "normal"):
        preset = config.DIFFICULTY_PRESETS[name]
        rich_counts, qualifying_counts = _club_counts(con, preset)
        for player_id, n_matches in stats.items():
            if (
                n_matches >= preset["min_matches"]
                and rich_counts.get(player_id, 0) >= preset["min_rich_clubs"]
                and qualifying_counts.get(player_id, 0) >= preset["min_qualifying_clubs"]
            ):
                candidates.add(player_id)
    return sorted(candidates, key=lambda pid: stats[pid], reverse=True)


def main() -> None:
    con = duckdb.connect(str(DEFAULT_DB_PATH))
    try:
        con.execute("ALTER TABLE player_wiki ADD COLUMN IF NOT EXISTS popularity_views BIGINT")

        candidates = _structural_candidates(con)  # already ordered, highest-value first
        already_done = {
            pid
            for (pid,) in con.execute(
                "SELECT player_id FROM player_wiki WHERE popularity_views IS NOT NULL"
            ).fetchall()
        }
        todo = [pid for pid in candidates if pid not in already_done]
        print(
            f"{len(candidates)} structural easy/normal candidates, "
            f"{len(already_done)} already cached, {len(todo)} to fetch"
        )

        start = time.monotonic()
        progress_lock = threading.Lock()
        done = 0

        def _fetch_one(player_id: int) -> None:
            nonlocal done
            # con.cursor() per task -- never share one cursor across threads.
            media.get_or_fetch_player_popularity(con.cursor(), player_id, sleep_s=0.1)
            with progress_lock:
                done += 1
                if done % 100 == 0 or done == len(todo):
                    print(f"[{done}/{len(todo)}] ({time.monotonic() - start:.0f}s elapsed)")

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(_fetch_one, player_id) for player_id in todo]
            for future in as_completed(futures):
                future.result()  # re-raises any worker exception instead of swallowing it
        print("Done.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
