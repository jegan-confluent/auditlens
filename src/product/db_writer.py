import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.product.event_normalization import event_fingerprint, normalize_event, parse_event_timestamp

logger = logging.getLogger(__name__)


@dataclass
class DbWriteResult:
    attempted: int
    inserted: int
    elapsed_ms: float


metadata = MetaData()

audit_events = Table(
    "audit_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_fingerprint", String(64), nullable=False),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    Column("result", String(32), nullable=False),
    Column("actor", String(255), nullable=False),
    Column("action", String(255), nullable=False),
    Column("normalized_action", String(255), nullable=False),
    Column("action_category", String(64), nullable=False),
    Column("resource_type", String(128), nullable=False),
    Column("resource_name", String(512), nullable=False),
    Column("resource_display", String(768), nullable=False),
    Column("cluster_id", String(255), nullable=True),
    Column("source_ip", String(128), nullable=True),
    Column("summary", Text, nullable=False),
    Column("raw_payload_json", Text, nullable=False),
    Column("is_failure", Boolean, nullable=False),
    Column("is_denied", Boolean, nullable=False),
    Column("is_routine_noise", Boolean, nullable=False),
    UniqueConstraint("event_fingerprint", name="uq_audit_events_event_fingerprint"),
)

Index("idx_audit_events_timestamp", audit_events.c.timestamp)
Index("idx_audit_events_event_fingerprint", audit_events.c.event_fingerprint)
Index("idx_audit_events_actor", audit_events.c.actor)
Index("idx_audit_events_resource_type", audit_events.c.resource_type)
Index("idx_audit_events_resource_name", audit_events.c.resource_name)
Index("idx_audit_events_action_category", audit_events.c.action_category)
Index("idx_audit_events_result", audit_events.c.result)
Index("idx_audit_events_timestamp_desc", audit_events.c.timestamp.desc())
Index("idx_audit_events_resource_lookup", audit_events.c.resource_type, audit_events.c.resource_name, audit_events.c.timestamp.desc())
Index("idx_audit_events_action_category_time", audit_events.c.action_category, audit_events.c.timestamp.desc())
Index("idx_audit_events_actor_time", audit_events.c.actor, audit_events.c.timestamp.desc())
Index("idx_audit_events_result_time", audit_events.c.result, audit_events.c.timestamp.desc())


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


class AuditEventDbWriter:
    def __init__(
        self,
        database_url: str,
        *,
        retention_days: int = 7,
        retention_cleanup_interval_seconds: float = 3600.0,
    ):
        self.database_url = normalize_database_url(database_url)
        self.retention_days = max(1, int(retention_days))
        self.retention_cleanup_interval_seconds = max(1.0, float(retention_cleanup_interval_seconds))
        self.last_cleanup_at: str | None = None
        self.last_cleanup_deleted_count = 0
        self._last_cleanup_monotonic = 0.0
        connect_args = {"check_same_thread": False} if self.database_url.startswith("sqlite") else {}
        self.engine = create_engine(self.database_url, future=True, pool_pre_ping=True, connect_args=connect_args)
        metadata.create_all(self.engine)

    @property
    def mode(self) -> str:
        return "postgres" if self.database_url.startswith("postgresql") else "sqlite"

    def _row(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_event(payload)
        return {
            "event_fingerprint": event_fingerprint(payload),
            "timestamp": parse_event_timestamp(payload),
            "raw_payload_json": json.dumps(payload, sort_keys=True, default=str),
            **normalized,
        }

    def write_batch(self, payloads: list[dict[str, Any]]) -> DbWriteResult:
        rows = [self._row(payload) for payload in payloads]
        if not rows:
            return DbWriteResult(attempted=0, inserted=0, elapsed_ms=0.0)
        started = time.perf_counter()
        if self.mode == "postgres":
            statement = (
                postgres_insert(audit_events)
                .values(rows)
                .on_conflict_do_nothing(index_elements=["event_fingerprint"])
                .returning(audit_events.c.event_fingerprint)
            )
        else:
            statement = sqlite_insert(audit_events).values(rows).on_conflict_do_nothing(index_elements=["event_fingerprint"])
        with self.engine.begin() as conn:
            result = conn.execute(statement)
            inserted = len(result.fetchall()) if self.mode == "postgres" else int(result.rowcount or 0)
        return DbWriteResult(attempted=len(rows), inserted=inserted, elapsed_ms=(time.perf_counter() - started) * 1000)

    def cleanup_retention(self, *, dry_run: bool = False, retention_days: int | None = None) -> dict[str, Any]:
        days = max(1, int(retention_days or self.retention_days))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with self.engine.begin() as conn:
            count = int(conn.execute(select(func.count()).select_from(audit_events).where(audit_events.c.timestamp < cutoff)).scalar() or 0)
            if not dry_run and count:
                conn.execute(delete(audit_events).where(audit_events.c.timestamp < cutoff))
        if not dry_run:
            self.last_cleanup_at = datetime.now(timezone.utc).isoformat()
            self.last_cleanup_deleted_count = count
            self._last_cleanup_monotonic = time.monotonic()
        logger.info(
            "DB writer retention cleanup complete dry_run=%s retention_days=%s cutoff=%s deleted_count=%s",
            dry_run,
            days,
            cutoff.isoformat(),
            count,
        )
        return {
            "dry_run": dry_run,
            "retention_days": days,
            "cutoff": cutoff.isoformat(),
            "deleted_count": count,
            "last_cleanup_at": self.last_cleanup_at,
        }

    def cleanup_retention_if_due(self) -> dict[str, Any] | None:
        if time.monotonic() - self._last_cleanup_monotonic < self.retention_cleanup_interval_seconds:
            return None
        return self.cleanup_retention(dry_run=False)

    def health(self) -> dict[str, Any]:
        with self.engine.connect() as conn:
            conn.exec_driver_sql("select 1")
            count = conn.exec_driver_sql("select count(*) from audit_events").scalar()
        return {
            "mode": self.mode,
            "event_count": int(count or 0),
            "retention_days": self.retention_days,
            "last_cleanup_at": self.last_cleanup_at,
            "last_cleanup_deleted_count": self.last_cleanup_deleted_count,
            "checked_at": datetime.utcnow().isoformat() + "Z",
        }
