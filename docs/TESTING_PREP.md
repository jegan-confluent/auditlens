# AuditLens Testing Prep

This document is the operator-facing test checklist for the single-instance
AuditLens foundation. It is intentionally practical: restart it, wipe the
SQLite file, replay from Kafka, and confirm the product tells the truth.

## Test Checklist

Validate these before calling the foundation ready for broader use:

- startup validation fails when required Kafka or auth config is missing
- authenticated API access works and unauthenticated access is rejected
- role-gated export blocks `viewer` and allows `exporter` or `admin`
- enriched events persist to SQLite
- denial summaries persist to SQLite
- `/api/v1/events/search` returns persisted records
- `/api/v1/export` returns persisted records and metadata headers
- `/health` exposes freshness, coverage, persistence, and replay status
- restart before commit replays uncommitted work
- restart after commit does not reprocess already committed work
- replay from Kafka rebuilds persistence after local SQLite loss

## Sample Test Data

Use existing repository fixtures and tests:

- `tests/test_productization.py`
- `tests/test_classification.py`
- `tests/test_principal_normalization.py`
- `tests/test_denial_aggregator.py`
- `tests/test_routing.py`

For live validation, choose a recent Kafka window containing:

- at least one destructive event
- repeated authorization failures
- low-risk read/list traffic

That mix proves classification, noise suppression, replay, and export behavior.

## Simulate Restart

Docker:

```bash
docker compose restart auditlens-forwarder
```

Kubernetes:

```bash
kubectl rollout restart deployment/auditlens-forwarder
```

Validate after restart:

- `/health` is live
- persisted records remain searchable
- replay is not incorrectly shown as active
- freshness resumes once new events arrive

## Simulate Persistence Loss

Docker:

1. Stop the forwarder.
2. Remove the SQLite file from the mounted volume.
3. Start the forwarder again.

Kubernetes:

1. Scale the deployment to zero.
2. Remove the SQLite file from the mounted PVC.
3. Scale back to one replica.

Expected outcome:

- Kafka offsets remain intact
- recent product search/export history is missing until replay completes
- `/health` continues to report the persistence state honestly

## Trigger Replay

CLI:

```bash
python3 audit_forwarder.py replay --source-mode raw --hours 24
```

API:

```bash
curl -X POST http://localhost:8003/api/v1/replay \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"source_mode":"raw","hours":24}'
```

Optional full rebuild:

```bash
python3 audit_forwarder.py replay --source-mode raw --from-earliest
```

## Validate Replay Results

Confirm all of the following:

- logs show replay start, progress, and completion
- `/health` shows `replay.in_progress=false` after completion
- `/health` shows `last_replay_time` and replay coverage metadata
- persisted enriched events repopulate
- high-risk events reappear
- denial summaries reappear
- duplicate rows are not created in SQLite

## Recommended Commands

```bash
python3 -m py_compile audit_forwarder.py src/product/auth.py src/product/persistence.py
pytest -q tests/test_productization.py tests/test_foundation_contract.py tests/test_classification.py tests/test_principal_normalization.py tests/test_denial_aggregator.py tests/test_routing.py
```

## Honest Limits

- This is a single-instance foundation, not HA.
- Replay depends on Kafka retention for the selected source topic.
- If Kafka evidence has already expired, AuditLens cannot reconstruct it.
- Replay is intentionally operator-triggered rather than automatic.
