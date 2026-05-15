"""Tests for the resource catalog endpoint."""
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.app.db.database import build_engine, get_db, init_db
from backend.app.main import create_app
from backend.app.core.config import get_settings
from backend.scripts.seed_data import SEED_EVENTS


@pytest.fixture()
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "resources_test.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv("FORWARDER_HEALTH_URL", "http://127.0.0.1:9/health")
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
