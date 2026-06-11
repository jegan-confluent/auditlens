"""API tests for /auth/analytics (Issue 7 — Pydantic response_model)."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.app.api.routes.auth_analytics import AuthAnalyticsResponse
from backend.app.core.config import get_settings
from backend.app.db.database import build_engine, get_db, init_db
from backend.app.main import create_app
from backend.app.services import noise_service


def _create_noise_table(engine) -> None:
    noise_service.audit_events_noise.metadata.create_all(engine, checkfirst=True)


@pytest.fixture()
def auth_client(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "auditlens.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv("FORWARDER_HEALTH_URL", "http://127.0.0.1:9/health")
        monkeypatch.setenv("API_AUTH_ENABLED", "false")
        monkeypatch.setattr("backend.app.main.init_db", lambda: None)
        get_settings.cache_clear()

        from backend.app.core.limiter import limiter
        from backend.app.services.system_service import reset_forwarder_health_cache

        reset_forwarder_health_cache()
        noise_service.reset_noise_table_existence_cache()
        limiter.enabled = False
        limiter.reset()

        engine = build_engine(f"sqlite:///{db_path}")
        TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        init_db(engine)
        _create_noise_table(engine)

        now = datetime.now(timezone.utc)
        rows = []
        # 30 auths from sa-fetcher over the last 5 minutes
        for i in range(30):
            rows.append({
                "timestamp": now - timedelta(minutes=i),
                "actor": "sa-fetcher",
                "action": "kafka.Authentication",
                "result": "Success",
                "resource_name": None,
                "source_ip": "10.0.0.1",
                "environment_id": "env-aaa",
                "cluster_id": "lkc-bbb",
                "is_denied": False,
            })
        # 5 from sa-other
        for i in range(5):
            rows.append({
                "timestamp": now - timedelta(minutes=i),
                "actor": "sa-other",
                "action": "kafka.Authentication",
                "result": "Success",
                "resource_name": None,
                "source_ip": "10.0.0.2",
                "environment_id": "env-aaa",
                "cluster_id": "lkc-bbb",
                "is_denied": False,
            })
        # 10 non-Authentication noise events that must NOT count
        for i in range(10):
            rows.append({
                "timestamp": now - timedelta(minutes=i),
                "actor": "sa-fetcher",
                "action": "kafka.Fetch",
                "result": "Success",
                "resource_name": "orders",
                "source_ip": "10.0.0.1",
                "environment_id": "env-aaa",
                "cluster_id": "lkc-bbb",
                "is_denied": False,
            })
        with engine.begin() as conn:
            for row in rows:
                conn.execute(noise_service.audit_events_noise.insert(), row)

        app = create_app()

        def override_db():
            db = TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        yield TestClient(app)


def test_auth_analytics_response_matches_pydantic_model(auth_client):
    """The route now has response_model=AuthAnalyticsResponse — validate
    that FastAPI's serialization keeps the documented shape."""
    response = auth_client.get("/auth/analytics?time_window=1d")
    assert response.status_code == 200, response.text
    body = response.json()
    # Pydantic must accept this body as the declared response_model.
    parsed = AuthAnalyticsResponse.model_validate(body)
    assert parsed.total_auth_events == 35  # 30 + 5; kafka.Fetch excluded
    assert parsed.time_window == "1d"
    assert len(parsed.top_actors) == 2
    # Ordered DESC by auth_count.
    assert parsed.top_actors[0].actor == "sa-fetcher"
    assert parsed.top_actors[0].auth_count == 30
    assert parsed.top_actors[1].actor == "sa-other"
    assert parsed.top_actors[1].auth_count == 5
    # SQLite test path → cross-table display lookup is skipped, so
    # actor_display_name falls back to raw actor via actor_mappings.yml.
    # The Pydantic shape should still be valid (str | None).
    assert isinstance(parsed.top_actors[0].actor_display_name, str)
    assert parsed.concentration.top3_pct == round(100.0 * 35 / 35, 2)


def test_auth_analytics_rejects_bad_time_window(auth_client):
    """time_window pattern is enforced at the route boundary."""
    response = auth_client.get("/auth/analytics?time_window=99d")
    assert response.status_code == 422


