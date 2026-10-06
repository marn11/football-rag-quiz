#!/usr/bin/env python3
"""Prints generated riddles for a few hand-picked players for eyeballing: Di María (known
recurring co-star with Ramos: Real Madrid, then PSG) plus a couple of selection.py's own
top candidates at different difficulties.

Usage: uv run scripts/show_riddle.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from footy_quiz import riddle, selection
from footy_quiz.db import connect

DI_MARIA = 2995


def show(player_id: int) -> None:
    r = riddle.get_riddle(player_id)
    print(f"player_id={r.target_player_id}  difficulty={r.difficulty}")
    for i, c in enumerate(r.clues, 1):
        print(f"  [{i}] {c.text}")
        print(
            f"      season_start_year={c.season_start_year}  "
            f"teammate_photo={'yes' if c.teammate_photo_url else 'NO'}  "
            f"crest={'yes' if c.team_crest_url else 'NO'}"
        )
    print()


def main() -> None:
    print("=== Di María (expect Ramos recurring across Real Madrid + PSG) ===")
    show(DI_MARIA)

    con = connect()
    try:
        easy = selection.rank_candidates(con, difficulty="easy", limit=3)
        hard = selection.rank_candidates(con, difficulty="hard", limit=3)
    finally:
        con.close()

    print("=== A couple of 'easy' candidates ===")
    for c in easy:
        print(f"-- {c.player_name} --")
        show(c.player_id)

    print("=== A couple of 'hard' candidates ===")
    for c in hard:
        print(f"-- {c.player_name} --")
        show(c.player_id)


if __name__ == "__main__":
    main()
