#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "FAIL: docker is required" >&2
  exit 1
fi

if [ ! -f .env ]; then
  echo "FAIL: .env is required. Run: cp .env.example .env, then fill Kafka credentials." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
. ./.env
set +a

warn_legacy_mismatch() {
  local canonical_name="$1"
  local legacy_name="$2"
  local canonical_value="${!canonical_name:-}"
  local legacy_value="${!legacy_name:-}"
  if [ -n "$canonical_value" ] && [ -n "$legacy_value" ] && [ "$canonical_value" != "$legacy_value" ]; then
    echo "WARN: $legacy_name is a legacy alias and differs from $canonical_name; using $canonical_name." >&2
  fi
}

legacy_fallback() {
  local canonical_name="$1"
  local legacy_name="$2"
  local canonical_value="${!canonical_name:-}"
  local legacy_value="${!legacy_name:-}"
  if [ -z "$canonical_value" ] && [ -n "$legacy_value" ]; then
    printf -v "$canonical_name" '%s' "$legacy_value"
    export "$canonical_name"
    echo "WARN: $legacy_name is deprecated; set $canonical_name in .env instead." >&2
  fi
}

warn_legacy_mismatch AUDIT_BOOTSTRAP KAFKA_BOOTSTRAP_SERVERS
warn_legacy_mismatch AUDIT_API_KEY KAFKA_API_KEY
warn_legacy_mismatch AUDIT_API_SECRET KAFKA_API_SECRET
warn_legacy_mismatch AUDIT_TOPIC KAFKA_AUDIT_TOPIC

legacy_fallback AUDIT_BOOTSTRAP KAFKA_BOOTSTRAP_SERVERS
legacy_fallback AUDIT_API_KEY KAFKA_API_KEY
legacy_fallback AUDIT_API_SECRET KAFKA_API_SECRET
legacy_fallback AUDIT_TOPIC KAFKA_AUDIT_TOPIC

export AUDIT_BOOTSTRAP="${AUDIT_BOOTSTRAP:-}"
export AUDIT_API_KEY="${AUDIT_API_KEY:-}"
export AUDIT_API_SECRET="${AUDIT_API_SECRET:-}"
export AUDIT_TOPIC="${AUDIT_TOPIC:-confluent-audit-log-events}"
export DEST_BOOTSTRAP="${DEST_BOOTSTRAP:-}"
export DEST_API_KEY="${DEST_API_KEY:-}"
export DEST_API_SECRET="${DEST_API_SECRET:-}"

missing=()
for name in AUDIT_BOOTSTRAP AUDIT_API_KEY AUDIT_API_SECRET AUDIT_TOPIC; do
  if [ -z "${!name:-}" ]; then
    missing+=("$name")
  fi
done

if [ "${#missing[@]}" -gt 0 ]; then
  echo "FAIL: missing Kafka configuration: ${missing[*]}" >&2
  echo "Fill AUDIT_* values in .env. KAFKA_* is supported only as a deprecated legacy alias." >&2
  exit 1
fi

missing_dest=()
for name in DEST_BOOTSTRAP DEST_API_KEY DEST_API_SECRET; do
  if [ -z "${!name:-}" ]; then
    missing_dest+=("$name")
  fi
done

if [ "${#missing_dest[@]}" -gt 0 ]; then
  echo "WARN: missing destination test cluster configuration: ${missing_dest[*]}" >&2
  echo "WARN: real create/delete topic testing needs DEST_* values." >&2
fi

export DATABASE_URL="${DATABASE_URL_POSTGRES:-postgresql://auditlens:auditlens@postgres:5432/auditlens}"
export FORWARDER_DATABASE_URL="${FORWARDER_DATABASE_URL_POSTGRES:-postgresql://auditlens:auditlens@postgres:5432/auditlens}"
export POSTGRES_DB="${POSTGRES_DB:-auditlens}"
export POSTGRES_USER="${POSTGRES_USER:-auditlens}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-auditlens}"
export ENABLE_DB_WRITER="${ENABLE_DB_WRITER:-true}"
export NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-http://127.0.0.1:8080}"

echo "Starting AuditLens Postgres product mode..."
docker compose --profile postgres up --build -d postgres auditlens-forwarder api frontend

echo "Waiting for API readiness..."
api_ready=0
for _ in {1..90}; do
  if curl -fsS "http://127.0.0.1:${BACKEND_PORT:-8080}/ready" >/dev/null 2>&1; then
    api_ready=1
    break
  fi
  sleep 2
done

if [ "$api_ready" -ne 1 ]; then
  echo "FAIL: API/DB readiness did not become ready at http://127.0.0.1:${BACKEND_PORT:-8080}/ready" >&2
  exit 1
fi

echo "API ready"
if curl -fsS "http://127.0.0.1:${BACKEND_PORT:-8080}/pipeline/ready" >/dev/null 2>&1; then
  echo "Pipeline ready"
else
  echo "WARN: Product usable but ingestion is not active or is degraded. Check /pipeline/ready and forwarder logs." >&2
fi

scripts/health_check.sh

echo
echo "AuditLens Postgres product mode is running"
echo "API:       http://127.0.0.1:${BACKEND_PORT:-8080}"
echo "UI:        http://127.0.0.1:${FRONTEND_PORT:-3000}"
echo "Forwarder: http://127.0.0.1:${METRICS_PORT:-8003}/health"
