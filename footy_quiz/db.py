"""Shared connection helper for query-time modules (selection, riddle, answers, ...).

One lazily-opened, process-wide read-write connection, reused for the process's whole
lifetime -- callers get `.cursor()` handles on it rather than each opening their own
`duckdb.connect()` (which reopens the file, re-validates it, and rebuilds the catalog
every time -- real, avoidable overhead if called once per request, e.g. per autocomplete
keystroke).

Why read-write for everyone, even read-only callers: DuckDB refuses to open a read-only
connection to a file that already has a read-write connection open (confirmed directly --
"Can't open a connection to same database file with a different configuration than
existing connections"), so a single process can't keep both kinds open at once. Since
riddle.get_riddle() needs write access in-process (to lazily cache media lookups), the
only connection that can coexist with it is itself -- so everything shares one read-write
connection and relies on query-level discipline (SELECT-only code just never writes),
not connection-level enforcement, to stay "read-only" in practice.

cursor() does NOT add concurrency -- per DuckDB's own docs, cursors on one connection
"cannot run queries at the same time" (queries serialize). What it buys instead: each
caller gets its own execute()/fetchall() state, so overlapping calls can't clobber each
other's results. At this project's scale (sub-10ms queries, a casual web game's worth of
traffic) serialized queries are a non-issue; a real connection *pool* would be the next
step if that ever stopped being true, not cursor() -- there's no evidence we need one yet.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from footy_quiz.ingest import DEFAULT_DB_PATH

_singleton: duckdb.DuckDBPyConnection | None = None
_singleton_path: Path | None = None


def connect(db_path: Path = DEFAULT_DB_PATH, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    """Returns a cursor on the shared process-wide connection (opening it on first use).

    `read_only` is intent documentation for the caller, not an enforced separate
    connection mode -- see module docstring for why DuckDB makes that impossible here.
    """
    global _singleton, _singleton_path
    if _singleton is None:
        _singleton = duckdb.connect(str(db_path), read_only=False)
        _singleton_path = db_path
    elif db_path != _singleton_path:
        raise RuntimeError(
            f"footy_quiz.db singleton already opened against {_singleton_path}, "
            f"can't also serve {db_path} in the same process"
        )
    return _singleton.cursor()
