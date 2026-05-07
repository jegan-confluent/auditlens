# AuditLens DB Design

The product database stores normalized audit events in `audit_events`.

## Table

Key columns:

- `id`: database primary key.
- `event_fingerprint`: stable deduplication key with a unique constraint.
- `timestamp`: event time used for ordering, filtering, retention, and health checks.
- `actor`, `result`, `action_category`, `resource_type`, `resource_name`: common filter dimensions.
- `summary`: readable normalized event text.
- `raw_payload_json`: raw audit evidence, returned only from `/events/{event_id}`.
- `resource_display_name`, `resource_scope`, `parent_resource`, `cluster_name`, `environment_name`: persisted resource intelligence fields used by the list and detail views.
- `resource_criticality`, `blast_radius_hint`, `production_hint`: lightweight derived hints for triage.

## Indexes

The schema includes:

- `timestamp DESC`
- `resource_type, resource_name, timestamp DESC`
- `signal_type`, `impact_type`, `risk_level`, `change_type`, `resource_family`
- `timestamp DESC, signal_type`
- `timestamp DESC, impact_type`
- `timestamp DESC, risk_level`
- `action_category, timestamp DESC`
- `actor, timestamp DESC`
- `result, timestamp DESC`
- Supporting single-column indexes for common filters and `event_fingerprint`.

## Resource Catalog

`resource_catalog` stores durable resource identity and hierarchy context without forcing joins in the hot list path. It is best-effort and event-derived, not an authoritative resource inventory.

Key columns:

- `resource_id`: stable resource key
- `resource_type`
- `resource_name`
- `display_name`
- `cluster_id`, `cluster_name`
- `environment_id`, `environment_name`
- `parent_resource`
- `resource_scope`
- `resource_criticality`
- `blast_radius_hint`
- `production_hint`
- `source`
- `metadata_json`
- `first_seen_at`
- `last_seen_at`

The catalog is upserted during ingestion and indexed by `resource_type`, `resource_name`, `cluster_id`, `environment_id`, and `last_seen_at`.

## Retention

`EVENT_RETENTION_DAYS` controls API-side retention cleanup and defaults to 7 days for local/demo mode. Cleanup is available at:

```bash
curl -X POST "http://localhost:8080/admin/retention/cleanup?dry_run=true"
curl -X POST "http://localhost:8080/admin/retention/cleanup?dry_run=false"
```

The cleanup function logs `dry_run`, retention window, cutoff, and deleted count. Use dry-run before deleting production data.

## Health

DB health reports:

- mode: `sqlite` or `postgres`
- connectivity and simple query status
- event count
- oldest event
- newest event
- storage estimate where possible
