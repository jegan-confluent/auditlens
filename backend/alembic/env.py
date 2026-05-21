"""Alembic migration environment for AuditLens.

Activate Alembic for production Postgres deployments via:
    cd backend && alembic upgrade head

The SQLite demo path still uses backend.app.db.database._ensure_audit_event_columns()
to additively patch local databases. Alembic is the canonical schema-change
mechanism when ENABLE_DB_WRITER=true and DATABASE_URL points to Postgres.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool, text

from alembic import context

# Make backend/ and the repo root importable so we can pull in the SQLAlchemy models.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent
for path in (_REPO_ROOT, _BACKEND_DIR):
    str_path = str(path)
    if str_path not in sys.path:
        sys.path.insert(0, str_path)

from backend.app.db.database import normalize_database_url  # noqa: E402
from backend.app.db.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_url() -> str:
    explicit = config.get_main_option("sqlalchemy.url")
    if explicit and explicit not in {"", "driver://user:pass@localhost/dbname"}:
        return normalize_database_url(explicit)
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return normalize_database_url(env_url)
    # Conservative default that lets `alembic upgrade head` succeed in dev/demo.
    return normalize_database_url("sqlite:///./data/auditlens.db")


target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {}) or {}
    section["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        # Postgres-only: widen alembic_version.version_num from the default
        # VARCHAR(32) to VARCHAR(128) so longer revision IDs (date-prefixed
        # slugs, branch-merge nodes) stop tripping `value too long for type
        # character varying(32)` when alembic stamps the new head. Wrapped
        # in a SAVEPOINT so a failure (column already wide, table missing
        # on first install) does not abort the outer migration transaction.
        # SQLite has no ALTER COLUMN TYPE and does not exhibit the failure,
        # so the dialect guard keeps test runs clean.
        if connection.dialect.name == "postgresql":
            try:
                with connection.begin_nested():
                    connection.execute(text(
                        "ALTER TABLE alembic_version "
                        "ALTER COLUMN version_num TYPE VARCHAR(128)"
                    ))
            except Exception:
                # Column already wide, table doesn't exist yet, or operator
                # lacks ALTER privilege — none of those should block the
                # actual migrations from running.
                pass
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
