#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

args=()
if [ "${1:-}" = "--volumes" ]; then
  args+=("--volumes")
fi

if [ "${#args[@]}" -gt 0 ]; then
  docker compose down "${args[@]}"
  docker compose --profile postgres down "${args[@]}"
  docker compose --profile observability down "${args[@]}"
else
  docker compose down
  docker compose --profile postgres down
  docker compose --profile observability down
fi

echo "AuditLens containers stopped."
if [ "${1:-}" = "--volumes" ]; then
  echo "Docker volumes were removed because --volumes was provided."
else
  echo "Docker volumes were preserved. Pass --volumes to delete them."
fi
