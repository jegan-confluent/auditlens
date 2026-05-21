"""Drop redundant / unused audit_events indexes (35 → 24).

Production telemetry from pg_stat_user_indexes after ~10 days of live
traffic showed 11 indexes with idx_scan = 0 AND no functional reason to
keep them (no purpose-built WHERE clause, no UNIQUE/PK backing). Each
INSERT into audit_events pays the write cost of every index, so dropping
the unused ones is the cheapest write-throughput win available.

Drops (telemetry from live deploy 2026-05-20):
  • idx_audit_events_resource_type              (idx_scan=0; resource_type_time covers)
  • idx_audit_events_timestamp_desc             (idx_scan=0; bare timestamp serves DESC scans)
  • idx_audit_events_timestamp_impact_type      (idx_scan=0; composite never used)
  • idx_audit_events_resource_type_action_category_time
                                                (idx_scan=0; 3-col composite never selected)
  • idx_audit_events_resource_name_time         (idx_scan=0; bare resource_name has 1200 scans)
  • idx_audit_events_source_ip                  (idx_scan=0)
  • idx_audit_events_resource_lookup            (idx_scan=0; 3-col composite never selected)
  • idx_audit_events_change_type                (idx_scan=0)
  • idx_audit_events_impact_type                (idx_scan=0)
  • idx_audit_events_environment_id             (idx_scan=0)
  • idx_audit_events_event_fingerprint          (idx_scan=0; uq_audit_events_event_fingerprint
                                                covers — 27 050 scans on the UNIQUE)

Kept despite idx_scan=0 (intentional defensive partials backing specific
dashboard queries; telemetry window may be too short to be conclusive):
  • idx_audit_events_failure_time         (partial: WHERE is_failure)
  • idx_audit_events_attention_time       (partial: WHERE NOT is_routine_noise)
  • idx_audit_events_actor_notnull        (partial: WHERE actor IS NOT NULL)
  • idx_audit_events_resource_type_notnull (partial: WHERE resource_type IS NOT NULL)
  • idx_audit_events_actor_confidence_low (partial: WHERE actor_confidence='low')
  • idx_audit_events_actor_display_enrichment (partial: WHERE actor_display_name…)

Uses plain ``DROP INDEX IF EXISTS`` (no CONCURRENTLY). The earlier
``autocommit_block() + DROP INDEX CONCURRENTLY`` form failed under
env.py's transactional migration runner with
``AssertionError: assert self._transaction is not None``. The drop now
takes a brief ACCESS EXCLUSIVE lock on audit_events; acceptable
migration cost on a single-process upgrade. See 0004 for the full
rationale.

Revision ID: 0025_deduplicate_audit_events_indexes
Revises: 0024_add_admin_audit_log
Create Date: 2026-05-20
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "0025_deduplicate_audit_events_indexes"
down_revision = "0024_add_admin_audit_log"
branch_labels = None
depends_on = None


_INDEXES_TO_DROP: tuple[str, ...] = (
    "idx_audit_events_resource_type",
    "idx_audit_events_timestamp_desc",
    "idx_audit_events_timestamp_impact_type",
    "idx_audit_events_resource_type_action_category_time",
    "idx_audit_events_resource_name_time",
    "idx_audit_events_source_ip",
    "idx_audit_events_resource_lookup",
    "idx_audit_events_change_type",
    "idx_audit_events_impact_type",
    "idx_audit_events_environment_id",
    "idx_audit_events_event_fingerprint",
)


# CREATE statements that mirror the original index definitions so
# `alembic downgrade` returns the table to its pre-0025 shape. The
# {concurrent} placeholder is retained as an empty string for template
# compatibility — CONCURRENTLY was dropped repo-wide because it
# requires autocommit_block(), which is incompatible with env.py's
# transactional migration runner.
_INDEXES_TO_RECREATE: dict[str, str] = {
    "idx_audit_events_resource_type":
        "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_resource_type "
        "ON audit_events (resource_type)",
    "idx_audit_events_timestamp_desc":
        "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_timestamp_desc "
        "ON audit_events (timestamp DESC)",
    "idx_audit_events_timestamp_impact_type":
        "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_timestamp_impact_type "
        "ON audit_events (timestamp DESC, impact_type)",
    "idx_audit_events_resource_type_action_category_time":
        "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_resource_type_action_category_time "
        "ON audit_events (resource_type, action_category, timestamp DESC)",
    "idx_audit_events_resource_name_time":
        "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_resource_name_time "
        "ON audit_events (resource_name, timestamp DESC)",
    "idx_audit_events_source_ip":
        "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_source_ip "
        "ON audit_events (source_ip)",
    "idx_audit_events_resource_lookup":
        "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_resource_lookup "
        "ON audit_events (resource_type, resource_name, timestamp DESC)",
    "idx_audit_events_change_type":
        "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_change_type "
        "ON audit_events (change_type)",
    "idx_audit_events_impact_type":
        "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_impact_type "
        "ON audit_events (impact_type)",
    "idx_audit_events_environment_id":
        "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_environment_id "
        "ON audit_events (environment_id)",
    "idx_audit_events_event_fingerprint":
        "CREATE INDEX {concurrent}IF NOT EXISTS idx_audit_events_event_fingerprint "
        "ON audit_events (event_fingerprint)",
}


def upgrade() -> None:
    # Plain DROP INDEX IF EXISTS for both dialects. The {concurrent}
    # placeholder in _INDEXES_TO_RECREATE is retained for downgrade
    # template compatibility but always filled with "".
    for name in _INDEXES_TO_DROP:
        op.execute(text(f"DROP INDEX IF EXISTS {name}"))


def downgrade() -> None:
    for name in _INDEXES_TO_DROP:
        op.execute(text(_INDEXES_TO_RECREATE[name].format(concurrent="")))
