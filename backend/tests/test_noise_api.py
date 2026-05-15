"""API tests for the noise table query path.

Covers Fix 3:
  - GET /summary/methods (unified signal+noise method distribution)
  - GET /summary?include_noise=true (noise_summary block)
  - GET /events?show_noise=true (paginated noise rows + filter rejection)
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend.app.core.config import get_settings
from backend.app.db.database import build_engine, get_db, init_db
from backend.app.main import create_app
from backend.app.services import noise_service
from backend.app.services.event_service import create_event
from backend.scripts.seed_data import SEED_EVENTS


def _create_noise_table(engine) -> None:
    """Create audit_events_noise on the test engine. The application
    side runs Alembic 0007 in production; tests build it directly so
    each test starts on a known schema."""
    noise_service.audit_events_noise.metadata.create_all(engine, checkfirst=True)


def _seed_noise(engine, rows: list[dict]) -> None:
    """Insert noise rows directly via Core. Each `rows` entry needs
    timestamp / actor / action / result / is_denied at minimum."""
    with engine.begin() as conn:
        for row in rows:
            conn.execute(noise_service.audit_events_noise.insert(), row)


@pytest.fixture()
def noise_client(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "auditlens.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv("FORWARDER_HEALTH_URL", "http://127.0.0.1:9/health")
        monkeypatch.setenv("API_AUTH_ENABLED", "false")
        monkeypatch.setattr("backend.app.main.init_db", lambda: None)
        get_settings.cache_clear()
        from backend.app.services.system_service import reset_forwarder_health_cache
        from backend.app.services.filter_options_service import clear_filter_options_cache
        from backend.app.core.limiter import limiter

        reset_forwarder_health_cache()
        clear_filter_options_cache()
        noise_service.reset_noise_table_existence_cache()
        noise_service.clear_method_distribution_cache()
        limiter.enabled = False
        limiter.reset()

        engine = build_engine(f"sqlite:///{db_path}")
        TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        init_db(engine)
        _create_noise_table(engine)

        # Seed the audit_events table with the canonical fixture set so
        # /summary/methods has signal-side data to merge.
        with TestingSessionLocal() as db:
            for payload in SEED_EVENTS:
                create_event(db, payload)

        # Seed the noise table with three distinct methods at varying
        # volumes so /summary/methods, /summary?include_noise, and
        # /events?show_noise have something to return.
        now = datetime.now(timezone.utc)
        rows = []
        for i in range(50):
            rows.append({
                "timestamp": now - timedelta(seconds=i),
                "actor": "sa-fetcher",
                "action": "kafka.Fetch",
                "result": "Success",
                "resource_name": "orders",
                "source_ip": "10.0.0.1",
                "environment_id": "env-aaa",
                "cluster_id": "lkc-bbb",
                "is_denied": False,
            })
        for i in range(15):
            rows.append({
                "timestamp": now - timedelta(seconds=i),
                "actor": "sa-producer",
                "action": "kafka.Produce",
                "result": "Success",
                "resource_name": "events",
                "source_ip": "10.0.0.2",
                "environment_id": "env-aaa",
                "cluster_id": "lkc-bbb",
                "is_denied": False,
            })
        for i in range(7):
            rows.append({
                "timestamp": now - timedelta(seconds=i),
                "actor": "sa-rbac",
                "action": "mds.Authorize",
                "result": "Failure",
                "resource_name": "lkc-bbb",
                "source_ip": "10.0.0.3",
                "environment_id": "env-aaa",
                "cluster_id": "lkc-bbb",
                "is_denied": True,
            })
        _seed_noise(engine, rows)

        app = create_app()

        def override_db():
            db = TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        yield TestClient(app)


@pytest.fixture()
def noise_client_no_table(monkeypatch):
    """Variant fixture — skips the audit_events_noise create_all so we
    can verify graceful degradation when the migration hasn't been run."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "auditlens.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv("FORWARDER_HEALTH_URL", "http://127.0.0.1:9/health")
        monkeypatch.setenv("API_AUTH_ENABLED", "false")
        monkeypatch.setattr("backend.app.main.init_db", lambda: None)
        get_settings.cache_clear()
        from backend.app.services.system_service import reset_forwarder_health_cache
        from backend.app.services.filter_options_service import clear_filter_options_cache
        from backend.app.core.limiter import limiter

        reset_forwarder_health_cache()
        clear_filter_options_cache()
        noise_service.reset_noise_table_existence_cache()
        noise_service.clear_method_distribution_cache()
        limiter.enabled = False
        limiter.reset()

        engine = build_engine(f"sqlite:///{db_path}")
        TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        init_db(engine)
        # Intentionally skip _create_noise_table.

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


