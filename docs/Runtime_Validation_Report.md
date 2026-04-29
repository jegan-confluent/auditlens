# Runtime Validation Report

Timestamp: 2026-04-27T10:11:45Z

This report reflects the current live validation run on 2026-04-27. It replaces the earlier incident-focused report that documented a local disk-full crash and destructive recovery on 2026-04-24.

## Git Status Summary

- Branch: `master`
- Worktree state: dirty, with a large number of modified and untracked files from ongoing productization work.
- This validation pass did not perform broad cleanup or history rewriting.

## Current Runtime State

### Docker Compose

`docker compose ps` shows the current local stack is up:

- `auditlens-forwarder`: Up and healthy, bound to `127.0.0.1:8003`
- `auditlens-landing`: Up, bound to `127.0.0.1:8088`
- `dashboard`: Up, bound to `127.0.0.1:8503`
- `audit-prometheus`: Up, bound to `127.0.0.1:9090`
- `audit-grafana`: Up, bound to `127.0.0.1:3000`
- `loki`, `promtail`: Up

### Landing / Dashboard / Prometheus

- `http://localhost:8088/status` returns:
  - `dashboard: ok`
  - `grafana: ok`
  - `prometheus: ok`
  - `health: ok`
  - `metrics: ok`
- `curl -I http://localhost:8503` returns `HTTP/1.1 200 OK`
- `http://localhost:9090/api/v1/rules` is reachable and returns alert groups

## Health Summary

`curl -s http://localhost:8003/health` currently returns HTTP `200` with top-level status `healthy`.

Key values captured during validation:

- `processed_total`: `2445719`
- `error_count`: `17`
- `observability.persistence_storage.db_file_bytes`: `13345693696`
- `observability.persistence_storage.wal_file_bytes`: `4198312`
- `observability.persistence_storage.free_disk_bytes`: `34294448128`
- `observability.persistence_storage.db_max_bytes`: `5368709120`
- `observability.persistence_storage.storage_status`: `warning`
- `observability.persistence_storage.storage_reasons`: `['database file exceeds configured max']`
- `observability.persistence_storage.cleanup_status`: `success`
- `observability.persistence_storage.last_checkpoint_status`: `success`

Interpretation:

- The current runtime is operational.
- Persistence is healthy.
- The local SQLite hot cache is materially larger than its configured maximum and is correctly exposing a warning state.
- This is a bounded-storage policy gap, not an active crash.

## Metrics Summary

`curl -s http://localhost:8003/metrics` includes the required persistence metrics:

- `audit_forwarder_persistence_db_file_bytes 13354549248`
- `audit_forwarder_persistence_wal_file_bytes 4198312`
- `audit_forwarder_persistence_free_disk_bytes 34285572096`
- `audit_forwarder_persistence_db_max_bytes 5368709120`
- `audit_forwarder_persistence_storage_status 1`
- `audit_forwarder_persistence_cleanup_status 1`
- `audit_forwarder_persistence_checkpoint_status 1`

Interpretation:

- `storage_status=1` means warning.
- Cleanup and checkpoint status are currently healthy.
- The warning condition is driven by database size, not by free-disk exhaustion.

## SQLite Volume Summary

Current persistence volume evidence from `auditlens_auditlens_data`:

- Path inside volume: `/var/lib/auditlens`
- `auditlens.db`: about `13G`
- `auditlens.db-wal`: about `4.1M`
- `auditlens.db-shm`: about `32K`

Implication:

- The product is not currently disk-full.
- The product is currently violating its configured hot-cache size target.
- Static retention is not keeping SQLite within the intended operational bound.

## Alert Rule Summary

Validation passed:

- `docker compose config --quiet`
- `promtool check rules /etc/prometheus/alerts/audit-forwarder.yml`
- `promtool check config /etc/prometheus/prometheus.yml`

Live rules API confirms Prometheus is serving alert groups from `audit-forwarder.yml`, including the storage alerts:

- `AuditForwarderLowDiskWarning`
- `AuditForwarderLowDiskCritical`
- `AuditForwarderSQLiteDbTooLarge`
- `AuditForwarderSQLiteWalTooLarge`
- `AuditForwarderCheckpointFailure`
- `AuditForwarderCleanupFailure`

## Recovery Note

No destructive recovery action was required in this validation pass.

- No Kafka topics were deleted.
- No source audit data was deleted.
- No `.secrets` files were deleted.
- No SQLite backup or cleanup was performed in this pass because the service was already recovered and healthy enough to validate.

The earlier local disk-full incident remains historically relevant, but it was not the current runtime state during this validation run.

## Commands Run

```bash
docker compose ps
docker compose logs --tail=200 auditlens-forwarder
docker compose logs --tail=200 prometheus
docker system df -v
docker volume ls
docker volume inspect auditlens_auditlens_data
curl -sv http://localhost:8003/health
curl -sv http://localhost:8003/metrics
curl -s http://localhost:8088/status
curl -I http://localhost:8503
curl -s http://localhost:9090/api/v1/rules
docker compose config --quiet
docker run --rm --entrypoint /bin/promtool -v /Users/jegan/playground/AuditLens/prometheus:/etc/prometheus prom/prometheus:v2.54.1 check rules /etc/prometheus/alerts/audit-forwarder.yml
docker run --rm --entrypoint /bin/promtool -v /Users/jegan/playground/AuditLens/prometheus:/etc/prometheus prom/prometheus:v2.54.1 check config /etc/prometheus/prometheus.yml
docker run --rm -v auditlens_auditlens_data:/var/lib/auditlens python:3.11-slim sh -lc 'ls -lah /var/lib/auditlens && du -sh /var/lib/auditlens/* 2>/dev/null || true'
API_AUTH_ENABLED=false pytest -q -p no:cacheprovider /Users/jegan/playground/AuditLens/tests/test_productization.py /Users/jegan/playground/AuditLens/tests/test_landing_page.py /Users/jegan/playground/AuditLens/tests/test_dashboard_welcome_health.py
```

## Key Outputs

- Landing status:
  - `{"dashboard": "ok", "grafana": "ok", "prometheus": "ok", "health": "ok", "metrics": "ok"}`
- Test suite:
  - `32 passed in 5.40s`
- Prometheus rule validation:
  - `SUCCESS: 20 rules found`
- Prometheus config validation:
  - `SUCCESS: /etc/prometheus/prometheus.yml is valid prometheus config file syntax`

## Remaining Blockers

1. SQLite exceeds its configured maximum size while still remaining operational. This is a warning state that needs prevention, not just visibility.
2. Static retention is not sufficient to keep the local hot cache bounded under current ingest volume.
3. The dashboard is still not fully API-first or product-grade authenticated.
4. Replay dry-run and stronger deterministic derived identifiers are still open reliability gaps.
5. Long-term archive integration is still architectural direction rather than implemented product path.

## Readiness Conclusion

- `/health` works.
- `/metrics` works.
- Landing, dashboard, and Prometheus all work.
- Storage visibility and storage alert rules are live.
- The current environment is operational but not yet storage-safe by design.
- The most important current issue is not an outage. It is that the SQLite hot cache is materially above its configured size bound and is only protected by warning-level detection.
