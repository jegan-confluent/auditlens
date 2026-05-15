"""Tests for the feedback submission endpoint."""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.app.db.database import build_engine, get_db, init_db
from backend.app.main import create_app
from backend.app.core.config import get_settings


@pytest.fixture()
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "feedback_test.db"
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
            yield c


def test_submit_feedback_success(client):
    r = client.post("/feedback", json={
        "type": "bug",
        "title": "Something broke",
        "description": "The events table does not load when filtering by Review.",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["type"] == "bug"
    assert "id" in data
    assert "created_at" in data


def test_submit_feedback_with_email(client):
    r = client.post("/feedback", json={
        "type": "feature",
        "title": "Add dark mode",
        "description": "Would love a dark mode toggle in the settings page.",
        "email": "user@example.com",
    })
    assert r.status_code == 201


def test_submit_feedback_title_too_short(client):
    r = client.post("/feedback", json={
        "type": "general",
        "title": "Hi",
        "description": "This is a valid description.",
    })
    assert r.status_code == 422


def test_submit_feedback_description_too_short(client):
    r = client.post("/feedback", json={
        "type": "bug",
        "title": "Valid title",
        "description": "short",
    })
    assert r.status_code == 422


def test_submit_feedback_invalid_type(client):
    r = client.post("/feedback", json={
        "type": "unknown_type",
        "title": "Valid title here",
        "description": "A valid description for this test.",
    })
    assert r.status_code == 422


def test_list_feedback_returns_submissions(client):
    client.post("/feedback", json={
        "type": "bug",
        "title": "First submission",
        "description": "Something is broken on the events page.",
    })
    client.post("/feedback", json={
        "type": "feature",
        "title": "Second submission",
        "description": "Would love to see better dark mode support.",
    })
    r = client.get("/feedback")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 2


def test_list_feedback_filter_by_type(client):
    client.post("/feedback", json={
        "type": "bug",
        "title": "A bug report title",
        "description": "Detailed description of the bug.",
    })
    client.post("/feedback", json={
        "type": "feature",
        "title": "Feature request title",
        "description": "This is a detailed feature request description.",
    })
    r = client.get("/feedback?type=bug")
    assert r.status_code == 200
    data = r.json()
    assert all(item["type"] == "bug" for item in data)


def test_feedback_post_requires_auth_when_auth_enabled(client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    r = client.post("/feedback", json={
        "type": "bug",
        "title": "Auth test feedback",
        "description": "This request should be rejected without a valid token.",
    })
    assert r.status_code in (401, 403, 503)
