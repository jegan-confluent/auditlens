#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <draft-file>" >&2
  exit 1
fi

DRAFT_FILE="$1"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f "$DRAFT_FILE" ]]; then
  echo "Draft file not found: $DRAFT_FILE" >&2
  exit 1
fi

if [[ ! -s "$DRAFT_FILE" ]]; then
  echo "Draft file is empty: $DRAFT_FILE" >&2
  exit 1
fi

touch CHANGELOG.md
printf '\n%s\n' "$(cat "$DRAFT_FILE")" >> CHANGELOG.md
echo "Appended draft to CHANGELOG.md"
