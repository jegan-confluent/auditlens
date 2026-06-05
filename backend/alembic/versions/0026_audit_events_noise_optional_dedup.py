"""Documentation-only migration: optional dedup for audit_events_noise.

audit_events_noise intentionally has NO unique constraint so the bulk
noise path stays as cheap as possible (~50x lower per-row INSERT cost
than audit_events). On forwarder restart / rebalance / replay, noise
events are re-INSERTed; with the default 3-day retention this is a
bounded storage cost, and the canonical operator response is "query
audit_events for exact counts, audit_events_noise for trend shape".

This migration is a NO-OP by default. Operators who require strict
noise-event dedup (rare — usually only relevant when computing per-
actor authz/produce/fetch rate-of-change against the noise table)
can uncomment the SQL block in `upgrade()` to add a partial unique
index keyed on (timestamp, actor, action, source_ip, resource_name).

Trade-off the operator buys:
  - ~15% write overhead on the bulk lane (index maintenance on every
    INSERT, even when the conflict path doesn't fire).
  - Possible INSERT failures with `IntegrityError: duplicate key` —
    write_noise_batch would need updating to call ON CONFLICT DO
    NOTHING. The bulk INSERT path is currently a plain executemany
    against a constraint-free table; adding the constraint here alone
    will break ingestion until write_noise_batch is also updated.
    Treat this migration as PAIRED with a writer-side patch.

Revision ID: 0026_audit_events_noise_optional_dedup
Revises: 0025_deduplicate_audit_events_indexes
Create Date: 2026-06-05
"""

from __future__ import annotations

# from alembic import op  # uncomment when enabling the SQL block below
# import sqlalchemy as sa  # uncomment when enabling the SQL block below

revision = "0026_audit_events_noise_optional_dedup"
down_revision = "0025_deduplicate_audit_events_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Default: no schema change. Uncomment the block below AND patch
    src/product/db_writer.py:write_noise_batch to use ON CONFLICT DO
    NOTHING before applying."""
    # OPT-IN: enable noise dedup
    # ─────────────────────────
    # bind = op.get_bind()
    # if bind.dialect.name != "postgresql":
    #     # SQLite demo path: skip. The noise table is Postgres-tuned.
    #     return
    # op.execute(
    #     "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
    #     "uq_audit_events_noise_dedup "
    #     "ON audit_events_noise (timestamp, actor, action, "
    #     "source_ip, resource_name)"
    # )
    pass


def downgrade() -> None:
    """Default: no-op. If the optional dedup index was created, uncomment
    the matching drop here before downgrading."""
    # op.execute("DROP INDEX IF EXISTS uq_audit_events_noise_dedup")
    pass
