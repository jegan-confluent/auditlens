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


def _preflight_alembic_version_table_pg(engine) -> None:
    """Ensure alembic_version exists at VARCHAR(128) on Postgres BEFORE
    alembic creates it at the default VARCHAR(32).

    Done with its OWN connection + explicit begin/commit so the DDL is
    durably persisted before alembic opens its own transaction. The
    earlier "begin_nested() on the alembic connection" form leaked an
    uncommitted outer transaction that swallowed every subsequent
    migration write — audit_events would get populated by the forwarder
    later, but alembic_version would never persist, so each restart
    re-ran every migration from scratch (and corrupted state for any
    one-shot migration). The dedicated-connection pattern avoids that
    by committing this DDL on its own, completely independent of the
    alembic context's transaction lifecycle.

    Two cases handled:
      1. Table already exists at any width → CREATE IF NOT EXISTS is a
         no-op, then ALTER widens to 128 (Postgres no-ops the ALTER if
         already that wide).
      2. Fresh DB → table is created at VARCHAR(128); alembic's own
         CREATE IF NOT EXISTS later finds it and skips its narrow create.

    Any DDL failure (lock conflict, missing privilege, parallel runner
    won the race) is swallowed — migrations themselves still run.
    """
    import logging
    logger = logging.getLogger("alembic.env")
    try:
        with engine.connect() as ddl_conn:
            with ddl_conn.begin():
                ddl_conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS alembic_version ("
                    "  version_num VARCHAR(128) NOT NULL,"
                    "  CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
                    ")"
                ))
                ddl_conn.execute(text(
                    "ALTER TABLE alembic_version "
                    "ALTER COLUMN version_num TYPE VARCHAR(128)"
                ))
    except Exception as exc:
        logger.warning("alembic_version preflight skipped: %s", exc)


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {}) or {}
    section["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    # Pre-create alembic_version on Postgres so the column is wide enough
    # for our 35+ character revision IDs (date-prefixed slugs, branch
    # merges). SQLite has no ALTER COLUMN TYPE and uses dynamic typing,
    # so the dialect guard skips it there. This runs on its OWN
    # connection with a committed transaction — never share state with
    # alembic's connection, which manages its own transaction lifecycle.
    if connectable.dialect.name == "postgresql":
        _preflight_alembic_version_table_pg(connectable)

    with connectable.connect() as connection:
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
