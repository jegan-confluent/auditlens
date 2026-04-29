#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

pass() {
  echo "OK: $*"
}

echo "== AuditLens bounded hot-cache validation =="

docker compose ps
pass "docker compose ps completed"

HEALTH_JSON="$(curl -fsS http://localhost:8003/health)"
METRICS_TEXT="$(curl -fsS http://localhost:8003/metrics)"
LANDING_STATUS="$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8088)"
DASHBOARD_HEALTH="$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8503/_stcore/health)"

[ "$LANDING_STATUS" = "200" ] || fail "landing page returned HTTP $LANDING_STATUS"
[ "$DASHBOARD_HEALTH" = "200" ] || fail "dashboard health returned HTTP $DASHBOARD_HEALTH"
pass "landing and dashboard health endpoints responded"

python3 - "$HEALTH_JSON" <<'PY'
import json
import sys

health = json.loads(sys.argv[1])
storage = health.get("observability", {}).get("persistence_storage", {})
required = [
    "current_db_size",
    "max_db_size",
    "storage_mode",
    "rotation_in_progress",
    "last_rotation_time",
    "rotation_total",
    "data_retention_mode",
    "hot_cache_retention_hours",
    "archive_enabled",
    "data_loss_possible",
    "write_guard_active",
    "storage_degraded",
    "rotation_trigger",
    "last_rotation_failure_time",
]
missing = [field for field in required if field not in storage]
if missing:
    raise SystemExit(f"missing health fields: {missing}")
if storage["current_db_size"] >= storage["max_db_size"]:
    raise SystemExit(
        f"current_db_size must be below max_db_size: {storage['current_db_size']} >= {storage['max_db_size']}"
    )
if storage["data_retention_mode"] != "bounded_hot_cache":
    raise SystemExit(f"unexpected data_retention_mode: {storage['data_retention_mode']}")
print(
    "OK: health fields present; "
    f"db={storage['current_db_size']} max={storage['max_db_size']} "
    f"mode={storage['storage_mode']} rotation_total={storage['rotation_total']}"
)
PY

for metric in \
  audit_forwarder_storage_db_size_bytes \
  audit_forwarder_storage_mode \
  audit_forwarder_rotation_total \
  audit_forwarder_rotation_duration_ms \
  audit_forwarder_storage_write_dropped_total
do
  grep -q "^${metric} " <<< "$METRICS_TEXT" || fail "missing metric $metric"
done
pass "required Prometheus metrics present"

docker compose exec -T auditlens-forwarder python - <<'PY'
import sqlite3

db_path = "/var/lib/auditlens/auditlens.db"
conn = sqlite3.connect(db_path)
integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
if integrity != "ok":
    raise SystemExit(f"SQLite integrity_check failed: {integrity}")
dupes = conn.execute(
    "SELECT COUNT(*) FROM (SELECT event_id FROM enriched_events GROUP BY event_id HAVING COUNT(*) > 1)"
).fetchone()[0]
if dupes:
    raise SystemExit(f"duplicate enriched primary keys: {dupes}")
print("OK: SQLite integrity_check=ok and duplicate enriched primary keys=0")
PY

echo "== Validation complete =="
