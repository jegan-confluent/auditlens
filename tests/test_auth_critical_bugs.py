"""Tests for critical auth bugs: BUG-1 (Role.VIEWER on auth disabled), BUG-2 (triage auth check)."""
import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient
from fastapi import FastAPI

from src.product.auth import AuthConfig, Authenticator, Role


# ---------------------------------------------------------------------------
# BUG-1: auth disabled must grant VIEWER, not ADMIN
# ---------------------------------------------------------------------------

def test_auth_disabled_returns_viewer_role():
    """When auth is disabled, anonymous-dev actor must have VIEWER role, not ADMIN."""
    config = AuthConfig(enabled=False, tokens={})
    result = Authenticator(config).authenticate(headers={})
    assert result.ok is True
    assert result.actor is not None
    assert result.actor.role == Role.VIEWER, (
        f"Expected VIEWER but got {result.actor.role}. "
        "Granting ADMIN when auth is disabled is a security escalation."
    )


def test_auth_disabled_actor_cannot_trigger_admin_check():
    """VIEWER from auth-disabled mode must not pass an admin-role check."""
    config = AuthConfig(enabled=False, tokens={})
    result = Authenticator(config).authenticate(headers={})
    assert result.actor is not None
    assert result.actor.role != Role.ADMIN


def test_auth_enabled_admin_token_still_gets_admin():
    """Enabling auth and using an admin token must still return ADMIN role."""
    tokens_json = '[{"token": "my-token", "actor_id": "admin-user", "role": "admin"}]'
    config = AuthConfig.from_json(tokens_json)
    result = Authenticator(config).authenticate(headers={"Authorization": "Bearer my-token"})
    assert result.ok is True
    assert result.actor is not None
    assert result.actor.role == Role.ADMIN


# ---------------------------------------------------------------------------
# BUG-2: POST /events/{id}/triage requires authentication
# ---------------------------------------------------------------------------

def _make_test_app():
    """Build a minimal FastAPI app with only the events router for testing."""
    from backend.app.api.routes.events import router as events_router
    from backend.app.db.database import get_db

    app = FastAPI()

    # Provide a stub DB session
    def override_get_db():
        yield MagicMock()

    app.dependency_overrides[get_db] = override_get_db
    app.include_router(events_router)
    return app


@pytest.fixture()
def events_client():
    return TestClient(_make_test_app(), raise_server_exceptions=False)


def test_triage_without_auth_header_when_auth_enabled_returns_401(events_client):
    """POST /events/{id}/triage with no credentials when auth is enabled must return 401."""
    with patch("backend.app.api.routes.patterns.AuthConfig.from_env") as mock_from_env:
        config = AuthConfig(enabled=True, tokens={})
        mock_from_env.return_value = config
        resp = events_client.post(
            "/events/1/triage",
            json={"triage_status": "reviewed"},
        )
    assert resp.status_code in (401, 403), (
        f"Expected 401/403 but got {resp.status_code}. "
        "Unauthenticated triage must be rejected when auth is enabled."
    )


def test_triage_with_viewer_role_returns_403(events_client):
    """VIEWER-role token must not be allowed to triage events when auth is enabled."""
    tokens_json = '[{"token": "viewer-tok", "actor_id": "viewer-user", "role": "viewer"}]'
    config = AuthConfig.from_json(tokens_json)
    with patch("backend.app.api.routes.patterns.AuthConfig.from_env", return_value=config):
        resp = events_client.post(
            "/events/1/triage",
            json={"triage_status": "reviewed"},
            headers={"Authorization": "Bearer viewer-tok"},
        )
    assert resp.status_code == 403, (
        f"Expected 403 for VIEWER but got {resp.status_code}."
    )
