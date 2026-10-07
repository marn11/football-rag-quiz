#!/usr/bin/env python3
"""Simulates 6 sequential hint requests for one player (no LLM phrasing yet -- that's
checkpoint 12), printing each hint's angle, specificity ceiling, and raw retrieved chunk.
Confirms no repeated chunk_index and that the specificity ceiling steps up over time.

Usage: uv run scripts/simulate_hints.py [player_id]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb

from footy_quiz.hints import store
from footy_quiz.hints.session import HintSessionState, get_next_hint
from footy_quiz.ingest import DEFAULT_DB_PATH

DEFAULT_PLAYER = 5503  # Messi


def main() -> None:
    player_id = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PLAYER
    con = duckdb.connect(str(DEFAULT_DB_PATH))
    try:
        store.ensure_player_chunks(con, player_id)
        state = HintSessionState(player_id=player_id)

        for i in range(1, 7):
            ceiling = state.specificity_ceiling()
            result = get_next_hint(con, state)
            if result is None:
                print(f"[hint {i}] ceiling={ceiling}  -- no eligible chunk remaining")
                continue
            chunk_index, text = result
            print(f"[hint {i}] ceiling={ceiling}  chunk={chunk_index}  {text}")

        print()
        print("served chunk indices:", sorted(state.served_chunk_indices))
        print(
            "no repeats:",
            len(state.served_chunk_indices) == state.hints_given,
        )
    finally:
        con.close()


if __name__ == "__main__":
    main()
