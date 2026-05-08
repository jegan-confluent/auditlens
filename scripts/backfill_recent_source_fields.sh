#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -z "${DATABASE_URL:-}" ]; then
  echo "FAIL: DATABASE_URL is required. Set it in your shell before running this backfill." >&2
  exit 1
fi

# Prefer a virtualenv interpreter when one is available; fall back to python3
# only in environments without a venv (containers with deps installed globally).
PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
  if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
    PYTHON_BIN="$VIRTUAL_ENV/bin/python"
  elif [ -x "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi
BACKFILL_HOURS="${BACKFILL_HOURS:-4}"
BACKFILL_LIMIT="${BACKFILL_LIMIT:-10000}"
BACKFILL_DRY_RUN="${BACKFILL_DRY_RUN:-false}"
BACKFILL_SLEEP_MS="${BACKFILL_SLEEP_MS:-0}"
LOG_DIR="${LOG_DIR:-logs}"
LOG_FILE="$LOG_DIR/backfill_recent_source_fields.log"
BACKFILL_DRY_RUN_NORMALIZED="$(printf '%s' "$BACKFILL_DRY_RUN" | tr '[:upper:]' '[:lower:]')"

mkdir -p "$LOG_DIR"

echo "Current database status:"
./scripts/db_status.sh

args=(--source-fields --hours "$BACKFILL_HOURS" --limit "$BACKFILL_LIMIT" --sleep-ms "$BACKFILL_SLEEP_MS")
case "$BACKFILL_DRY_RUN_NORMALIZED" in
  1|true|yes|on)
    args+=(--dry-run)
    ;;
esac

set +e
output="$("$PYTHON_BIN" scripts/backfill_event_fields.py "${args[@]}" 2>&1)"
status=$?
set -e

printf '%s\n' "$output"

if [ "$status" -ne 0 ]; then
  exit "$status"
fi

summary_json="$(printf '%s\n' "$output" | tail -n 1)"
summary="$("$PYTHON_BIN" - "$summary_json" <<'PY'
import json
import sys

data = json.loads(sys.argv[1])
print(f"scanned={data['scanned']} updated={data['updated']} invalid_json={data['invalid_json']}")
PY
)"

timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '%s dry_run=%s hours=%s limit=%s %s\n' "$timestamp" "$BACKFILL_DRY_RUN_NORMALIZED" "$BACKFILL_HOURS" "$BACKFILL_LIMIT" "$summary" >> "$LOG_FILE"
