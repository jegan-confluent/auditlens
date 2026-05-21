"""Drop indexes on audit_events that pg_stat_user_indexes shows unused.

Production telemetry (pg_stat_user_indexes after several days of forwarder
ingestion + dashboard reads) shows the indexes listed below have ``idx_scan=0``.
Each index still costs a write on every INSERT into audit_events. With the
forwarder ingesting hundreds of events per second, dropping unused indexes is
the single biggest write-throughput improvement available.

Kept (idx_scan > 0 OR backing a UNIQUE/PK constraint):
- audit_events_pkey, uq_audit_events_event_fingerprint
- idx_audit_events_timestamp{_desc}, idx_audit_events_signal_type
- idx_audit_events_action_category, idx_audit_events_result
- idx_audit_events_resource_type, idx_audit_events_actor_notnull
- idx_audit_events_timestamp_signal_type / _impact_type
- idx_audit_events_action_category_time, idx_audit_events_result_time
- idx_audit_events_resource_type_time, idx_audit_events_failure_time
- idx_audit_events_denied_time, idx_audit_events_resource_name_time
- idx_audit_events_resource_type_action_category_time

Revision ID: 0006_drop_unused_indexes
Revises: 0005_filter_options_partial_indexes
Create Date: 2026-05-09
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "0006_drop_unused_indexes"
down_revision = "0005_filter_options_partial_indexes"
branch_labels = None
depends_on = None


_INDEXES_TO_DROP: tuple[str, ...] = (
    "idx_audit_events_event_fingerprint",
    "idx_audit_events_actor",
    "idx_audit_events_actor_id",
    "idx_audit_events_resource_name",
    "idx_audit_events_source_ip",
    "idx_audit_events_environment_id",
    "idx_audit_events_cluster_name",
    "idx_audit_events_environment_name",
    "idx_audit_events_parent_resource",
    "idx_audit_events_resource_scope",
    "idx_audit_events_resource_display_name",
    "idx_audit_events_resource_criticality",
    "idx_audit_events_impact_type",
    "idx_audit_events_risk_level",
    "idx_audit_events_change_type",
    "idx_audit_events_resource_family",
    "idx_audit_events_timestamp_risk_level",
    "idx_audit_events_resource_lookup",
    "idx_audit_events_actor_time",
    "idx_audit_events_resource_type_notnull",
)


_INDEXES_TO_RECREATE: dict[str, str] = {
    "idx_audit_events_event_fingerprint": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_event_fingerprint ON audit_events (event_fingerprint)",
    "idx_audit_events_actor": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_actor ON audit_events (actor)",
    "idx_audit_events_actor_id": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_actor_id ON audit_events (actor_id)",
    "idx_audit_events_resource_name": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_resource_name ON audit_events (resource_name)",
    "idx_audit_events_source_ip": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_source_ip ON audit_events (source_ip)",
    "idx_audit_events_environment_id": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_environment_id ON audit_events (environment_id)",
    "idx_audit_events_cluster_name": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_cluster_name ON audit_events (cluster_name)",
    "idx_audit_events_environment_name": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_environment_name ON audit_events (environment_name)",
    "idx_audit_events_parent_resource": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_parent_resource ON audit_events (parent_resource)",
    "idx_audit_events_resource_scope": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_resource_scope ON audit_events (resource_scope)",
    "idx_audit_events_resource_display_name": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_resource_display_name ON audit_events (resource_display_name)",
    "idx_audit_events_resource_criticality": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_resource_criticality ON audit_events (resource_criticality)",
    "idx_audit_events_impact_type": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_impact_type ON audit_events (impact_type)",
    "idx_audit_events_risk_level": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_risk_level ON audit_events (risk_level)",
    "idx_audit_events_change_type": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_change_type ON audit_events (change_type)",
    "idx_audit_events_resource_family": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_resource_family ON audit_events (resource_family)",
    "idx_audit_events_timestamp_risk_level": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_timestamp_risk_level ON audit_events (timestamp DESC, risk_level)",
    "idx_audit_events_resource_lookup": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_resource_lookup ON audit_events (resource_type, resource_name, timestamp DESC)",
    "idx_audit_events_actor_time": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_actor_time ON audit_events (actor, timestamp DESC)",
    "idx_audit_events_resource_type_notnull": "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_resource_type_notnull ON audit_events (resource_type) WHERE resource_type IS NOT NULL AND resource_type != ''",
}


def upgrade() -> None:
    # Plain DROP INDEX (no CONCURRENTLY). autocommit_block + CONCURRENTLY
    # was incompatible with env.py's transactional migration runner —
    # ran into `AssertionError: assert self._transaction is not None`.
    # See 0004_summary_aggregation_indexes.py for the full rationale.
    for name in _INDEXES_TO_DROP:
        op.execute(text(f"DROP INDEX IF EXISTS {name}"))


def downgrade() -> None:
    # downgrade re-creates each previously-dropped index. Plain
    # (non-concurrent) CREATE for the same migration-transaction reason
    # — the {concurrent} placeholder is now always filled with "".
    for name in _INDEXES_TO_DROP:
        op.execute(text(_INDEXES_TO_RECREATE[name].format(concurrent="")))
