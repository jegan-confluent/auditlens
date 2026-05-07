from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
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
    url = normalize_database_url(database_url or get_settings().database_url)
    _ensure_sqlite_parent(url)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)


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
