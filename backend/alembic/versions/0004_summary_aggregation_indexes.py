"""Indexes that close the gaps in /summary aggregation queries.

The summary route issues several aggregations against ``audit_events`` filtered
by ``timestamp >= cutoff`` (plus an optional decision-mode OR predicate). At
production volume (10M+ rows, 31 GB) the existing index set already covered:

* ``GROUP BY action_category`` — ``idx_audit_events_action_category_time``
* ``GROUP BY result`` — ``idx_audit_events_result_time``

The three remaining hot queries had no targeted index:

* ``GROUP BY resource_type`` over a time window
* ``count(*) WHERE is_failure = true`` over a time window
* ``count(*) WHERE is_denied = true`` over a time window

This revision adds:

1. ``idx_audit_events_resource_type_time`` — composite ``(resource_type, timestamp DESC)``
2. ``idx_audit_events_failure_time`` — partial ``(timestamp DESC) WHERE is_failure = true``
3. ``idx_audit_events_denied_time`` — partial ``(timestamp DESC) WHERE is_denied = true``

On Postgres we build with ``CREATE INDEX CONCURRENTLY`` so the live forwarder
keeps writing while the index is being built. ``IF NOT EXISTS`` makes the
revision idempotent if it has already been applied manually.

Revision ID: 0004_summary_aggregation_indexes
Revises: 0003_triage_cascade_fk
Create Date: 2026-05-07
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "0004_summary_aggregation_indexes"
down_revision = "0003_triage_cascade_fk"
branch_labels = None
depends_on = None


_INDEX_NAMES: tuple[str, ...] = (
    "idx_audit_events_resource_type_time",
    "idx_audit_events_failure_time",
    "idx_audit_events_denied_time",
)


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        # CONCURRENTLY cannot run inside a transaction, so wrap each statement
        # in autocommit. Build order matches the priority of the queries that
        # benefit: the resource-type composite first, then the partial indexes.
        statements = (
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_events_resource_type_time "
            "ON audit_events (resource_type, timestamp DESC)",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_events_failure_time "
            "ON audit_events (timestamp DESC) WHERE is_failure = true",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_events_denied_time "
            "ON audit_events (timestamp DESC) WHERE is_denied = true",
        )
        with op.get_context().autocommit_block():
            for sql in statements:
                op.execute(text(sql))
        return

    # SQLite (demo / tests). No CONCURRENTLY; partial-index syntax matches.
    # The boolean column is stored as 0/1 in SQLite; the literal ``true``
    # works through the SQLAlchemy parser, but we fork to ``= 1`` to be safe.
    sqlite_statements = (
        "CREATE INDEX IF NOT EXISTS idx_audit_events_resource_type_time "
        "ON audit_events (resource_type, timestamp DESC)",
        "CREATE INDEX IF NOT EXISTS idx_audit_events_failure_time "
        "ON audit_events (timestamp DESC) WHERE is_failure = 1",
        "CREATE INDEX IF NOT EXISTS idx_audit_events_denied_time "
        "ON audit_events (timestamp DESC) WHERE is_denied = 1",
    )
    for sql in sqlite_statements:
        op.execute(text(sql))


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        with op.get_context().autocommit_block():
            for name in _INDEX_NAMES:
                op.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {name}"))
        return
    for name in _INDEX_NAMES:
        op.execute(text(f"DROP INDEX IF EXISTS {name}"))
