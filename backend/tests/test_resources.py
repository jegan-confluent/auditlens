"""Tests for the resource catalog endpoint."""
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.app.db.database import build_engine, get_db, init_db
from backend.app.db.models import ResourceCatalog
from backend.app.main import create_app
from backend.app.core.config import get_settings
from backend.scripts.seed_data import SEED_EVENTS


@pytest.fixture()
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "resources_test.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv("FORWARDER_HEALTH_URL", "http://127.0.0.1:9/health")
        monkeypatch.setenv("API_AUTH_ENABLED", "false")
        monkeypatch.setattr("backend.app.main.init_db", lambda: None)
        get_settings.cache_clear()
        from backend.app.core.limiter import limiter
        from backend.app.services.system_service import reset_forwarder_health_cache
        from backend.app.services.filter_options_service import clear_filter_options_cache
        reset_forwarder_health_cache()
        clear_filter_options_cache()
        limiter.enabled = False
        limiter.reset()
        engine = build_engine(f"sqlite:///{db_path}")
        TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        init_db(engine)

        app = create_app()

        def override_get_db():
            db = TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

        # Seed events so resource_catalog gets populated
        with TestClient(app) as c:
            from backend.app.services.event_service import upsert_events
            db_override = next(iter(app.dependency_overrides.values()))
            session_gen = db_override()
            db = next(session_gen)
            try:
                upsert_events(db, SEED_EVENTS)
            finally:
                session_gen.close()
            yield c


def test_resource_catalog_returns_list(client):
    r = client.get("/resources")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    for item in data:
        assert "resource_id" in item
        assert "resource_type" in item
        assert "resource_name" in item
        assert "first_seen" in item
        assert "last_seen" in item
        assert "event_count" in item
        assert isinstance(item["event_count"], int)


# ---------------------------------------------------------------------------
# Fixtures and helpers for /resources/catalog tests
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 18, 12, 0, 0, tzinfo=timezone.utc)


def _seed_catalog(db, rows: list[dict]) -> None:
    for row in rows:
        db.add(ResourceCatalog(
            resource_id=row["resource_id"],
            resource_type=row["resource_type"],
            resource_name=row["resource_name"],
            display_name=row.get("display_name"),
            first_seen_at=_NOW,
            last_seen_at=_NOW,
        ))
    db.commit()


@pytest.fixture()
def catalog_client(monkeypatch):
    """Client with a fixed resource_catalog seeded directly (no upsert_events path)."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "catalog_test.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv("FORWARDER_HEALTH_URL", "http://127.0.0.1:9/health")
        monkeypatch.setenv("API_AUTH_ENABLED", "false")
        monkeypatch.setattr("backend.app.main.init_db", lambda: None)
        get_settings.cache_clear()
        from backend.app.core.limiter import limiter
        from backend.app.services.system_service import reset_forwarder_health_cache
        from backend.app.services.filter_options_service import clear_filter_options_cache
        reset_forwarder_health_cache()
        clear_filter_options_cache()
        limiter.enabled = False
        limiter.reset()
        engine = build_engine(f"sqlite:///{db_path}")
        TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        init_db(engine)
        app = create_app()

        def override_get_db():
            db = TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

        with TestClient(app) as c:
            session_gen = override_get_db()
            db = next(session_gen)
            try:
                _seed_catalog(db, [
                    {"resource_id": "lkc-abc/payments", "resource_type": "Topic", "resource_name": "payments"},
                    {"resource_id": "lkc-abc/orders", "resource_type": "Topic", "resource_name": "orders"},
                    {"resource_id": "env-xyz", "resource_type": "Environment", "resource_name": "production"},
                    {"resource_id": "sa-001", "resource_type": "ServiceAccount", "resource_name": "sa-deploy"},
                ])
            finally:
                session_gen.close()
            yield c


# ---------------------------------------------------------------------------
# /resources/catalog tests
# ---------------------------------------------------------------------------

def test_resource_catalog_returns_grouped_results(catalog_client):
    """Catalog endpoint returns items wrapper with total count."""
    r = catalog_client.get("/resources/catalog")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] == len(data["items"])
    assert data["total"] == 4
    item = data["items"][0]
    assert "resource_id" in item
    assert "resource_type" in item
    assert "resource_name" in item
    assert "first_seen" in item
    assert "last_seen" in item
    assert isinstance(item["event_count"], int)


def test_resource_catalog_filter_by_type(catalog_client):
    """resource_type query param returns only matching rows."""
    r = catalog_client.get("/resources/catalog?resource_type=Topic")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    for item in data["items"]:
        assert item["resource_type"].lower() == "topic"


def test_resource_catalog_search(catalog_client):
    """q param filters by resource_name substring (case-insensitive)."""
    r = catalog_client.get("/resources/catalog?q=pay")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["resource_name"] == "payments"