# ─────────────────────────── /summary/methods ──────────────────────────


def test_summary_methods_returns_unified_distribution(noise_client):
    response = noise_client.get("/summary/methods")
    assert response.status_code == 200
    body = response.json()
    assert "methods" in body
    assert "total_signal_events" in body
    assert "total_noise_events" in body
    assert "generated_at" in body
    # We seeded 50+15+7 = 72 noise events.
    assert body["total_noise_events"] == 72


def test_summary_methods_includes_noise_methods(noise_client):
    body = noise_client.get("/summary/methods").json()
    actions = {m["action"] for m in body["methods"]}
    assert "kafka.Fetch" in actions
    assert "kafka.Produce" in actions
    assert "mds.Authorize" in actions


def test_summary_methods_marks_noise_only_actions_as_noise(noise_client):
    body = noise_client.get("/summary/methods").json()
    by_action = {m["action"]: m for m in body["methods"]}
    fetch = by_action["kafka.Fetch"]
    assert fetch["signal_type"] == "noise"
    assert fetch["table"] == "noise"
    assert fetch["count"] == 50


def test_summary_methods_returns_empty_when_table_missing(noise_client_no_table):
    response = noise_client_no_table.get("/summary/methods")
    assert response.status_code == 200
    body = response.json()
    # Signal side still has SEED_EVENTS rows; noise side is empty.
    assert body["total_noise_events"] == 0
    actions = {m["action"] for m in body["methods"]}
    assert "kafka.Fetch" not in actions  # noise-only methods absent


def test_summary_methods_postgres_branch_applies_recent_sample(noise_client, monkeypatch):
    """When the dialect is Postgres, _query_signal_methods must aggregate
    over the most-recent METHODS_RECENT_SAMPLE rows (subquery + LIMIT)
    rather than the entire audit_events table — this is the fix that
    keeps the route from timing out at production scale.

    We don't have a Postgres in CI, but the SQL we emit is portable
    enough that we can flip _is_postgres to True and verify the
    subquery LIMIT actually bounds the output set.
    """
    from backend.app.services import noise_service
    # Force the Postgres branch.
    monkeypatch.setattr(noise_service, "_is_postgres", lambda db: True)
    # Tighten the recent-sample to a tiny number so we can prove the
    # window applies — the SEED_EVENTS fixture has more rows than this.
    monkeypatch.setattr(noise_service, "METHODS_RECENT_SAMPLE", 2)
    noise_service.clear_method_distribution_cache()

    body = noise_client.get("/summary/methods").json()
    # Sum of signal-side counts must be <= the recent-sample window.
    signal_count_total = sum(
        m["count"] for m in body["methods"] if m["table"] == "signal"
    )
    assert signal_count_total <= 2


def test_summary_methods_sqlite_branch_full_table_aggregation(noise_client):
    """SQLite path must keep returning the full-table aggregation —
    that's the contract the existing test fixtures rely on."""
    from backend.app.services import noise_service

    noise_service.clear_method_distribution_cache()
    body = noise_client.get("/summary/methods").json()
    # The SEED_EVENTS fixture seeds many distinct actions; with the
    # full-table query at least a couple should land in the signal
    # bucket. (Don't pin a specific count — fixtures evolve.)
    signal_actions = [m for m in body["methods"] if m["table"] == "signal"]
    assert len(signal_actions) >= 1, "SQLite branch returned no signal-side methods"


# ───────────────────── /summary?include_noise=true ─────────────────────


def test_summary_default_does_not_include_noise_summary(noise_client):
    body = noise_client.get("/summary").json()
    assert body.get("noise_summary") is None


def test_summary_include_noise_true_returns_block(noise_client):
    body = noise_client.get("/summary?include_noise=true").json()
    ns = body.get("noise_summary")
    assert ns is not None
    assert ns["total_noise_events"] == 72
    assert ns["noise_table_rows"] == 72
    assert ns["noise_retention_days"] == 3  # BUG-004 fix: NOISE_RETENTION_DAYS default (3), not EVENT_RETENTION_DAYS (7)


