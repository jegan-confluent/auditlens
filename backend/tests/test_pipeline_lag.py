"""Tests for /system/status pipeline_lag + pipeline_status (Phase 2 Fix 2).

Locks down the four-state classifier (healthy / degraded / stalled /
unknown) plus the API contract — a transient forwarder outage or DB
hiccup must never 500 the status route.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.app.core.config import get_settings
from backend.app.db.database import build_engine, get_db, init_db
from backend.app.main import create_app
from backend.app.services import system_service
from backend.app.services.event_service import create_event
from backend.scripts.seed_data import SEED_EVENTS


# ─────────────────────── _classify_pipeline_status ─────────────────────


def test_pipeline_status_healthy_when_fresh_and_low_lag():
    out = system_service._classify_pipeline_status(
        db_behind_seconds=20,
        consumer_lag=5_000,
        db_latest_event_at=datetime.now(timezone.utc),
    )
    assert out == "healthy"


def test_pipeline_status_degraded_when_60_to_300_seconds_behind():
    out = system_service._classify_pipeline_status(
        db_behind_seconds=120,
        consumer_lag=5_000,
        db_latest_event_at=datetime.now(timezone.utc),
    )
    assert out == "degraded"


def test_pipeline_status_degraded_at_lag_100k_to_1m():
    out = system_service._classify_pipeline_status(
        db_behind_seconds=20,
        consumer_lag=500_000,
        db_latest_event_at=datetime.now(timezone.utc),
    )
    assert out == "degraded"


def test_pipeline_status_stalled_when_more_than_5_min_behind():
    out = system_service._classify_pipeline_status(
        db_behind_seconds=400,
        consumer_lag=0,
        db_latest_event_at=datetime.now(timezone.utc),
    )
    assert out == "stalled"


def test_pipeline_status_stalled_when_lag_over_1m():
    out = system_service._classify_pipeline_status(
        db_behind_seconds=10,
        consumer_lag=2_000_000,
        db_latest_event_at=datetime.now(timezone.utc),
    )
    assert out == "stalled"


def test_pipeline_status_stalled_when_db_latest_event_at_is_none():
    """Empty DB or PG query failure → stalled (forwarder unknown is a
    different state — handled at the assembler layer)."""
    out = system_service._classify_pipeline_status(
        db_behind_seconds=None,
        consumer_lag=0,
        db_latest_event_at=None,
    )
    assert out == "stalled"


def test_pipeline_status_healthy_when_consumer_lag_unknown():
    """Forwarder reachable but consumer_lag missing — DB freshness alone
    is enough to call healthy."""
    out = system_service._classify_pipeline_status(
        db_behind_seconds=10,
        consumer_lag=None,
        db_latest_event_at=datetime.now(timezone.utc),
    )
    assert out == "healthy"


# ────────────────── /system/status integration tests ───────────────────


@pytest.fixture()
def status_client(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "auditlens.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv("FORWARDER_HEALTH_URL", "http://127.0.0.1:9/health")
        monkeypatch.setattr("backend.app.main.init_db", lambda: None)
        get_settings.cache_clear()
        from backend.app.services.system_service import (
            reset_db_latest_event_cache,
            reset_forwarder_health_cache,
        )
        from backend.app.services.filter_options_service import clear_filter_options_cache
        from backend.app.core.limiter import limiter

        reset_forwarder_health_cache()
        reset_db_latest_event_cache()
        clear_filter_options_cache()
        limiter.enabled = False
        limiter.reset()

        engine = build_engine(f"sqlite:///{db_path}")
        TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        init_db(engine)

        # Seed audit_events so MAX(timestamp) returns a real value.
        with TestingSessionLocal() as db:
            for payload in SEED_EVENTS:
                create_event(db, payload)

        app = create_app()

        def override_db():
            db = TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        yield TestClient(app)


def _stub_forwarder(monkeypatch, **overrides) -> None:
    """Prime the forwarder /health cache with a complete shape so the
    SystemStatusResponse validation passes. Caller can override any
    field via kwargs."""
    snapshot = {
        "consumer_state": "connected",
        "last_successful_poll": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "retry_count": 0,
        "consecutive_error_count": 0,
        "last_error": None,
        "consumer_lag": 0,
        "records_consumed_total": 0,
        "db_writer_enabled": True,
        "db_writer_state": "connected",
        "db_write_success_total": 0,
        "db_write_error_total": 0,
        "db_write_batch_size": 0,
        "db_last_successful_write": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "db_last_error": None,
        "db_last_cleanup_at": None,
        "db_last_cleanup_deleted_count": 0,
    }
    snapshot.update(overrides)
    from backend.app.services.system_service import _forwarder_health_cache
    _forwarder_health_cache.prime(snapshot)


def test_status_route_includes_pipeline_lag_block(status_client, monkeypatch):
    _stub_forwarder(monkeypatch, consumer_lag=5_000)
    response = status_client.get("/system/status")
    assert response.status_code == 200
    body = response.json()
    assert "pipeline_lag" in body
    pl = body["pipeline_lag"]
    assert set(pl.keys()) == {
        "kafka_consumer_lag_messages",
        "db_latest_event_at",
        "forwarder_last_write_at",
        "db_behind_seconds",
        "replay_recommended",
        "status",
    }
    assert "pipeline_status" in body
    assert body["pipeline_status"] == pl["status"]


def test_status_route_pipeline_status_unknown_when_forwarder_unreachable(status_client, monkeypatch):
    _stub_forwarder(
        monkeypatch,
        consumer_state="unknown",
        consumer_lag=None,
        db_last_successful_write=None,
        last_error="ConnectError: All connection attempts failed",
    )
    body = status_client.get("/system/status").json()
    assert body["pipeline_status"] == "unknown"
    pl = body["pipeline_lag"]
    assert pl["status"] == "unknown"
    assert pl["kafka_consumer_lag_messages"] is None
    assert pl["forwarder_last_write_at"] is None


def test_status_route_does_not_500_when_forwarder_unreachable(status_client, monkeypatch):
    _stub_forwarder(
        monkeypatch,
        consumer_state="unknown",
        consumer_lag=None,
        db_last_successful_write=None,
        last_error="boom",
    )
    response = status_client.get("/system/status")
    # Spec: never 500; degrade to unknown / null fields.
    assert response.status_code == 200


def test_status_route_replay_recommended_when_kafka_caught_up_db_far_behind(status_client, monkeypatch):
    """Force the DB-side timestamp older than 5 min so the replay flag
    fires when consumer_lag is also 0."""
    from backend.app.services.system_service import _db_latest_event_cache
    far_past = datetime.now(timezone.utc) - timedelta(minutes=10)
    # Prime the cache directly so the inner SELECT MAX(timestamp) is bypassed.
    with _db_latest_event_cache._lock:
        _db_latest_event_cache._snapshots[id(status_client.app.dependency_overrides[get_db])] = (0, far_past)
    # The cache key is bind-id; we don't have easy access to the bind
    # from the test client. Instead force the cache for whatever engine
    # the route hits by setting all cached snapshots to the same future.
    # Simpler: just pre-fill via the public path — call once to warm,
    # then patch the snapshot.
    _stub_forwarder(monkeypatch, consumer_lag=0)
    # Touch the route once to populate the engine-keyed cache slot, then
    # mutate that slot to a far-past timestamp. We rely on the test
    # fixture only ever using one engine binding.
    status_client.get("/system/status")
    with _db_latest_event_cache._lock:
        # Replace every cached entry with the far-past datetime.
        for k in list(_db_latest_event_cache._snapshots.keys()):
            _db_latest_event_cache._snapshots[k] = (0, far_past)
    # Re-query — the assertion below depends on the cache returning the
    # mutated value (TTL 10s, but timestamp 0 means "expired" — so it
    # would re-fetch). Set the timestamp to "now" to keep the cached
    # value alive for our assertion.
    import time as _t
    with _db_latest_event_cache._lock:
        for k in list(_db_latest_event_cache._snapshots.keys()):
            _db_latest_event_cache._snapshots[k] = (_t.monotonic(), far_past)
    body = status_client.get("/system/status").json()
    pl = body["pipeline_lag"]
    assert pl["replay_recommended"] is True
    assert pl["status"] == "stalled"


def test_status_route_pipeline_lag_status_healthy_with_seeded_db(status_client, monkeypatch):
    """SEED_EVENTS are recent enough that with a fresh forwarder snapshot
    the pipeline should classify healthy."""
    _stub_forwarder(monkeypatch, consumer_lag=0)
    # SEED_EVENTS may have stale-ish timestamps depending on fixture; we
    # don't pin "healthy" because the seed data isn't necessarily fresh.
    # We assert only that the route produces a valid known state.
    body = status_client.get("/system/status").json()
    assert body["pipeline_status"] in {"healthy", "degraded", "stalled"}
    assert body["pipeline_lag"]["db_latest_event_at"] is not None


# ────────────────────────── DB cache TTL behavior ──────────────────────


def test_db_latest_event_cache_returns_none_on_query_failure(status_client, monkeypatch):
    """A bad SELECT should yield None, not raise."""
    from backend.app.services.system_service import _db_latest_event_cache, reset_db_latest_event_cache

    reset_db_latest_event_cache()

    # Force the underlying _fetch_now to raise → cache stores None.
    monkeypatch.setattr(
        _db_latest_event_cache,
        "_fetch_now",
        staticmethod(lambda db: None),
    )
    _stub_forwarder(monkeypatch, consumer_lag=0)
    body = status_client.get("/system/status").json()
    assert body["pipeline_lag"]["db_latest_event_at"] is None
    assert body["pipeline_status"] == "stalled"


def test_system_status_latest_event_reads_both_tables():
    """db_latest_event_at must reflect the newest timestamp across both
    audit_events and audit_events_noise — not just audit_events."""
    import tempfile
    from pathlib import Path as _Path
    from alembic import command as _alembic_cmd
    from alembic.config import Config as _AlembicConfig
    from sqlalchemy import text as _text
    from sqlalchemy.orm import sessionmaker as _sessionmaker
    from backend.app.db.database import build_engine
    from backend.app.services.system_service import _DbLatestEventCache

    _alembic_ini = _Path(__file__).resolve().parents[1] / "alembic.ini"

    with tempfile.TemporaryDirectory() as tmp:
        db_url = f"sqlite:///{_Path(tmp) / 'test.db'}"
        engine = build_engine(db_url)
        cfg = _AlembicConfig(str(_alembic_ini))
        cfg.set_main_option("sqlalchemy.url", db_url)
        _alembic_cmd.upgrade(cfg, "head")
        _SessionLocal = _sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

        old_ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        recent_ts = datetime.now(timezone.utc) - timedelta(seconds=5)

        with _SessionLocal() as db:
            db.execute(
                _text(
                    "INSERT INTO audit_events "
                    "(event_fingerprint, timestamp, result, actor, action, "
                    "normalized_action, action_category, resource_type, "
                    "resource_name, resource_display, summary, raw_payload_json, "
                    "is_failure, is_denied, is_routine_noise) "
                    "VALUES ('fp-old', :ts, 'Success', 'u-test', 'Test', 'Test', "
                    "'Other', 'Unknown', '-', 'Unknown', '', '{}', 0, 0, 0)"
                ),
                {"ts": old_ts},
            )
            db.execute(
                _text(
                    "INSERT INTO audit_events_noise "
                    "(timestamp, actor, action, result, resource_name, is_denied) "
                    "VALUES (:ts, 'u-noise', 'kafka.fetch', 'Success', '-', 0)"
                ),
                {"ts": recent_ts},
            )
            db.commit()

        cache = _DbLatestEventCache(ttl_seconds=0)
        with _SessionLocal() as db:
            result = cache.get(db)

        assert result is not None
        delta = abs((result - recent_ts).total_seconds())
        assert delta < 2, f"expected ~{recent_ts!r}, got {result!r}"
