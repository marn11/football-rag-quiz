"""Shared read-only connection helper for query-time modules (selection, riddle, answers, ...).

Ingestion/graph-building code opens its own read-write connection (see ingest.py, graph.py)
since it needs to create/modify tables. Everything downstream of that only ever reads.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from footy_quiz.ingest import DEFAULT_DB_PATH


def connect(db_path: Path = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=True)
