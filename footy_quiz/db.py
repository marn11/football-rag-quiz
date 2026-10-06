"""Shared read-only connection helper for query-time modules (selection, riddle, answers, ...).

Ingestion/graph-building code opens its own read-write connection (see ingest.py, graph.py)
since it needs to create/modify tables. Everything downstream of that only ever reads.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from footy_quiz.ingest import DEFAULT_DB_PATH


def connect(db_path: Path = DEFAULT_DB_PATH, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    """read_only=False is for callers that may need to lazily populate a cache as a side
    effect of an otherwise-read operation (e.g. riddle.get_riddle() resolving media via
    footy_quiz.media's get_or_fetch_* functions)."""
    return duckdb.connect(str(db_path), read_only=read_only)