def test_auth_analytics_pct_and_trend_keys_present(auth_client):
    body = auth_client.get("/auth/analytics?time_window=1d").json()
    for row in body["top_actors"]:
        assert "pct_of_total" in row
        assert "trend" in row
        assert row["trend"] in ("up", "down", "stable")


# ─────────────── noise-table display_name read-through ──────────────────


@pytest.fixture()
def auth_client_with_noise_display(monkeypatch):
    """Variant fixture — seeds two enriched kafka.Authentication rows
    (actor_display_name + actor_email populated on the noise row) and
    one User:N row that's only resolvable via the noise-row column."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "auditlens.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv("FORWARDER_HEALTH_URL", "http://127.0.0.1:9/health")
        monkeypatch.setenv("API_AUTH_ENABLED", "false")
        monkeypatch.setattr("backend.app.main.init_db", lambda: None)
        get_settings.cache_clear()

        from backend.app.core.limiter import limiter
        from backend.app.services.system_service import reset_forwarder_health_cache

        reset_forwarder_health_cache()
        noise_service.reset_noise_table_existence_cache()
        limiter.enabled = False
        limiter.reset()

        engine = build_engine(f"sqlite:///{db_path}")
        TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        init_db(engine)
        _create_noise_table(engine)

        now = datetime.now(timezone.utc)
        rows = [
            # Enriched at ingest — has both columns populated.
            {
                "timestamp": now - timedelta(minutes=1),
                "actor": "u-resolved",
                "actor_display_name": "Resolved User",
                "actor_email": "ru@confluent.io",
                "action": "kafka.Authentication",
                "result": "Success",
                "resource_name": None,
                "source_ip": "10.0.0.1",
                "environment_id": "env-aaa",
                "cluster_id": "lkc-bbb",
                "is_denied": False,
            },
            # Backfilled — noise row has display_name and email but no u-xxx exists.
            {
                "timestamp": now - timedelta(minutes=2),
                "actor": "User:8893428",
                "actor_display_name": "Backfilled MDS User",
                "actor_email": "mds@confluent.io",
                "action": "kafka.Authentication",
                "result": "Success",
                "resource_name": None,
                "source_ip": "10.0.0.2",
                "environment_id": "env-aaa",
                "cluster_id": "lkc-bbb",
                "is_denied": False,
            },
            # Unresolved — neither noise-row enrichment nor any other source.
            {
                "timestamp": now - timedelta(minutes=3),
                "actor": "User:99999999",
                "actor_display_name": None,
                "actor_email": None,
                "action": "kafka.Authentication",
                "result": "Success",
                "resource_name": None,
                "source_ip": "10.0.0.3",
                "environment_id": "env-aaa",
                "cluster_id": "lkc-bbb",
                "is_denied": False,
            },
        ]
        with engine.begin() as conn:
            for row in rows:
                conn.execute(noise_service.audit_events_noise.insert(), row)

        app = create_app()

        def override_db():
            db = TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        yield TestClient(app)


def test_auth_analytics_uses_noise_row_display_name(auth_client_with_noise_display):
    """The route must surface actor_display_name / actor_email straight
    from the noise row when populated — no audit_events cross-join
    required. Covers both newly-ingested rows (via principalResourceId
    swap) and offline-backfilled User:N rows."""
    body = auth_client_with_noise_display.get("/auth/analytics?time_window=1d").json()
    by_actor = {row["actor"]: row for row in body["top_actors"]}

    # u-resolved → enriched at ingest
    resolved = by_actor["u-resolved"]
    assert resolved["actor_display_name"] == "Resolved User"
    assert resolved["actor_email"] == "ru@confluent.io"

    # User:8893428 → resolved via the backfilled noise-row column
    backfilled = by_actor["User:8893428"]
    assert backfilled["actor_display_name"] == "Backfilled MDS User"
    assert backfilled["actor_email"] == "mds@confluent.io"

    # User:99999999 → no source resolves it; falls through to raw.
    unresolved = by_actor["User:99999999"]
    assert unresolved["actor_display_name"] == "User:99999999"
    assert unresolved["actor_email"] is None
