#!/usr/bin/env python3
"""Re-runs checkpoint 11's 6-hint simulation through the LLM phrasing layer: for each
raw retrieved chunk, shows the phrased hint Claude Haiku produces, confirms the player's
name never appears, and separately forces a bad API key to confirm the fallback fires.

Usage: uv run scripts/simulate_hints_llm.py [player_id]
Requires ANTHROPIC_API_KEY in .env (copy env.example -> .env and fill it in).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic
import duckdb

from footy_quiz.hints import llm_hint, store
from footy_quiz.hints.session import HintSessionState, get_next_hint
from footy_quiz.ingest import DEFAULT_DB_PATH

DEFAULT_PLAYER = 5503  # Messi


def run_simulation(player_id: int) -> None:
    con = duckdb.connect(str(DEFAULT_DB_PATH))
    try:
        store.ensure_player_chunks(con, player_id)
        player_name, player_nickname = con.execute(
            "SELECT player_name, player_nickname FROM players WHERE player_id = ?", [player_id]
        ).fetchone()

        state = HintSessionState(player_id=player_id)
        print(f"=== 6 simulated hints for {player_nickname or player_name} ===\n")
        for i in range(1, 7):
            result = get_next_hint(con, state)
            if result is None:
                print(f"[hint {i}] -- no eligible chunk remaining")
                continue
            _chunk_index, raw_text = result
            phrased = llm_hint.phrase_hint([raw_text], player_name, player_nickname, i)

            leaked = (player_nickname or "").split()[-1].lower() in phrased.lower()
            print(f"[hint {i}] raw:     {raw_text}")
            print(f"          phrased: {phrased}")
            print(f"          name leaked: {leaked}\n")
    finally:
        con.close()


def check_bad_key_fallback() -> None:
    print("=== Forcing a bad API key to confirm the fallback fires ===\n")
    bad_client = anthropic.Anthropic(api_key="sk-ant-invalid-key-for-testing")
    original_get_client = llm_hint._get_client
    llm_hint._client = bad_client
    try:
        result = llm_hint.phrase_hint(
            ["He once scored an incredible goal as a teenager."],
            "Lionel Andrés Messi Cuccittini",
            "Lionel Messi",
            1,
        )
        print(f"Result with bad key: {result!r}")
        print(f"Fallback fired (starts with 'Fun fact:'): {result.startswith('Fun fact:')}")
    finally:
        llm_hint._client = None  # reset singleton so later real calls aren't affected


if __name__ == "__main__":
    player_id = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PLAYER
    run_simulation(player_id)
    check_bad_key_fallback()
