#!/usr/bin/env python3
"""Rebuilds data/footy_quiz.duckdb from the vendored StatsBomb JSON.

Usage: uv run scripts/build_db.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from footy_quiz import ingest


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"Building {ingest.DEFAULT_DB_PATH} from {ingest.DEFAULT_VENDOR_DIR} ...")
    ingest.build()
    print("Done.")


if __name__ == "__main__":
    main()
