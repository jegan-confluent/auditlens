"""Recurring-event pattern detector.

Detects (actor, action, resource) tuples that fire above THRESHOLD occurrences
within a WINDOW_SECONDS sliding window and records them in audit_event_patterns.

Thread-safe. The record() method is called from the processor thread and is
non-blocking — all DB writes are dispatched to a daemon background thread.
"""

import hashlib
import logging
import queue
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

logger = logging.getLogger("auditlens.pattern_detector")

_metadata = MetaData()

_patterns_table = Table(
    "audit_event_patterns",
    _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("pattern_key", String(512), nullable=False),
    Column("actor", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("resource_name", Text, nullable=True),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("occurrence_count", Integer, nullable=False, default=0),
    Column("window_count", Integer, nullable=False, default=0),
    Column("status", String(32), nullable=False, default="active"),
    Column("suppressed_until", DateTime(timezone=True), nullable=True),
    Column("suppressed_by", Text, nullable=True),
    Column("suppression_reason", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("pattern_key", name="uq_audit_event_patterns_pattern_key"),
)


def _pattern_key(actor: str, action: str, resource: str) -> str:
    return hashlib.sha256(
        f"{actor}:{action}:{resource}".encode()
    ).hexdigest()[:64]


class PatternDetector:
    """Detects recurring (actor, action, resource) patterns in the processor thread.

    Non-blocking: record() updates in-memory sliding-window counters and enqueues
    DB writes only when the threshold is crossed. A daemon thread drains the queue.
    """

    WINDOW_SECONDS = 600   # 10-minute sliding window
    THRESHOLD = 10         # > 10 occurrences → write pattern record
    SUPPRESSION_WINDOWS = 3  # reserved for future cooldown logic

    def __init__(self, database_url: str) -> None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self._engine = create_engine(
            database_url, future=True, pool_pre_ping=True, connect_args=connect_args
        )
        # Create table if not yet present (migration 0009 is the canonical path;
        # this is a safety net so the forwarder works before migrations run).
        try:
            _metadata.create_all(self._engine, checkfirst=True)
        except Exception as exc:
            logger.warning("pattern_detector: table create_all failed (non-fatal): %s", exc)

        self._counts: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue(maxsize=1000)
        self._thread = threading.Thread(
            target=self._writer_loop,
            daemon=True,
            name="pattern-detector",
        )
        self._thread.start()

    def record(self, event: dict) -> None:
        """Called for every non-noise event from the processor thread. Non-blocking."""
        actor = (
            event.get("actor")
            or event.get("principal")
            or event.get("principal_normalized")
            or ""
        )
        action = (
            event.get("action")
            or event.get("methodName")
            or ""
        )
        resource = (
            event.get("resource_name")
            or event.get("resourceName")
            or event.get("authzResourceName")
            or ""
        )
        if resource.startswith("crn://"):
            parts = resource.rstrip("/").split("/")
            last = parts[-1] if parts else ""
            resource = last.split("=")[-1] if "=" in last else last
        if not actor or not action:
            return

        key = _pattern_key(actor, action, resource)
        now = time.time()

        with self._lock:
            timestamps = self._counts.get(key, [])
            # Prune timestamps outside the current window
            timestamps = [t for t in timestamps if now - t < self.WINDOW_SECONDS]
            timestamps.append(now)
            self._counts[key] = timestamps
            count = len(timestamps)
            if not self._counts[key]:
                del self._counts[key]

        # occurrence_count tracks threshold-crossing events (windows where count >= THRESHOLD),
        # not total raw event count. A continuous burst increments this on each window crossing.
        # Only enqueue a DB write the moment we cross the threshold so the queue
        # stays sparse — one entry per detection, not one per event.
        if count == self.THRESHOLD + 1:
            try:
                self._queue.put_nowait({
                    "key": key,
                    "actor": actor,
                    "action": action,
                    "resource_name": resource,
                    "count": count,
                    "ts": now,
                })
            except queue.Full:
                pass  # Non-blocking; drop if the writer thread is behind

    def _writer_loop(self) -> None:
        """Background daemon thread — drains the queue into audit_event_patterns."""
        while True:
            try:
                item = self._queue.get(timeout=5.0)
            except queue.Empty:
                continue
            try:
                self._upsert_pattern(item)
            except Exception as exc:
                logger.warning("pattern_detector: upsert failed: %s", exc)

    def _upsert_pattern(self, item: dict) -> None:
        now = datetime.fromtimestamp(item["ts"], tz=timezone.utc)
        dialect = self._engine.dialect.name
        tbl = _patterns_table

        if dialect == "postgresql":
            stmt = pg_insert(tbl).values(
                pattern_key=item["key"],
                actor=item["actor"],
                action=item["action"],
                resource_name=item["resource_name"] or None,
                first_seen_at=now,
                last_seen_at=now,
                occurrence_count=item["count"],
                window_count=1,
                status="active",
                created_at=now,
                updated_at=now,
            ).on_conflict_do_update(
                index_elements=["pattern_key"],
                set_={
                    "last_seen_at": now,
                    "occurrence_count": tbl.c.occurrence_count + 1,
                    "window_count": tbl.c.window_count + 1,
                    "updated_at": now,
                },
            )
        else:
            stmt = sqlite_insert(tbl).values(
                pattern_key=item["key"],
                actor=item["actor"],
                action=item["action"],
                resource_name=item["resource_name"] or None,
                first_seen_at=now,
                last_seen_at=now,
                occurrence_count=item["count"],
                window_count=1,
                status="active",
                created_at=now,
                updated_at=now,
            ).on_conflict_do_update(
                index_elements=["pattern_key"],
                set_={
                    "last_seen_at": now,
                    "occurrence_count": tbl.c.occurrence_count + 1,
                    "window_count": tbl.c.window_count + 1,
                    "updated_at": now,
                },
            )

        with self._engine.begin() as conn:
            conn.execute(stmt)
