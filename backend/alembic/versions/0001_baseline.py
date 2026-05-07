"""Baseline schema for AuditLens.

This revision codifies the schema as it exists at the cutover from hand-rolled
``Base.metadata.create_all`` + ``ALTER TABLE`` patches to Alembic-managed
migrations. It is safe to run on:

* a fresh database (creates every table, column, and index from
  ``backend.app.db.models.Base.metadata``)
* an existing database that already has these objects (every ``op.create_*``
  call uses ``checkfirst`` semantics via the underlying SQLAlchemy DDL)

This baseline is dialect-agnostic so the migration smoke test can run it
against an in-memory SQLite engine. The Postgres production path activates
when ``ENABLE_DB_WRITER=true`` and ``DATABASE_URL`` points to Postgres.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-05-07
"""

from __future__ import annotations

from alembic import op

from backend.app.db.models import Base

# revision identifiers, used by Alembic.
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # ``create_all`` issues IF NOT EXISTS internally, which makes this safe to
    # apply against a database whose tables were created by the legacy
    # ``init_db()`` path. Indexes defined on the metadata come along for free.
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, checkfirst=True)
