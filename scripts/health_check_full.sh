#!/bin/bash
# AuditLens — Full Health Check Report
# Run on EC2: bash ~/AuditLens/scripts/health_check.sh
# Produces a pass/fail report for all services, logs, and data pipeline

set -uo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'
BOLD='\033[1m'

PASS=0
FAIL=0
WARN=0

pass() { echo -e "  ${GREEN}✅ PASS${NC} — $1"; PASS=$((PASS+1)); }
fail() { echo -e "  ${RED}❌ FAIL${NC} — $1"; FAIL=$((FAIL+1)); }
warn() { echo -e "  ${YELLOW}⚠️  WARN${NC} — $1"; WARN=$((WARN+1)); }
header() { echo -e "\n${BOLD}${BLUE}$1${NC}"; echo "$(printf '─%.0s' {1..60})"; }

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║       AuditLens Health Check — $(date '+%Y-%m-%d %H:%M UTC')        ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"

# ─── SECTION 1: CONTAINER STATUS ────────────────────────────────────────────
header "1. CONTAINER STATUS (8 expected)"

EXPECTED_CONTAINERS=(
  "auditlens-forwarder"
  "auditlens-api"
  "auditlens-frontend"
  "auditlens-postgres"
  "auditlens-caddy"
  "audit-grafana"
  "audit-prometheus"
  "auditlens-postgres-exporter"
)

for container in "${EXPECTED_CONTAINERS[@]}"; do
  STATUS=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null || echo "missing")
  HEALTH=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$container" 2>/dev/null || echo "missing")
  UPTIME=$(docker inspect --format='{{.State.StartedAt}}' "$container" 2>/dev/null || echo "unknown")

  if [ "$STATUS" = "running" ]; then
    if [ "$HEALTH" = "unhealthy" ]; then
      fail "$container — running but UNHEALTHY"
    elif [ "$HEALTH" = "starting" ]; then
      warn "$container — running, health check still starting"
    else
      pass "$container — $STATUS ($HEALTH)"
    fi
  elif [ "$STATUS" = "missing" ]; then
    fail "$container — NOT FOUND"
  else
    fail "$container — $STATUS"
  fi
done

# Check for any unexpected exited containers
EXITED=$(docker ps -a --filter "status=exited" --format "{{.Names}}" | grep -i auditlens 2>/dev/null || true)
if [ -n "$EXITED" ]; then
  fail "Exited containers found: $EXITED"
else
  pass "No exited/crashed containers"
fi

# ─── SECTION 2: API HEALTH ──────────────────────────────────────────────────
header "2. API HEALTH ENDPOINTS"

