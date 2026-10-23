#!/usr/bin/env python3
"""RAG core proof of concept: fetch + chunk + embed one hardcoded player's Wikipedia
prose, then retrieve top-k chunks for a few hardcoded test queries via cosine distance.

Usage: uv run scripts/poc_retrieve.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb

from footy_quiz.hints import store
from footy_quiz.ingest import DEFAULT_DB_PATH

MESSI = 28003

TEST_QUERIES = [
    "an interesting fact about this player's youth or early career",
    "a notable achievement, award, or record held by this player",
    "something about this player's personality, style of play, or reputation",
    "a memorable match moment or transfer in this player's career",
]


def main() -> None:
    con = duckdb.connect(str(DEFAULT_DB_PATH))
    try:
        n = store.ensure_player_chunks(con, MESSI)
        print(f"{n} chunks available for player {MESSI}\n")

        for query in TEST_QUERIES:
            print(f"Query: {query!r}")
            for _chunk_index, text, distance in store.retrieve(con, MESSI, query, k=3):
                print(f"  [{distance:.3f}] {text}")
            print()
    finally:
        con.close()


if __name__ == "__main__":
    main()
