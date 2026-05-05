#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "FAIL: docker is required" >&2
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

mkdir -p data

export DATABASE_URL="sqlite:////var/lib/auditlens/auditlens_api.db"
export NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-http://127.0.0.1:8080}"
export FORWARDER_HEALTH_URL="${FORWARDER_HEALTH_URL:-http://127.0.0.1:9/health}"

echo "Starting AuditLens SQLite demo mode..."
docker compose up --build -d api frontend

echo "Waiting for API..."
for _ in {1..60}; do
  if curl -fsS "http://127.0.0.1:${BACKEND_PORT:-8080}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if [ "${1:-}" != "--no-seed" ]; then
  echo "Seeding sample audit events..."
  docker compose exec -T --user 1000:1000 api python -m backend.scripts.seed_data
fi

echo
echo "AuditLens SQLite demo is running"
echo "API: http://127.0.0.1:${BACKEND_PORT:-8080}"
echo "UI:  http://127.0.0.1:${FRONTEND_PORT:-3000}"
echo
echo "Health check:"
echo "  scripts/health_check.sh"
