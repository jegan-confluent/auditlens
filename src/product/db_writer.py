import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
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
    inspect,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backend.app.db.column_spec import AUDIT_EVENT_COLUMNS
from src.product.event_normalization import (
    event_fingerprint,
    minimal_normalize,
    normalize_event,
    parse_event_timestamp,
)
from src.product.resource_intelligence import build_resource_catalog_entry

logger = logging.getLogger(__name__)


@dataclass
class DbWriteResult:
    attempted: int
    inserted: int
    elapsed_ms: float
    # Per-phase breakdown so operators can tell at a glance whether a slow
    # batch is dominated by row-building, the PG INSERT, or the catalog upsert.
    normalize_ms: float = 0.0
    pg_insert_ms: float = 0.0
    catalog_upsert_ms: float = 0.0
    # When write_batch is called with defer_catalog=True, the caller is given
    # the prepared catalog rows so they can be queued for an out-of-band
    # upsert thread instead of paying for the upsert in the hot path.
    deferred_catalog_rows: list = None


metadata = MetaData()

audit_events = Table(
    "audit_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_fingerprint", String(64), nullable=False),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    Column("result", String(32), nullable=False),
    Column("actor", String(255), nullable=False),
    Column("actor_id", String(255), nullable=True),
    Column("actor_display_name", String(255), nullable=True),
    Column("actor_email", String(255), nullable=True),
    Column("actor_type", String(64), nullable=True),
    Column("actor_source", String(64), nullable=True),
    Column("actor_confidence", String(32), nullable=True),
    Column("actor_enriched_at", String(64), nullable=True),
    Column("action", String(255), nullable=False),
    Column("normalized_action", String(255), nullable=False),
    Column("action_category", String(64), nullable=False),
    Column("resource_type", String(128), nullable=False),
    Column("resource_name", String(512), nullable=False),
    Column("resource_display", String(768), nullable=False),
    Column("cluster_id", String(255), nullable=True),
    Column("source_ip", String(128), nullable=True),
    Column("source_context", String(255), nullable=True),
    Column("client_id", String(255), nullable=True),
    Column("connection_id", String(255), nullable=True),
    Column("request_id", String(255), nullable=True),
    Column("environment_id", String(255), nullable=True),
    Column("cluster_name", String(255), nullable=True),
    Column("environment_name", String(255), nullable=True),
    Column("parent_resource", String(255), nullable=True),
    Column("resource_scope", String(512), nullable=True),
    Column("resource_display_name", String(768), nullable=True),
    Column("resource_criticality", String(32), nullable=True),
    Column("blast_radius_hint", String(64), nullable=True),
    Column("production_hint", String(64), nullable=True),
    Column("flink_region", String(255), nullable=True),
    Column("network_id", String(255), nullable=True),
    Column("signal_type", String(32), nullable=True),
    Column("signal_reason", String(128), nullable=True),
    Column("impact_type", String(64), nullable=True),
    Column("risk_level", String(32), nullable=True),
    Column("change_type", String(32), nullable=True),
    Column("resource_family", String(64), nullable=True),
    Column("event_title", String(255), nullable=True),
    Column("event_summary", String(768), nullable=True),
    Column("decision_reason", String(255), nullable=True),
    Column("decision_label", String(32), nullable=True),
    Column("recommended_action", String(255), nullable=True),
    Column("summary", Text, nullable=False),
    Column("raw_payload_json", Text, nullable=False),
    Column("is_failure", Boolean, nullable=False),
    Column("is_denied", Boolean, nullable=False),
    Column("is_routine_noise", Boolean, nullable=False),
    UniqueConstraint("event_fingerprint", name="uq_audit_events_event_fingerprint"),
)

