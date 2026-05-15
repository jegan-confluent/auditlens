"""Tests for the actor mappings CRUD API."""
import tempfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.app.db.database import build_engine, get_db, init_db
from backend.app.main import create_app
from backend.app.core.config import get_settings


@pytest.fixture()
def client(monkeypatch, tmp_path):
    yaml_file = tmp_path / "actor_mappings.yml"
    yaml_file.write_text("mappings:\n  sa-existing: 'Existing Mapping'\n", encoding="utf-8")
    monkeypatch.setenv("ACTOR_MAPPINGS_FILE", str(yaml_file))

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "actor_mappings_test.db"
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
        with TestClient(app) as c:
            yield c


def test_list_actor_mappings_returns_list(client):
    r = client.get("/actor-mappings")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert any(m["raw_id"] == "sa-existing" for m in data)


def test_create_actor_mapping_success(client):
    r = client.post("/actor-mappings", json={
        "raw_id": "sa-new123",
        "display_name": "New Service Account",
        "team": "Platform",
        "notes": "Created via API",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["raw_id"] == "sa-new123"
    assert data["display_name"] == "New Service Account"
    assert data["team"] == "Platform"

    # Confirm persisted
    r2 = client.get("/actor-mappings")
    assert any(m["raw_id"] == "sa-new123" for m in r2.json())


def test_create_actor_mapping_duplicate_returns_409(client):
    r = client.post("/actor-mappings", json={
        "raw_id": "sa-existing",
        "display_name": "Duplicate",
    })
    assert r.status_code == 409


def test_update_actor_mapping_success(client):
    r = client.put("/actor-mappings/sa-existing", json={
        "raw_id": "sa-existing",
        "display_name": "Updated Display Name",
        "team": "Data Engineering",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["display_name"] == "Updated Display Name"
    assert data["team"] == "Data Engineering"


def test_delete_actor_mapping_success(client):
    r = client.delete("/actor-mappings/sa-existing")
    assert r.status_code == 200
    data = r.json()
    assert data["deleted"] is True

    # Confirm removed
    r2 = client.get("/actor-mappings")
    assert not any(m["raw_id"] == "sa-existing" for m in r2.json())


def test_delete_actor_mapping_not_found_returns_404(client):
    r = client.delete("/actor-mappings/sa-does-not-exist")
    assert r.status_code == 404
