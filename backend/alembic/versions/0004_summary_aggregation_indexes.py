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

``IF NOT EXISTS`` makes the revision idempotent if it has already been
applied manually. Previously we used ``CREATE INDEX CONCURRENTLY`` inside
an ``op.get_context().autocommit_block()`` so the forwarder could keep
writing during the build, but ``autocommit_block()`` requires the env to
run migrations outside a transaction and ours uses
``context.begin_transaction()`` — the combination tripped
``AssertionError: assert self._transaction is not None`` and blocked
every fresh install. Standard ``CREATE INDEX`` takes a brief ACCESS
EXCLUSIVE lock on ``audit_events`` (seconds, not minutes — these indexes
are small partials / composites) which is acceptable migration cost.

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
        statements = (
            "CREATE INDEX IF NOT EXISTS idx_audit_events_resource_type_time "
            "ON audit_events (resource_type, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_audit_events_failure_time "
            "ON audit_events (timestamp DESC) WHERE is_failure = true",
            "CREATE INDEX IF NOT EXISTS idx_audit_events_denied_time "
            "ON audit_events (timestamp DESC) WHERE is_denied = true",
        )
        for sql in statements:
            op.execute(text(sql))
        return

    # SQLite (demo / tests). The boolean column is stored as 0/1; the
    # literal ``true`` works through SQLAlchemy but we fork to ``= 1`` to
    # be safe.
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
    # Plain DROP INDEX IF EXISTS — no CONCURRENTLY (would re-introduce
    # the autocommit_block requirement that broke fresh installs).
    for name in _INDEX_NAMES:
        op.execute(text(f"DROP INDEX IF EXISTS {name}"))