# API health
API_HEALTH=$(curl -s --max-time 5 http://localhost/api/health 2>/dev/null || echo "")
if echo "$API_HEALTH" | grep -q '"status":"ok"'; then
  DB_MODE=$(echo "$API_HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('database_mode','unknown'))" 2>/dev/null || echo "unknown")
  pass "API /health — OK (db_mode=$DB_MODE)"
else
  fail "API /health — no response or error"
fi

# Forwarder health
FWD_HEALTH=$(curl -s --max-time 5 http://localhost:8003/health 2>/dev/null || echo "")
if [ -n "$FWD_HEALTH" ]; then
  LAG=$(echo "$FWD_HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('consumer_lag',0))" 2>/dev/null || echo "unknown")
  RATE=$(echo "$FWD_HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(round(d.get('processing_rate',0),1))" 2>/dev/null || echo "unknown")
  HEALTHY=$(echo "$FWD_HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('healthy',False))" 2>/dev/null || echo "False")

  if [ "$HEALTHY" = "True" ]; then
    pass "Forwarder /health — healthy (lag=$LAG, rate=$RATE msg/s)"
  else
    # Check if lag is exploding
    if [ "$LAG" -gt 100000 ] 2>/dev/null; then
      fail "Forwarder — lag=$LAG (critical threshold exceeded)"
    else
      warn "Forwarder — degraded (lag=$LAG, rate=$RATE msg/s)"
    fi
  fi
else
  fail "Forwarder /health — no response"
fi

# Caddy / frontend
FRONTEND=$(curl -s -L --max-time 5 -o /dev/null -w "%{http_code}" http://localhost/ 2>/dev/null || echo "000")
if [ "$FRONTEND" = "200" ]; then
  pass "Caddy/Frontend — HTTP $FRONTEND"
else
  fail "Caddy/Frontend — HTTP $FRONTEND (expected 200)"
fi

# Grafana
GRAFANA=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" http://localhost:3001/api/health 2>/dev/null || echo "000")
if [ "$GRAFANA" = "200" ]; then
  pass "Grafana — HTTP $GRAFANA"
else
  warn "Grafana — HTTP $GRAFANA"
fi

# Prometheus
PROM=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" http://localhost:9090/-/healthy 2>/dev/null || echo "000")
if [ "$PROM" = "200" ]; then
  pass "Prometheus — HTTP $PROM"
else
  warn "Prometheus — HTTP $PROM"
fi

# ─── SECTION 3: DATABASE ────────────────────────────────────────────────────
header "3. DATABASE"

# Postgres connectivity
PG_CHECK=$(docker exec auditlens-postgres psql -U auditlens -d auditlens \
  -c "SELECT count(*) FROM audit_events;" -t 2>/dev/null | tr -d ' ' || echo "ERROR")
if [[ "$PG_CHECK" =~ ^[0-9]+$ ]]; then
  pass "Postgres — connected, audit_events=$PG_CHECK rows"
else
  fail "Postgres — connection failed: $PG_CHECK"
fi

# Noise table
NOISE_CHECK=$(docker exec auditlens-postgres psql -U auditlens -d auditlens \
  -c "SELECT count(*) FROM audit_events_noise;" -t 2>/dev/null | tr -d ' ' || echo "ERROR")
if [[ "$NOISE_CHECK" =~ ^[0-9]+$ ]]; then
  pass "Postgres — audit_events_noise=$NOISE_CHECK rows"
else
  fail "Postgres — noise table check failed"
fi

# DB size
DB_SIZE=$(docker exec auditlens-postgres psql -U auditlens -d auditlens \
  -c "SELECT pg_size_pretty(pg_database_size('auditlens'));" -t 2>/dev/null | tr -d ' ' || echo "ERROR")
pass "Postgres — database size: $DB_SIZE"

# Migration version
MIGRATION=$(docker exec auditlens-postgres psql -U auditlens -d auditlens \
  -c "SELECT version_num FROM alembic_version;" -t 2>/dev/null | tr -d ' ' || echo "ERROR")
if [ -n "$MIGRATION" ] && [ "$MIGRATION" != "ERROR" ]; then
  pass "Migrations — current: $MIGRATION"
else
  fail "Migrations — could not read alembic_version"
fi

# Dead tuples check
DEAD=$(docker exec auditlens-postgres psql -U auditlens -d auditlens \
  -c "SELECT sum(n_dead_tup) FROM pg_stat_user_tables;" -t 2>/dev/null | tr -d ' ' || echo "0")
if [ "$DEAD" -gt 10000 ] 2>/dev/null; then
  warn "Postgres — $DEAD dead tuples (consider VACUUM ANALYZE)"
else
  pass "Postgres — dead tuples: $DEAD (healthy)"
fi

# Disk usage
DISK=$(df -h / | awk 'NR==2 {print $5}' | tr -d '%')
if [ "$DISK" -gt 85 ] 2>/dev/null; then
  fail "Disk — ${DISK}% used (critical, >85%)"
elif [ "$DISK" -gt 70 ] 2>/dev/null; then
  warn "Disk — ${DISK}% used (warning, >70%)"
else
  pass "Disk — ${DISK}% used"
fi

# ─── SECTION 4: ERROR LOG SCAN ──────────────────────────────────────────────
header "4. ERROR LOG SCAN (last 100 lines per container)"

scan_logs() {
  local container=$1
  local errors
  errors=$(docker logs "$container" --tail=100 2>&1 | \
    grep -iE "ERROR|CRITICAL|FATAL|Exception|Traceback|OOM|killed|crash" | \
    grep -viE "DeprecationWarning|UserWarning|INFO.*error|debug.*error|no error" | \
    wc -l | tr -d ' ')

  if [ "$errors" -gt 10 ]; then
    fail "$container — $errors error lines in last 100 log lines"
    # Show the most recent errors
    docker logs "$container" --tail=100 2>&1 | \
      grep -iE "ERROR|CRITICAL|FATAL" | tail -3 | \
      sed 's/^/         /'
  elif [ "$errors" -gt 0 ]; then
    warn "$container — $errors error lines in last 100 log lines"
  else
    pass "$container — no errors in last 100 log lines"
  fi
}

scan_logs "auditlens-api"
scan_logs "auditlens-forwarder"
scan_logs "auditlens-postgres"
scan_logs "auditlens-frontend"
scan_logs "auditlens-caddy"

# ─── SECTION 5: BACKUP STATUS ───────────────────────────────────────────────
header "5. BACKUP STATUS"

BACKUP_DIR="/home/ec2-user/AuditLens/backups"
BACKUP_DIR2="/home/ec2-user/backups/postgres"

for dir in "$BACKUP_DIR" "$BACKUP_DIR2"; do
  if [ -d "$dir" ]; then
    LATEST=$(find "$dir" -name "*.sql.gz" -type f -printf '%T@ %p\n' 2>/dev/null | \
      sort -n | tail -1 | awk '{print $2}')
    if [ -n "$LATEST" ]; then
      AGE_HOURS=$(( ($(date +%s) - $(stat -c %Y "$LATEST" 2>/dev/null || echo 0)) / 3600 ))
      SIZE=$(du -sh "$LATEST" 2>/dev/null | cut -f1)
      if [ "$AGE_HOURS" -gt 26 ]; then
        warn "Backup ($dir) — last backup ${AGE_HOURS}h ago ($SIZE) — may have missed a run"
      else
        pass "Backup ($dir) — last backup ${AGE_HOURS}h ago ($SIZE)"
      fi
    else
      warn "Backup ($dir) — no backup files found"
    fi
  fi
done

# Cron job check
CRON_CHECK=$(crontab -l 2>/dev/null | grep -c "backup\|pg_dump" || echo "0")
if [ "$CRON_CHECK" -gt 0 ]; then
  pass "Backup cron — $CRON_CHECK backup job(s) configured"
else
  fail "Backup cron — no backup cron jobs found"
fi

# ─── SECTION 6: PIPELINE FRESHNESS ─────────────────────────────────────────
header "6. PIPELINE FRESHNESS"

# Last event timestamp
LAST_EVENT=$(docker exec auditlens-postgres psql -U auditlens -d auditlens \
  -c "SELECT extract(epoch from (now() - max(timestamp)))::int FROM audit_events;" \
  -t 2>/dev/null | tr -d ' ' || echo "999999")

if [[ "$LAST_EVENT" =~ ^[0-9]+$ ]]; then
  LAST_MINS=$((LAST_EVENT / 60))
  if [ "$LAST_MINS" -lt 5 ]; then
    pass "Last signal event — ${LAST_MINS}m ago (fresh)"
  elif [ "$LAST_MINS" -lt 60 ]; then
    warn "Last signal event — ${LAST_MINS}m ago (slightly stale)"
  else
    fail "Last signal event — ${LAST_MINS}m ago (stale, forwarder may be stuck)"
  fi
fi

# Consumer lag trend
if [ -n "$FWD_HEALTH" ]; then
  LAG_NUM=$(echo "$FWD_HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('consumer_lag',0))" 2>/dev/null || echo "0")
  if [ "$LAG_NUM" -lt 10000 ] 2>/dev/null; then
    pass "Consumer lag — $LAG_NUM (healthy)"
  elif [ "$LAG_NUM" -lt 100000 ] 2>/dev/null; then
    warn "Consumer lag — $LAG_NUM (elevated, catching up)"
  else
    fail "Consumer lag — $LAG_NUM (critical)"
  fi
fi

# ─── SECTION 7: MEMORY & RESOURCES ─────────────────────────────────────────
header "7. MEMORY & RESOURCES"

# Container memory usage
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}" 2>/dev/null | \
  grep -E "auditlens|audit-|NAME" | while IFS=$'\t' read -r name mem cpu; do
  if [ "$name" = "NAME" ]; then continue; fi
  echo -e "  ${BLUE}→${NC} $name — mem: $mem, cpu: $cpu"
done

# Total memory
FREE_MEM=$(free -h | awk 'NR==2 {print $7}')
TOTAL_MEM=$(free -h | awk 'NR==2 {print $2}')
pass "System memory — $FREE_MEM available of $TOTAL_MEM"

# ─── FINAL REPORT ───────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║                    HEALTH SUMMARY                       ║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${BOLD}║  ${GREEN}✅ PASSED: $PASS${NC}$(printf '%*s' $((42-${#PASS})) '')${BOLD}║${NC}"
echo -e "${BOLD}║  ${YELLOW}⚠️  WARNED: $WARN${NC}$(printf '%*s' $((42-${#WARN})) '')${BOLD}║${NC}"
echo -e "${BOLD}║  ${RED}❌ FAILED: $FAIL${NC}$(printf '%*s' $((42-${#FAIL})) '')${BOLD}║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════╣${NC}"

if [ "$FAIL" -eq 0 ] && [ "$WARN" -eq 0 ]; then
  echo -e "${BOLD}║  ${GREEN}🟢 ALL SYSTEMS HEALTHY — READY FOR DEMO${NC}$(printf '%*s' 16 '')${BOLD}║${NC}"
elif [ "$FAIL" -eq 0 ]; then
  echo -e "${BOLD}║  ${YELLOW}🟡 HEALTHY WITH WARNINGS — REVIEW ABOVE${NC}$(printf '%*s' 16 '')${BOLD}║${NC}"
else
  echo -e "${BOLD}║  ${RED}🔴 FAILURES DETECTED — ACTION REQUIRED${NC}$(printf '%*s' 17 '')${BOLD}║${NC}"
fi
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
