#!/usr/bin/env python3
"""Prints ranked target-player candidates for eyeballing.

Usage: uv run scripts/list_candidates.py [--tier any|multi_club|single_club] [--limit 30]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from footy_quiz import selection
from footy_quiz.db import connect


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", default="any", choices=["any", "multi_club", "single_club"])
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()

    con = connect()
    try:
        candidates = selection.rank_candidates(con, tier=args.tier, limit=args.limit)
    finally:
        con.close()

    print(f"{'player_id':>10}  {'tier':<11} {'score':>6}  {'clubs':>5}  {'rich':>4}  {'matches':>7}  name")
    for c in candidates:
        print(
            f"{c.player_id:>10}  {c.tier:<11} {c.score:>6.2f}  {c.n_clubs:>5}  "
            f"{c.n_rich_clubs:>4}  {c.n_matches:>7}  {c.player_name}"
        )


if __name__ == "__main__":
    main()
