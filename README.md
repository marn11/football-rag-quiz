# Footy Quiz — Guess the Player

A football quiz game. The current mode, **Guess the Player**, identifies a mystery
footballer only through a chain of deterministic clues — "played alongside teammate A at
Club X" — built from [StatsBomb's open data](https://github.com/hudl/open-data). On top
of that, players can request hints: a live RAG pipeline retrieves grounded, non-spoiler
sentences from the mystery player's Wikipedia page and has an LLM (Claude Haiku 4.5)
phrase them into a natural trivia hint.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (manages the Python version and virtualenv)
- An [Anthropic API key](https://console.anthropic.com/) (for hint phrasing)

## Setup

```bash
# 1. Create the virtualenv (pinned to Python 3.12) and install dependencies
uv venv --python 3.12
uv sync

# 2. Vendor the StatsBomb data (~100 MB; sparse-checks out only what's needed,
#    skips the 12.8 GB events/ directory entirely)
./scripts/vendor_data.sh

# 3. Build the database: ingests the vendored JSON, then builds the
#    co-appearance ("teammate") graph on top of it
uv run scripts/build_db.py
uv run scripts/build_graph.py

# 4. Add your Anthropic API key
cp env.example .env
# then edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

## Running

```bash
uv run uvicorn footy_quiz.api.main:app --reload
```

Open **http://127.0.0.1:8000** in a browser.

The first hint request for any given player fetches and embeds their Wikipedia page
(a network call plus a one-time local model load), so the very first hint in a fresh run
is slower than the rest — later hints for the same player, and hints for other players
you've already seen, are fast.

## Running the tests

```bash
uv run pytest
```

Most tests need the database built (step 3 above); they skip themselves if it's missing.
A handful make real network calls (Wikipedia resolution) on first run per player and are
cached afterward.

## Project layout

```
footy_quiz/           # riddle engine + RAG hint pipeline (the actual game logic)
  hints/              # Wikipedia fetch/chunk/embed/retrieve, session state, LLM phrasing
  api/                # FastAPI service
vendor/open-data/     # vendored StatsBomb data (gitignored, re-fetched via vendor_data.sh)
data/                 # the built DuckDB file (gitignored, rebuildable from scripts/)
web/                  # static frontend (no build step)
scripts/              # one-off build/debug/verification scripts
tests/
```
