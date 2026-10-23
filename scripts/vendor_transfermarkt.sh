#!/usr/bin/env bash
# Vendors the transfermarkt-datasets project (CC0, github.com/dcaribou/transfermarkt-datasets):
# squads/lineups for ~20 top-flight domestic leagues plus World Cup/Euro/Copa América/AFCON/
# Champions League/Europa League, 2005-2025 seasons. Published as a single DuckDB file --
# no JSON/CSV parsing needed, footy_quiz.ingest reads straight out of it.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="$ROOT_DIR/vendor/transfermarkt"
URL="https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/transfermarkt-datasets.duckdb"

mkdir -p "$VENDOR_DIR"
curl -L -o "$VENDOR_DIR/transfermarkt-datasets.duckdb" "$URL"
echo "Vendored $(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$VENDOR_DIR/SOURCE_FETCHED_AT.txt"
echo "Vendored transfermarkt-datasets.duckdb -> $VENDOR_DIR"
