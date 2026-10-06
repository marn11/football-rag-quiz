#!/usr/bin/env bash
# Vendors the subset of hudl/open-data (StatsBomb open data) this project needs:
# competitions.json, matches/**, lineups/**. Deliberately skips data/events/** (~12.8 GB)
# since the co-appearance riddle mechanic never needs event-level data.
set -euo pipefail

REPO_URL="https://github.com/hudl/open-data.git"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="$ROOT_DIR/vendor/open-data"

if [ -d "$VENDOR_DIR/.git" ]; then
  echo "Vendor repo already present at $VENDOR_DIR, updating..."
  git -C "$VENDOR_DIR" fetch --depth 1 origin
  git -C "$VENDOR_DIR" reset --hard origin/HEAD
  git -C "$VENDOR_DIR" sparse-checkout reapply
else
  git clone --depth 1 --filter=blob:none --no-checkout "$REPO_URL" "$VENDOR_DIR"
  git -C "$VENDOR_DIR" sparse-checkout init --no-cone
  git -C "$VENDOR_DIR" sparse-checkout set \
    "data/competitions.json" \
    "data/matches" \
    "data/lineups"
  git -C "$VENDOR_DIR" checkout
fi

git -C "$VENDOR_DIR" rev-parse HEAD > "$ROOT_DIR/vendor/SOURCE_COMMIT.txt"
echo "Vendored commit: $(cat "$ROOT_DIR/vendor/SOURCE_COMMIT.txt")"
