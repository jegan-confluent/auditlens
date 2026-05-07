from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import get_settings
from backend.app.db.models import Base


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def _ensure_sqlite_parent(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return
    path_text = database_url.replace("sqlite:///", "", 1)
    if path_text in {":memory:", ""}:
        return
    path = Path(path_text)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)


def build_engine(database_url: str | None = None) -> Engine:
    """Build the SQLAlchemy engine for the configured database URL.

    The engine is tuned per dialect:

    * **Postgres**: an explicit pool (size 5, overflow 10, recycle 30 min) and
      ``statement_timeout=30s`` so a single slow query cannot hold a connection
      indefinitely or exhaust the pool.
    * **SQLite**: ``check_same_thread=False`` for FastAPI's threaded session
      handling, plus a ``foreign_keys=ON`` PRAGMA so the
      ``audit_event_triage`` -> ``audit_events`` cascade is honoured in demo /
      test mode.
    """
    url = normalize_database_url(database_url or get_settings().database_url)
    _ensure_sqlite_parent(url)

    if url.startswith("sqlite"):
        # SQLite (demo + tests). Pool tuning is not meaningful here; SQLAlchemy
        # uses StaticPool/NullPool semantics depending on the URL.
        connect_args = {"check_same_thread": False}
        engine = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)

        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):  # noqa: D401
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

        return engine

    # Postgres production path. Pool sizing and statement_timeout are tuned for
    # a single API replica handling typical dashboard traffic; bump pool_size /
    # max_overflow when running multiple replicas behind the ALB.
    pg_connect_args: dict = {}
    if url.startswith("postgresql"):
        # 30s statement timeout — protects the pool from one slow query blocking
        # all other requests. Tune via the PG server if a longer query is
        # legitimately needed for an admin operation.
        pg_connect_args["options"] = "-c statement_timeout=30000"

    return create_engine(
        url,
        future=True,
        pool_pre_ping=True,
        pool_size=5,            # baseline concurrent connections
        max_overflow=10,        # burst capacity above pool_size
        pool_timeout=30,        # seconds to wait for a free connection before raising
        pool_recycle=1800,      # recycle connections every 30 min to dodge idle TCP RST
        connect_args=pg_connect_args,
    )


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db(db_engine: Engine | None = None) -> None:
    target = db_engine or engine
    Base.metadata.create_all(bind=target)
    _ensure_audit_event_columns(target)
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            index.create(bind=target, checkfirst=True)


def _ensure_audit_event_columns(target: Engine) -> None:
    """SQLite-friendly additive column patch.

    Postgres deployments should manage schema via Alembic
    (``cd backend && alembic upgrade head``). This function still runs for
    SQLite demo databases that pre-date an additive column. The Alembic
    revision ``0002_ensure_decision_columns`` applies the same patch on
    Postgres.
    """
    inspector = inspect(target)
    if "audit_events" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("audit_events")}
    additions = {
        "actor_id": "VARCHAR(255)",
        "actor_display_name": "VARCHAR(255)",
        "actor_email": "VARCHAR(255)",
        "actor_type": "VARCHAR(64)",
        "actor_source": "VARCHAR(64)",
        "actor_confidence": "VARCHAR(32)",
        "actor_enriched_at": "VARCHAR(64)",
        "source_context": "VARCHAR(255)",
        "client_id": "VARCHAR(255)",
        "connection_id": "VARCHAR(255)",
        "request_id": "VARCHAR(255)",
        "environment_id": "VARCHAR(255)",
        "cluster_name": "VARCHAR(255)",
        "environment_name": "VARCHAR(255)",
        "parent_resource": "VARCHAR(255)",
        "resource_scope": "VARCHAR(512)",
        "resource_display_name": "VARCHAR(768)",
        "resource_criticality": "VARCHAR(32)",
        "blast_radius_hint": "VARCHAR(64)",
        "production_hint": "VARCHAR(64)",
        "flink_region": "VARCHAR(255)",
        "network_id": "VARCHAR(255)",
        "signal_type": "VARCHAR(32)",
        "signal_reason": "VARCHAR(128)",
        "impact_type": "VARCHAR(64)",
        "risk_level": "VARCHAR(32)",
        "change_type": "VARCHAR(32)",
        "resource_family": "VARCHAR(64)",
        "event_title": "VARCHAR(255)",
        "event_summary": "VARCHAR(768)",
        "decision_reason": "VARCHAR(255)",
        "decision_label": "VARCHAR(32)",
        "recommended_action": "VARCHAR(255)",
    }
    dialect = target.dialect.name
    with target.begin() as conn:
        for name, type_sql in additions.items():
            if name in existing:
                continue
            if dialect == "postgresql":
                conn.execute(text(f"ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS {name} {type_sql}"))
            else:
                conn.execute(text(f"ALTER TABLE audit_events ADD COLUMN {name} {type_sql}"))


def check_db_health(db_engine: Engine | None = None) -> dict:
    target = db_engine or engine
    with target.connect() as conn:
        return _health_from_connection(conn)


def check_db_health_session(db: Session) -> dict:
    return _health_from_connection(db.connection())


def _health_from_connection(conn) -> dict:
    conn.execute(text("select 1"))
    event_count = conn.execute(text("select count(*) from audit_events")).scalar_one()
    oldest = conn.execute(text("select min(timestamp) from audit_events")).scalar_one()
    newest = conn.execute(text("select max(timestamp) from audit_events")).scalar_one()
    return {
        "can_connect": True,
        "can_query": True,
        "event_count": int(event_count or 0),
        "oldest_event": str(oldest) if oldest is not None else None,
        "newest_event": str(newest) if newest is not None else None,
    }


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