def test_summary_include_noise_true_top_methods_sorted_desc(noise_client):
    ns = noise_client.get("/summary?include_noise=true").json()["noise_summary"]
    counts = [entry["count"] for entry in ns["top_noise_methods"]]
    assert counts == sorted(counts, reverse=True)
    top = ns["top_noise_methods"][0]
    assert top["action"] == "kafka.Fetch"
    assert top["count"] == 50


def test_summary_include_noise_when_table_missing_returns_null(noise_client_no_table):
    body = noise_client_no_table.get("/summary?include_noise=true").json()
    assert body.get("noise_summary") is None


# ────────────────────── /events?show_noise=true ────────────────────────


def test_events_default_reads_signal_table(noise_client):
    body = noise_client.get("/events").json()
    # Default path: existing EventListResponse shape.
    assert "items" in body
    assert "scanned_events" in body  # only present on EventListResponse


def test_events_show_noise_returns_noise_response_shape(noise_client):
    body = noise_client.get("/events?show_noise=true&limit=10").json()
    assert body["source"] == "noise_table"
    assert body["limit"] == 10
    assert body["total"] == 72
    assert len(body["items"]) == 10


def test_events_show_noise_items_carry_constants(noise_client):
    body = noise_client.get("/events?show_noise=true&limit=5").json()
    for item in body["items"]:
        assert item["signal_type"] == "noise"
        assert item["signal_reason"] == "bulk_noise"
        assert item["source"] == "noise_table"
        assert "id" in item
        assert "timestamp" in item


def test_events_show_noise_actor_filter(noise_client):
    body = noise_client.get("/events?show_noise=true&actor=sa-producer").json()
    assert body["total"] == 15
    for item in body["items"]:
        assert item["actor"] == "sa-producer"


def test_events_show_noise_action_filter(noise_client):
    body = noise_client.get("/events?show_noise=true&action=mds.Authorize").json()
    assert body["total"] == 7
    for item in body["items"]:
        assert item["action"] == "mds.Authorize"
        assert item["is_denied"] is True


def test_events_show_noise_time_window_filter(noise_client):
    # Window of 1m at our seed time should still cover everything (we
    # inserted within seconds of "now"); window of 1m offset tests the
    # parser path. 1h is also accepted.
    body = noise_client.get("/events?show_noise=true&time_window=1h").json()
    assert body["total"] == 72


def test_events_show_noise_limit_capped_at_500(noise_client):
    response = noise_client.get("/events?show_noise=true&limit=999")
    # limit query param has le=500 in the route, so 999 fails validation.
    assert response.status_code == 422


def test_events_show_noise_rejects_signal_type_filter(noise_client):
    response = noise_client.get(
        "/events?show_noise=true&signal_type=noise"
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "signal_type" in detail
    assert "not supported" in detail.lower()


def test_events_show_noise_rejects_impact_type_filter(noise_client):
    response = noise_client.get(
        "/events?show_noise=true&impact_type=destructive"
    )
    assert response.status_code == 400
    assert "impact_type" in response.json()["detail"]


def test_events_show_noise_rejects_change_type_filter(noise_client):
    response = noise_client.get(
        "/events?show_noise=true&change_type=deleted"
    )
    assert response.status_code == 400


def test_events_show_noise_rejects_resource_filter(noise_client):
    response = noise_client.get("/events?show_noise=true&resource=orders")
    assert response.status_code == 400


def test_events_show_noise_when_table_missing_returns_empty(noise_client_no_table):
    body = noise_client_no_table.get("/events?show_noise=true").json()
    assert body["source"] == "noise_table"
    assert body["total"] == 0
    assert body["items"] == []


def test_events_show_noise_pagination(noise_client):
    page1 = noise_client.get("/events?show_noise=true&limit=20&offset=0").json()
    page2 = noise_client.get("/events?show_noise=true&limit=20&offset=20").json()
    page1_ids = {item["id"] for item in page1["items"]}
    page2_ids = {item["id"] for item in page2["items"]}
    assert page1_ids.isdisjoint(page2_ids)
    assert len(page1["items"]) == 20
    assert len(page2["items"]) == 20
