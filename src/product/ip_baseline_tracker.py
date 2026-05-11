"""Actor-IP baseline tracker.

Records every (actor, source_ip) pair seen in audit events and persists them
to actor_ip_baseline. Used to detect new/anomalous IPs for a given actor.

Thread-safe. record() is called from the processor thread and is non-blocking
— all DB writes are dispatched to a daemon background thread.
"""

import ipaddress
import logging
import queue
import threading
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

logger = logging.getLogger("auditlens.ip_baseline_tracker")

_metadata = MetaData()

_ip_baseline_table = Table(
    "actor_ip_baseline",
    _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("actor", String(255), nullable=False),
    Column("source_ip", String(128), nullable=False),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("occurrence_count", Integer, nullable=False, default=1),
    Column("cloud_provider", String(64), nullable=True),
    Column("region", String(128), nullable=True),
    Column("is_trusted", Boolean, nullable=False, default=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("actor", "source_ip", name="uq_actor_ip"),
)

# Static CIDR blocks for cloud provider detection (no external APIs).
_CLOUD_CIDRS: list[tuple[str, str, str]] = [
    # (cidr, provider, region_hint)
    ("34.64.0.0/11", "gcp", "us"),
    ("35.190.0.0/17", "gcp", "us"),
    ("34.80.0.0/12", "gcp", "asia"),
    ("34.96.0.0/12", "gcp", "global"),
    ("35.186.0.0/17", "gcp", "us"),
    ("52.0.0.0/8", "aws", "us-east"),
    ("54.0.0.0/8", "aws", "global"),
    ("34.0.0.0/8", "aws", "global"),
    ("3.0.0.0/8", "aws", "global"),
    ("18.0.0.0/8", "aws", "global"),
    ("13.0.0.0/8", "aws", "us"),
    ("40.0.0.0/8", "azure", "global"),
    ("20.0.0.0/8", "azure", "global"),
    ("52.224.0.0/11", "azure", "us"),
    ("134.238.0.0/16", "confluent", "us"),   # Confluent Cloud management plane
]

_compiled_cidrs: list[tuple[ipaddress.IPv4Network, str, str]] = []


def _init_cidrs() -> None:
    global _compiled_cidrs
    if _compiled_cidrs:
        return
    result = []
    for cidr, provider, region in _CLOUD_CIDRS:
        try:
            result.append((ipaddress.IPv4Network(cidr, strict=False), provider, region))
        except ValueError:
            pass
    _compiled_cidrs = result


def detect_cloud_provider(ip: str) -> tuple[str | None, str | None]:
    """Return (cloud_provider, region) for ip, or (None, None) if unknown."""
    _init_cidrs()
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError:
        return None, None
    for network, provider, region in _compiled_cidrs:
        if addr in network:
            return provider, region
    return None, None


def _is_private_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


class IpBaselineTracker:
    """Tracks (actor, source_ip) pairs and detects new IPs per actor.

    Non-blocking: record() updates an in-memory set and enqueues DB upserts.
    A daemon thread drains the queue into actor_ip_baseline.
    """

    def __init__(self, database_url: str) -> None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self._engine = create_engine(
            database_url, future=True, pool_pre_ping=True, connect_args=connect_args
        )
        try:
            _metadata.create_all(self._engine, checkfirst=True)
        except Exception as exc:
            logger.warning("ip_baseline_tracker: table create_all failed (non-fatal): %s", exc)

        # In-memory set of known (actor, ip) pairs — seeded from DB on startup.
        self._seen: set[tuple[str, str]] = set()
        self._lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue(maxsize=5000)
        self._seeded = False

        self._thread = threading.Thread(
            target=self._writer_loop,
            daemon=True,
            name="ip-baseline-tracker",
        )
        self._thread.start()
        self._seed_from_db()

    def _seed_from_db(self) -> None:
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    _ip_baseline_table.select().with_only_columns(
                        _ip_baseline_table.c.actor,
                        _ip_baseline_table.c.source_ip,
                    )
                )
                with self._lock:
                    for row in rows:
                        self._seen.add((row.actor, row.source_ip))
                    self._seeded = True
        except Exception as exc:
            logger.warning("ip_baseline_tracker: seed_from_db failed: %s", exc)

    def record(self, actor: str, source_ip: str) -> bool:
        """Record an (actor, source_ip) observation.

        Returns True if this is the first time this IP has been seen for
        this actor (i.e. it is a new IP). Returns False otherwise.
        """
        if not actor or not source_ip:
            return False
        key = (actor, source_ip)
        with self._lock:
            is_new = key not in self._seen
            self._seen.add(key)
        provider, region = detect_cloud_provider(source_ip)
        try:
            self._queue.put_nowait({
                "actor": actor,
                "source_ip": source_ip,
                "is_new": is_new,
                "cloud_provider": provider,
                "region": region,
                "ts": datetime.now(timezone.utc),
            })
        except queue.Full:
            pass
        return is_new

    def is_new_ip(self, actor: str, source_ip: str) -> bool:
        """Return True if source_ip has not been seen for actor before."""
        if not actor or not source_ip:
            return False
        with self._lock:
            return (actor, source_ip) not in self._seen

    def _writer_loop(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=5.0)
            except queue.Empty:
                continue
            try:
                self._upsert(item)
            except Exception as exc:
                logger.warning("ip_baseline_tracker: upsert failed: %s", exc)

    def _upsert(self, item: dict) -> None:
        now = item["ts"]
        dialect = self._engine.dialect.name
        tbl = _ip_baseline_table
        values = {
            "actor": item["actor"],
            "source_ip": item["source_ip"],
            "first_seen_at": now,
            "last_seen_at": now,
            "occurrence_count": 1,
            "cloud_provider": item.get("cloud_provider"),
            "region": item.get("region"),
            "is_trusted": False,
            "created_at": now,
        }
        if dialect == "postgresql":
            stmt = pg_insert(tbl).values(**values)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_actor_ip",
                set_={
                    "last_seen_at": stmt.excluded.last_seen_at,
                    "occurrence_count": tbl.c.occurrence_count + 1,
                    "cloud_provider": stmt.excluded.cloud_provider,
                    "region": stmt.excluded.region,
                },
            )
        else:
            stmt = sqlite_insert(tbl).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["actor", "source_ip"],
                set_={
                    "last_seen_at": stmt.excluded.last_seen_at,
                    "occurrence_count": tbl.c.occurrence_count + 1,
                    "cloud_provider": stmt.excluded.cloud_provider,
                    "region": stmt.excluded.region,
                },
            )
        with self._engine.begin() as conn:
            conn.execute(stmt)
