#!/usr/bin/env python3
"""Prints every cached chunk for a player with its contains_name/specificity tags, for
eyeballing and threshold tuning.

Usage: uv run scripts/show_tags.py [player_id]
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb

from footy_quiz.hints import store
from footy_quiz.ingest import DEFAULT_DB_PATH

DEFAULT_PLAYER = 5503  # Messi


def main() -> None:
    player_id = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PLAYER
    con = duckdb.connect(str(DEFAULT_DB_PATH))
    try:
        store.ensure_player_chunks(con, player_id)
        rows = con.execute(
            "SELECT chunk_index, contains_name, specificity, text FROM wiki_chunks "
            "WHERE player_id = ? ORDER BY chunk_index",
            [player_id],
        ).fetchall()

        for chunk_index, name_flag, spec, text in rows:
            flag = "NAME" if name_flag else "    "
            print(f"[{chunk_index:>3}] [{flag}] [tier {spec}] {text}")

        print()
        print("contains_name counts:", Counter(r[1] for r in rows))
        print("specificity tier counts:", Counter(r[2] for r in rows))
    finally:
        con.close()


if __name__ == "__main__":
    main()
