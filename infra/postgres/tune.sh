#!/bin/bash
# AuditLens Postgres auto-tuner
# Detects available RAM and sets optimal Postgres parameters.
# Works on any instance size from 2GB (t3.small) to 32GB (t3.2xlarge).
#
# chmod +x ~/AuditLens/infra/postgres/tune.sh  — run once on EC2 after deploy

set -euo pipefail

TOTAL_RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
TOTAL_RAM_MB=$((TOTAL_RAM_KB / 1024))

# shared_buffers = 25% of RAM (Postgres standard recommendation)
SHARED_BUFFERS_MB=$((TOTAL_RAM_MB / 4))

# effective_cache_size = 75% of RAM
EFFECTIVE_CACHE_MB=$((TOTAL_RAM_MB * 3 / 4))

# work_mem: budget 4MB per connection, max_connections=50
# but cap at 64MB to avoid runaway sorts
WORK_MEM_MB=$((TOTAL_RAM_MB / 50))
if [ "$WORK_MEM_MB" -gt 64 ]; then WORK_MEM_MB=64; fi
if [ "$WORK_MEM_MB" -lt 4 ];  then WORK_MEM_MB=4;  fi

# maintenance_work_mem = 10% of RAM, cap at 512MB
MAINT_MEM_MB=$((TOTAL_RAM_MB / 10))
if [ "$MAINT_MEM_MB" -gt 512 ]; then MAINT_MEM_MB=512; fi

# wal_buffers: 3% of shared_buffers, min 8MB max 64MB
WAL_BUFFERS_MB=$((SHARED_BUFFERS_MB * 3 / 100))
if [ "$WAL_BUFFERS_MB" -lt 8 ];  then WAL_BUFFERS_MB=8;  fi
if [ "$WAL_BUFFERS_MB" -gt 64 ]; then WAL_BUFFERS_MB=64; fi

echo "=== AuditLens Postgres Auto-Tune ==="
echo "Instance RAM:          ${TOTAL_RAM_MB}MB"
echo "shared_buffers:        ${SHARED_BUFFERS_MB}MB"
echo "effective_cache_size:  ${EFFECTIVE_CACHE_MB}MB"
echo "work_mem:              ${WORK_MEM_MB}MB"
echo "maintenance_work_mem:  ${MAINT_MEM_MB}MB"
echo "wal_buffers:           ${WAL_BUFFERS_MB}MB"
echo "====================================="

exec docker-entrypoint.sh postgres \
  -c shared_buffers=${SHARED_BUFFERS_MB}MB \
  -c effective_cache_size=${EFFECTIVE_CACHE_MB}MB \
  -c work_mem=${WORK_MEM_MB}MB \
  -c maintenance_work_mem=${MAINT_MEM_MB}MB \
  -c wal_buffers=${WAL_BUFFERS_MB}MB \
  -c max_connections=50 \
  -c random_page_cost=1.1 \
  -c synchronous_commit=off \
  -c checkpoint_completion_target=0.9 \
  -c max_wal_size=1GB \
  -c autovacuum_vacuum_scale_factor=0.01 \
  -c autovacuum_analyze_scale_factor=0.005 \
  -c autovacuum_vacuum_cost_delay=2ms \
  -c autovacuum_vacuum_cost_limit=400
