#!/bin/bash
# AuditLens Postgres auto-tuner
# Uses container memory limit (cgroup) not host RAM.
set -euo pipefail

# Read container memory limit from cgroup (works on Docker/EC2)
# Falls back to host RAM if cgroup limit is unavailable or set to "max"
CGROUP_LIMIT_FILE="/sys/fs/cgroup/memory.max"
CGROUP_LIMIT_BYTES=""
if [ -f "$CGROUP_LIMIT_FILE" ]; then
    CGROUP_LIMIT_BYTES=$(cat "$CGROUP_LIMIT_FILE")
fi

if [ -z "$CGROUP_LIMIT_BYTES" ] || [ "$CGROUP_LIMIT_BYTES" = "max" ]; then
    # Fallback: use 768MB safe default for t3.large with 768M container limit
    TOTAL_RAM_MB=768
else
    TOTAL_RAM_MB=$((CGROUP_LIMIT_BYTES / 1024 / 1024))
fi

# Cap at 768MB regardless — never trust host RAM for container tuning
if [ "$TOTAL_RAM_MB" -gt 768 ]; then TOTAL_RAM_MB=768; fi

# shared_buffers = 25% of container RAM
SHARED_BUFFERS_MB=$((TOTAL_RAM_MB / 4))

# effective_cache_size = 75% of container RAM
EFFECTIVE_CACHE_MB=$((TOTAL_RAM_MB * 3 / 4))

# work_mem: cap at 16MB inside container (parallel workers multiply this)
WORK_MEM_MB=$((TOTAL_RAM_MB / 50))
if [ "$WORK_MEM_MB" -gt 16 ]; then WORK_MEM_MB=16; fi
if [ "$WORK_MEM_MB" -lt 4 ];  then WORK_MEM_MB=4;  fi

# maintenance_work_mem = 10% of RAM, cap at 128MB inside container
MAINT_MEM_MB=$((TOTAL_RAM_MB / 10))
if [ "$MAINT_MEM_MB" -gt 128 ]; then MAINT_MEM_MB=128; fi

# wal_buffers: 3% of shared_buffers, min 8MB max 32MB
WAL_BUFFERS_MB=$((SHARED_BUFFERS_MB * 3 / 100))
if [ "$WAL_BUFFERS_MB" -lt 8 ];  then WAL_BUFFERS_MB=8;  fi
if [ "$WAL_BUFFERS_MB" -gt 32 ]; then WAL_BUFFERS_MB=32; fi

echo "=== AuditLens Postgres Auto-Tune ==="
echo "Container RAM cap:     ${TOTAL_RAM_MB}MB"
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
  -c max_parallel_workers_per_gather=0 \
  -c random_page_cost=1.1 \
  -c synchronous_commit=off \
  -c checkpoint_completion_target=0.9 \
  -c max_wal_size=512MB \
  -c autovacuum_vacuum_scale_factor=0.01 \
  -c autovacuum_analyze_scale_factor=0.005 \
  -c autovacuum_vacuum_cost_delay=2ms \
  -c autovacuum_vacuum_cost_limit=400