# Bulk-noise table: routine auth checks and produce/fetch traffic that
# dominate volume (~83% of events) but never need full enrichment. No
# event_fingerprint, no UNIQUE constraint, two indexes — INSERT-only.
# Rebuildable from Kafka topics, so retention is short (7 days default).
audit_events_noise = Table(
    "audit_events_noise",
    metadata,
    # BigInteger on Postgres (BIGSERIAL); fall back to Integer on SQLite
    # because only INTEGER PRIMARY KEY aliases ROWID and gives autoincrement.
    Column(
        "id",
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    ),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    Column("actor", String(255), nullable=True),
    Column("action", String(255), nullable=True),
    Column("result", String(32), nullable=True),
    Column("resource_name", String(512), nullable=True),
    Column("source_ip", String(128), nullable=True),
    Column("environment_id", String(255), nullable=True),
    Column("cluster_id", String(255), nullable=True),
    Column("is_denied", Boolean, nullable=False, default=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

Index("idx_noise_timestamp", audit_events_noise.c.timestamp.desc())
Index("idx_noise_actor", audit_events_noise.c.actor)


resource_catalog = Table(
    "resource_catalog",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("resource_id", String(512), nullable=False),
    Column("resource_type", String(128), nullable=False),
    Column("resource_name", String(512), nullable=False),
    Column("display_name", String(768), nullable=True),
    Column("cluster_id", String(255), nullable=True),
    Column("cluster_name", String(255), nullable=True),
    Column("environment_id", String(255), nullable=True),
    Column("environment_name", String(255), nullable=True),
    Column("parent_resource", String(255), nullable=True),
    Column("resource_scope", Text, nullable=True),
    Column("resource_criticality", String(32), nullable=True),
    Column("blast_radius_hint", String(64), nullable=True),
    Column("production_hint", String(64), nullable=True),
    Column("source", String(64), nullable=True),
    Column("metadata_json", Text, nullable=True),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("resource_id", name="uq_resource_catalog_resource_id"),
)

Index("idx_audit_events_timestamp", audit_events.c.timestamp)
Index("idx_audit_events_resource_type", audit_events.c.resource_type)
Index("idx_audit_events_action_category", audit_events.c.action_category)
Index("idx_audit_events_result", audit_events.c.result)
Index("idx_audit_events_signal_type", audit_events.c.signal_type)
Index("idx_audit_events_timestamp_desc", audit_events.c.timestamp.desc())
Index("idx_audit_events_timestamp_signal_type", audit_events.c.timestamp.desc(), audit_events.c.signal_type)
Index("idx_audit_events_timestamp_impact_type", audit_events.c.timestamp.desc(), audit_events.c.impact_type)
Index("idx_audit_events_action_category_time", audit_events.c.action_category, audit_events.c.timestamp.desc())
Index("idx_audit_events_result_time", audit_events.c.result, audit_events.c.timestamp.desc())
Index("idx_resource_catalog_resource_type", resource_catalog.c.resource_type)
Index("idx_resource_catalog_resource_name", resource_catalog.c.resource_name)
Index("idx_resource_catalog_cluster_id", resource_catalog.c.cluster_id)
Index("idx_resource_catalog_environment_id", resource_catalog.c.environment_id)
Index("idx_resource_catalog_last_seen_at", resource_catalog.c.last_seen_at)


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
        self._ensure_columns()
        self._ensure_indexes()
        self.timescaledb_enabled = self._detect_and_enable_timescaledb()

    def _detect_and_enable_timescaledb(self) -> bool:
        """If TimescaleDB is installed, convert audit_events and
        audit_events_noise to hypertables and add a compression policy.
        Otherwise log "not detected" and continue with regular tables —
        zero behavior change.

        Hypertables transparently partition by ``timestamp`` (1-day
        chunks by default), which keeps INSERT cost flat as the table
        grows and lets the retention sweep drop chunks instead of
        DELETE-ing rows."""
        if self.mode != "postgres":
            logger.info("TimescaleDB skipped — not running on Postgres")
            return False
        try:
            with self.engine.connect() as conn:
                row = conn.execute(text(
                    "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'"
                )).fetchone()
        except Exception as exc:
            logger.debug("TimescaleDB detection probe failed: %s", exc)
            return False
        if not row:
            logger.info("TimescaleDB not detected — using standard tables")
            return False
        version = row[0]
        logger.info("TimescaleDB %s detected — converting tables to hypertables", version)
        try:
            with self.engine.begin() as conn:
                # create_hypertable + add_compression_policy are both
                # idempotent via if_not_exists=>TRUE; safe to call on
                # every startup. migrate_data => true allows converting
                # existing tables that already have rows.
                for table_name in ("audit_events", "audit_events_noise"):
                    conn.execute(text(
                        f"SELECT create_hypertable('{table_name}', 'timestamp', "
                        "if_not_exists => TRUE, migrate_data => TRUE)"
                    ))
                    try:
                        conn.execute(text(
                            f"ALTER TABLE {table_name} SET ("
                            "timescaledb.compress, timescaledb.compress_orderby = 'timestamp DESC')"
                        ))
                    except Exception as exc:
                        # Older Timescale versions or repeat application.
                        logger.debug("compress ALTER failed on %s: %s", table_name, exc)
                    conn.execute(text(
                        f"SELECT add_compression_policy('{table_name}', "
                        "INTERVAL '1 day', if_not_exists => TRUE)"
                    ))
            return True
        except Exception as exc:
            logger.warning(
                "TimescaleDB hypertable conversion failed (continuing with standard tables): %s",
                exc,
            )
            return False

    @property
    def mode(self) -> str:
        return "postgres" if self.database_url.startswith("postgresql") else "sqlite"

    def _ensure_columns(self) -> None:
        inspector = inspect(self.engine)
        if "audit_events" not in inspector.get_table_names():
            return
        existing = {column["name"] for column in inspector.get_columns("audit_events")}
        with self.engine.begin() as conn:
            for name, type_sql in AUDIT_EVENT_COLUMNS.items():
                if name in existing:
                    continue
                if self.mode == "postgres":
                    conn.execute(text(f"ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS {name} {type_sql}"))
                else:
                    conn.execute(text(f"ALTER TABLE audit_events ADD COLUMN {name} {type_sql}"))

    def _ensure_indexes(self) -> None:
        if "audit_events" not in metadata.tables:
            return
        table = metadata.tables["audit_events"]
        for index in table.indexes:
            index.create(bind=self.engine, checkfirst=True)

    def _row(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_event(payload)
        return {
            "event_fingerprint": event_fingerprint(payload),
            "timestamp": parse_event_timestamp(payload),
            "raw_payload_json": json.dumps(payload, sort_keys=True, default=str),
            **normalized,
        }

    def write_batch(self, payloads: list[dict[str, Any]], *, defer_catalog: bool = False) -> DbWriteResult:
        """Insert a batch of audit events.

        If ``defer_catalog`` is True the catalog upsert is skipped and the
        prepared catalog rows are returned on the result via
        ``deferred_catalog_rows`` so the caller can queue them for a
        background ``upsert_catalog`` call. This keeps ``write_batch``'s hot
        path — building rows + the audit_events INSERT — independent of the
        catalog upsert latency.
        """
        normalize_started = time.perf_counter()
        rows = [self._row(payload) for payload in payloads]
        resource_rows = []
        for payload, row in zip(payloads, rows):
            try:
                record = build_resource_catalog_entry(payload, seen_at=row["timestamp"])
            except Exception as exc:  # pragma: no cover - best-effort enrichment
                logger.debug("resource catalog row build failed: %s", exc)
                continue
            if record["resource_type"] == "unknown" and record["resource_name"] in {"", "-"}:
                continue
            resource_rows.append(record)
        normalize_ms = (time.perf_counter() - normalize_started) * 1000
        if not rows:
            return DbWriteResult(attempted=0, inserted=0, elapsed_ms=0.0, normalize_ms=normalize_ms)
        started = time.perf_counter()
        pg_insert_started = time.perf_counter()
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
        pg_insert_ms = (time.perf_counter() - pg_insert_started) * 1000

        catalog_upsert_ms = 0.0
        deferred_catalog_rows = None
        if defer_catalog:
            deferred_catalog_rows = resource_rows or []
        elif resource_rows:
            catalog_upsert_started = time.perf_counter()
            try:
                self._upsert_catalog_rows(resource_rows)
            except Exception as exc:  # pragma: no cover - best-effort enrichment
                logger.debug("resource catalog write failed: %s", exc)
            catalog_upsert_ms = (time.perf_counter() - catalog_upsert_started) * 1000

        return DbWriteResult(
            attempted=len(rows),
            inserted=inserted,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            normalize_ms=normalize_ms,
            pg_insert_ms=pg_insert_ms,
            catalog_upsert_ms=catalog_upsert_ms,
            deferred_catalog_rows=deferred_catalog_rows,
        )

    def write_noise_batch(self, payloads: list[dict[str, Any]]) -> DbWriteResult:
        """Bulk-noise INSERT path. Skips event_fingerprint, ON CONFLICT,
        and full normalize_event(). Targets the audit_events_noise table
        which has 2 indexes only — INSERT cost is dominated by the wire
        round-trip, not the index updates.
        """
        normalize_started = time.perf_counter()
        rows: list[dict[str, Any]] = []
        for payload in payloads:
            try:
                normalized = minimal_normalize(payload)
            except Exception as exc:  # pragma: no cover - best-effort minimal path
                logger.debug("minimal_normalize failed: %s", exc)
                continue
            # minimal_normalize returns exactly the audit_events_noise
            # column set; pass it straight through.
            rows.append({
                "timestamp": normalized["timestamp"],
                "actor": normalized["actor"],
                "action": normalized["action"],
                "result": normalized["result"],
                "resource_name": normalized["resource_name"],
                "source_ip": normalized["source_ip"],
                "environment_id": normalized["environment_id"],
                "cluster_id": normalized["cluster_id"],
                "is_denied": normalized["is_denied"],
            })
        normalize_ms = (time.perf_counter() - normalize_started) * 1000
        if not rows:
            return DbWriteResult(attempted=0, inserted=0, elapsed_ms=0.0, normalize_ms=normalize_ms)
        started = time.perf_counter()
        pg_insert_started = time.perf_counter()
        with self.engine.begin() as conn:
            result = conn.execute(audit_events_noise.insert(), rows)
            inserted = int(result.rowcount or 0)
            if inserted < 0:
                # Some drivers return -1 for executemany without RETURNING.
                inserted = len(rows)
        pg_insert_ms = (time.perf_counter() - pg_insert_started) * 1000
        return DbWriteResult(
            attempted=len(rows),
            inserted=inserted,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            normalize_ms=normalize_ms,
            pg_insert_ms=pg_insert_ms,
            catalog_upsert_ms=0.0,
        )

    def cleanup_noise_retention(self, *, retention_days: int | None = None) -> int:
        """Delete noise rows older than ``retention_days`` (default: same
        as audit_events). Called from the existing retention sweep."""
        days = max(1, int(retention_days or self.retention_days))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with self.engine.begin() as conn:
            result = conn.execute(
                delete(audit_events_noise).where(audit_events_noise.c.timestamp < cutoff)
            )
            return int(result.rowcount or 0)

    def upsert_catalog(self, resource_rows: list[dict[str, Any]]) -> int:
        """Upsert prepared resource_catalog rows. Used by the async catalog
        writer thread so the hot audit_events INSERT path doesn't pay for it.
        Returns the number of rows submitted."""
        if not resource_rows:
            return 0
        self._upsert_catalog_rows(resource_rows)
        return len(resource_rows)

    @staticmethod
    def _dedupe_catalog_rows(resource_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collapse duplicate resource_id rows down to one entry per id.

        Postgres's ``ON CONFLICT DO UPDATE`` cannot affect the same target
        row twice in a single statement (CardinalityViolation). Audit
        batches frequently contain many events for the same resource
        (e.g. dozens of authz checks against the same topic in the same
        second), all of which produce the same resource_id. We keep the
        last entry by ``last_seen_at`` so the recency update in the
        upsert reflects the latest event in the batch.
        """
        if not resource_rows:
            return resource_rows
        deduped: dict[Any, dict[str, Any]] = {}
        for row in resource_rows:
            key = row.get("resource_id")
            if key is None:
                # Drop rows missing the conflict key — they would fail
                # the constraint anyway.
                continue
            existing = deduped.get(key)
            if existing is None:
                deduped[key] = row
                continue
            # Compare last_seen_at; keep the row with the more recent
            # timestamp. Datetime objects compare directly; strings
            # compare lexicographically (ISO-8601 keeps that monotonic).
            try:
                if row.get("last_seen_at") and (
                    not existing.get("last_seen_at")
                    or row["last_seen_at"] >= existing["last_seen_at"]
                ):
                    deduped[key] = row
            except TypeError:
                # Mixed datetime/str shapes — fall back to "later wins"
                # in iteration order, which is also the upsert's default.
                deduped[key] = row
        return list(deduped.values())

    def _upsert_catalog_rows(self, resource_rows: list[dict[str, Any]]) -> None:
        resource_rows = self._dedupe_catalog_rows(resource_rows)
        if not resource_rows:
            return
        with self.engine.begin() as conn:
            if self.mode == "postgres":
                stmt = postgres_insert(resource_catalog).values(resource_rows)
                excluded = stmt.excluded
                resource_statement = (
                    stmt
                    .on_conflict_do_update(
                        index_elements=["resource_id"],
                        set_={
                            "resource_type": func.coalesce(func.nullif(excluded.resource_type, "unknown"), resource_catalog.c.resource_type),
                            "resource_name": func.coalesce(func.nullif(excluded.resource_name, "-"), resource_catalog.c.resource_name),
                            "display_name": func.coalesce(func.nullif(excluded.display_name, "Unknown"), resource_catalog.c.display_name),
                            "cluster_id": func.coalesce(excluded.cluster_id, resource_catalog.c.cluster_id),
                            "cluster_name": func.coalesce(func.nullif(excluded.cluster_name, "Unknown"), resource_catalog.c.cluster_name),
                            "environment_id": func.coalesce(excluded.environment_id, resource_catalog.c.environment_id),
                            "environment_name": func.coalesce(func.nullif(excluded.environment_name, "Unknown"), resource_catalog.c.environment_name),
                            "parent_resource": func.coalesce(func.nullif(excluded.parent_resource, "unknown"), resource_catalog.c.parent_resource),
                            "resource_scope": func.coalesce(func.nullif(excluded.resource_scope, "unknown"), resource_catalog.c.resource_scope),
                            "resource_criticality": func.coalesce(func.nullif(excluded.resource_criticality, "unknown"), resource_catalog.c.resource_criticality),
                            "blast_radius_hint": func.coalesce(func.nullif(excluded.blast_radius_hint, "unknown"), resource_catalog.c.blast_radius_hint),
                            "production_hint": func.coalesce(func.nullif(excluded.production_hint, "unknown"), resource_catalog.c.production_hint),
                            "source": func.coalesce(func.nullif(excluded.source, "fallback"), resource_catalog.c.source),
                            "metadata_json": excluded.metadata_json,
                            "last_seen_at": excluded.last_seen_at,
                        },
                    )
                )
            else:
                stmt = sqlite_insert(resource_catalog).values(resource_rows)
                excluded = stmt.excluded
                resource_statement = (
                    stmt
                    .on_conflict_do_update(
                        index_elements=["resource_id"],
                        set_={
                            "resource_type": func.coalesce(func.nullif(excluded.resource_type, "unknown"), resource_catalog.c.resource_type),
                            "resource_name": func.coalesce(func.nullif(excluded.resource_name, "-"), resource_catalog.c.resource_name),
                            "display_name": func.coalesce(func.nullif(excluded.display_name, "Unknown"), resource_catalog.c.display_name),
                            "cluster_id": func.coalesce(excluded.cluster_id, resource_catalog.c.cluster_id),
                            "cluster_name": func.coalesce(func.nullif(excluded.cluster_name, "Unknown"), resource_catalog.c.cluster_name),
                            "environment_id": func.coalesce(excluded.environment_id, resource_catalog.c.environment_id),
                            "environment_name": func.coalesce(func.nullif(excluded.environment_name, "Unknown"), resource_catalog.c.environment_name),
                            "parent_resource": func.coalesce(func.nullif(excluded.parent_resource, "unknown"), resource_catalog.c.parent_resource),
                            "resource_scope": func.coalesce(func.nullif(excluded.resource_scope, "unknown"), resource_catalog.c.resource_scope),
                            "resource_criticality": func.coalesce(func.nullif(excluded.resource_criticality, "unknown"), resource_catalog.c.resource_criticality),
                            "blast_radius_hint": func.coalesce(func.nullif(excluded.blast_radius_hint, "unknown"), resource_catalog.c.blast_radius_hint),
                            "production_hint": func.coalesce(func.nullif(excluded.production_hint, "unknown"), resource_catalog.c.production_hint),
                            "source": func.coalesce(func.nullif(excluded.source, "fallback"), resource_catalog.c.source),
                            "metadata_json": excluded.metadata_json,
                            "last_seen_at": excluded.last_seen_at,
                        },
                    )
                )
            conn.execute(resource_statement)

    def cleanup_retention(self, *, dry_run: bool = False, retention_days: int | None = None) -> dict[str, Any]:
        days = max(1, int(retention_days or self.retention_days))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with self.engine.begin() as conn:
            count = int(conn.execute(select(func.count()).select_from(audit_events).where(audit_events.c.timestamp < cutoff)).scalar() or 0)
            if not dry_run and count:
                conn.execute(delete(audit_events).where(audit_events.c.timestamp < cutoff))
            # The noise table follows the same retention as audit_events.
            # Best-effort: any deletion error is logged but doesn't fail
            # the primary cleanup.
            try:
                noise_deleted = int(
                    conn.execute(delete(audit_events_noise).where(audit_events_noise.c.timestamp < cutoff)).rowcount or 0
                )
                if noise_deleted:
                    logger.info("Noise retention cleanup: deleted %d rows older than %s", noise_deleted, cutoff.isoformat())
            except Exception as exc:  # pragma: no cover - best-effort
                logger.warning("Noise retention cleanup failed: %s", exc)
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
