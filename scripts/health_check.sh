#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

BACKEND_PORT="${BACKEND_PORT:-8080}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
failed=0

check_http() {
  local name="$1"
  local url="$2"
  local code
  code="$(curl -s -o /tmp/auditlens_health_check.out -w '%{http_code}' "$url" 2>/dev/null || true)"
  if [ "$code" = "200" ]; then
    echo "PASS: $name ($url)"
  else
    echo "FAIL: $name ($url) returned ${code:-000}"
    failed=1
  fi
}

check_optional_http() {
  local name="$1"
  local url="$2"
  local code
  code="$(curl -s -o /tmp/auditlens_health_check.out -w '%{http_code}' "$url" 2>/dev/null || true)"
  if [ "$code" = "200" ]; then
    echo "PASS: $name ($url)"
  else
    echo "WARN: $name ($url) returned ${code:-000}"
  fi
}

echo "Docker services:"
if docker compose ps; then
  echo "PASS: docker compose ps"
else
  echo "FAIL: docker compose ps"
  failed=1
fi

check_http "API /ready" "http://127.0.0.1:${BACKEND_PORT}/ready"
check_optional_http "Pipeline /pipeline/ready" "http://127.0.0.1:${BACKEND_PORT}/pipeline/ready"
check_http "API /system/status" "http://127.0.0.1:${BACKEND_PORT}/system/status"
check_http "API /events?limit=1" "http://127.0.0.1:${BACKEND_PORT}/events?limit=1"
check_http "UI /events" "http://127.0.0.1:${FRONTEND_PORT}/events"

if [ "$failed" -eq 0 ]; then
  echo "PASS: AuditLens health checks passed"
else
  echo "FAIL: one or more AuditLens health checks failed"
fi

exit "$failed"
