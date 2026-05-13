"""Normalize stored actor values that carry a spurious "User:" prefix.

Events collected before the normalize_event() fix stored "User:u-xxxxx" and
"User:sa-xxxxx" verbatim in the actor column, splitting what is really one
principal into two distinct actors.  This migration strips the prefix in-place.

Only "User:u-" and "User:sa-" forms are touched.  "User:NNNN" (numeric) is
intentionally excluded — those rows need principalResourceId resolution, not
simple prefix stripping.

For large tables the UPDATE uses the existing btree index on actor
(idx_audit_events_actor_notnull) via the constant-prefix LIKE operator.
For tables > 1M rows consider running this during a maintenance window; the
admin endpoint POST /admin/backfill/normalize-actor-prefixes performs the same
operation in explicit 10K-row batches if needed.

Revision ID: 0018_normalize_user_prefix_actors
Revises: 0017_add_client_tool
Create Date: 2026-05-13
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect, text

revision = "0018_normalize_user_prefix_actors"
down_revision = "0017_add_client_tool"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "audit_events" not in inspector.get_table_names():
        return

    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        # SUBSTRING(col FROM n) — 1-indexed, strips 5 chars ("User:")
        bind.execute(text(
            "UPDATE audit_events"
            " SET actor    = SUBSTRING(actor FROM 6),"
            "     actor_id = SUBSTRING(actor FROM 6)"
            " WHERE actor LIKE 'User:u-%'"
            "    OR actor LIKE 'User:sa-%'"
        ))
    else:
        # SQLite: SUBSTR(col, n)
        bind.execute(text(
            "UPDATE audit_events"
            " SET actor    = SUBSTR(actor, 6),"
            "     actor_id = SUBSTR(actor, 6)"
            " WHERE actor LIKE 'User:u-%'"
            "    OR actor LIKE 'User:sa-%'"
        ))


def downgrade() -> None:
    # Reversing is not safe without the original raw values; downgrade is a no-op.
    pass
