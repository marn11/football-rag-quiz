#!/usr/bin/env python3
"""Builds the teammate-graph tables on top of an already-ingested DB.

Usage: uv run scripts/build_graph.py  (run scripts/build_db.py first)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb

from footy_quiz import graph
from footy_quiz.ingest import DEFAULT_DB_PATH


def main() -> None:
    if not DEFAULT_DB_PATH.exists():
        raise SystemExit(f"{DEFAULT_DB_PATH} not found -- run scripts/build_db.py first")

    con = duckdb.connect(str(DEFAULT_DB_PATH))
    try:
        print(f"Building teammate graph in {DEFAULT_DB_PATH} ...")
        graph.build(con)
        n_edges = con.execute("SELECT COUNT(*) FROM teammate_edges").fetchone()[0]
        n_contexts = con.execute("SELECT COUNT(*) FROM teammate_edge_contexts").fetchone()[0]
        print(f"teammate_edges: {n_edges} rows, teammate_edge_contexts: {n_contexts} rows")
    finally:
        con.close()


if __name__ == "__main__":
    main()
