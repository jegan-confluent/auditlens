"""Tests for the AI summary layer.

All Claude calls are mocked. The shared ``client`` fixture wires the
same in-memory SQLite store the rest of the API tests use, so the
service-layer queries that the summarizer reaches into (get_summary,
_period_stats, the raw counts) run against seeded rows instead of a
mocked DB. That gives us coverage of the real context-building path
plus the failure / cache / disabled paths.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.app.ai.prompts import SUMMARY_INSTRUCTIONS, SYSTEM_PROMPT, render_summary_prompt
from backend.app.ai.summarizer import (
    AuditSummarizer,
    get_summarizer,
    reset_summarizer_for_tests,
)
from backend.app.core.config import get_settings
from backend.app.db.database import build_engine, get_db, init_db
from backend.app.main import create_app
from backend.app.services.event_service import create_event
from backend.scripts.seed_data import SEED_EVENTS


# ── shared fixtures ─────────────────────────────────────────────────


@pytest.fixture()
def client(monkeypatch):
    """Boot the FastAPI app against an in-memory SQLite store seeded with
    the standard SEED_EVENTS rows. Mirrors the pattern in
    backend/tests/test_api.py — kept consistent so the test harness
    behaves the same regardless of which surface a test exercises.
    """
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "auditlens.db"
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
        with TestingSessionLocal() as db:
            for payload in SEED_EVENTS:
                create_event(db, payload)

        reset_summarizer_for_tests()
        app = create_app()

        def override_db():
            db = TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        yield TestClient(app)

    # Drop the singleton on the way out so cached state from this test
    # cannot leak into the next.
    reset_summarizer_for_tests()


@pytest.fixture()
def db_session():
    """Standalone in-memory session for tests that exercise the
    summarizer directly without the FastAPI surface."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "auditlens.db"
        engine = build_engine(f"sqlite:///{db_path}")
        TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        init_db(engine)
        with TestingSessionLocal() as db:
            for payload in SEED_EVENTS:
                create_event(db, payload)
            yield db


def _stub_message_response(payload: dict) -> MagicMock:
    """Mimic anthropic.types.Message — only the bits the summarizer reads.

    The SDK returns response.content as a list of content blocks each
    with a .text attribute. We supply one text block carrying the JSON
    we want the summarizer to parse.
    """
    block = MagicMock()
    block.text = json.dumps(payload)
    response = MagicMock()
    response.content = [block]
    return response


# ── 1. disabled ─────────────────────────────────────────────────────


def test_summarizer_disabled(monkeypatch, db_session):
    """AI_ENABLED=false → status=disabled, no Claude call attempted."""
    monkeypatch.setenv("AI_ENABLED", "false")
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-doesnt-matter")
    reset_summarizer_for_tests()

    summarizer = AuditSummarizer()
    result = summarizer.summarize(db_session, window_hours=24)

    assert result.status == "disabled"
    assert result.window_hours == 24
    assert result.message and "AI_ENABLED" in result.message
    # No Claude call was attempted, so latency stays None.
    assert result.latency_ms is None


# ── 2. no key ───────────────────────────────────────────────────────


def test_summarizer_no_key(monkeypatch, db_session):
    """AI_ENABLED=true but CLAUDE_API_KEY missing → status=error,
    not a 500 and not an uncaught exception."""
    monkeypatch.setenv("AI_ENABLED", "true")
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    reset_summarizer_for_tests()

    summarizer = AuditSummarizer()
    result = summarizer.summarize(db_session, window_hours=24)

    assert result.status == "error"
    assert result.message and "CLAUDE_API_KEY" in result.message


# ── 3. context shape ────────────────────────────────────────────────


def test_build_context(monkeypatch, db_session):
    """The structured payload sent to Claude has all required keys with
    the correct primitive types. Failing this test means the prompt
    payload contract has drifted from what the prompt expects."""
    monkeypatch.setenv("AI_ENABLED", "true")
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-test")
    reset_summarizer_for_tests()

    summarizer = AuditSummarizer()
    context = summarizer._build_context(db_session, window_hours=24)

    assert context["window_hours"] == 24
    assert isinstance(context["total_events"], int)
    assert set(context["by_signal"].keys()) == {
        "action_required",
        "attention",
        "informational",
        "noise",
    }
    for value in context["by_signal"].values():
        assert isinstance(value, int)

    assert isinstance(context["top_actors"], list)
    assert isinstance(context["top_actions"], list)
    assert isinstance(context["auth_failures"], dict)
    assert "total" in context["auth_failures"]
    assert "top_actors" in context["auth_failures"]

    for required_int_key in ("alerts_fired", "ip_denials", "role_changes", "access_transparency"):
        assert isinstance(context[required_int_key], int)

    assert "baseline_comparison" in context
    assert set(context["baseline_comparison"].keys()) == {
        "events_vs_7d_avg",
        "auth_failures_vs_7d_avg",
    }


# ── 4. prompt rendering ─────────────────────────────────────────────


def test_prompt_renders():
    """SUMMARY_PROMPT renders cleanly against a representative context
    dict. Specifically: it must contain the JSON instructions block so
    Claude knows the response schema, and must serialise the context
    object without raising — even if a value is a non-JSON type."""
    from datetime import datetime, timezone

    context = {
        "window_hours": 24,
        "total_events": 1234,
        "by_signal": {"action_required": 1, "attention": 2, "informational": 3, "noise": 4},
        "top_actors": [],
        "top_actions": [],
        # datetime intentionally included to confirm default=str works.
        "_last_seen": datetime.now(timezone.utc),
        "auth_failures": {"total": 0, "top_actors": []},
        "alerts_fired": 0,
        "ip_denials": 0,
        "role_changes": 0,
        "access_transparency": 0,
        "baseline_comparison": {"events_vs_7d_avg": "+0%", "auth_failures_vs_7d_avg": "+0%"},
    }

    rendered = render_summary_prompt(context)

    assert SUMMARY_INSTRUCTIONS in rendered
    assert '"headline"' in rendered
    assert "1234" in rendered  # context numbers must round-trip
    # System prompt is a separate string the route also sends, but the
    # rendered prompt is purely the user turn — the two never overlap.
    assert SYSTEM_PROMPT not in rendered


# ── 5. cache hit ────────────────────────────────────────────────────


def test_cache_hit(monkeypatch, db_session):
    """A second summarize() call inside the TTL returns the cached
    AuditSummary; the Claude SDK is only invoked once. force=True must
    invalidate the cache and trigger a fresh call."""
    monkeypatch.setenv("AI_ENABLED", "true")
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-test")
    monkeypatch.setenv("AI_CACHE_TTL", "300")
    reset_summarizer_for_tests()

    summarizer = AuditSummarizer()

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _stub_message_response({
        "headline": "All quiet",
        "health": "healthy",
        "summary": "Routine activity, no anomalies.",
        "anomalies": [],
        "top_risk": None,
        "recommended_actions": [],
        "confidence": "high",
    })
    # Bypass the lazy SDK import + auth-key construction.
    summarizer._client = fake_client

    first = summarizer.summarize(db_session, window_hours=24)
    second = summarizer.summarize(db_session, window_hours=24)

    assert first.status == "ok"
    assert first.headline == "All quiet"
    # Same object identity → returned from the cache, not regenerated.
    assert second is first
    assert fake_client.messages.create.call_count == 1

    # force=True bypasses the cache.
    third = summarizer.summarize(db_session, window_hours=24, force=True)
    assert third is not first
    assert fake_client.messages.create.call_count == 2


# ── 6. graceful failure ─────────────────────────────────────────────


def test_claude_failure_graceful(monkeypatch, db_session):
    """When Claude raises (timeout, network, 5xx) the summarizer MUST
    return an AuditSummary with status=error — the caller never sees
    the exception. This is the contract the FastAPI route depends on."""
    monkeypatch.setenv("AI_ENABLED", "true")
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-test")
    reset_summarizer_for_tests()

    summarizer = AuditSummarizer()
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = RuntimeError("upstream 500")
    summarizer._client = fake_client

    result = summarizer.summarize(db_session, window_hours=24)

    assert result.status == "error"
    assert "upstream 500" in (result.message or "")
    # context_used is still populated — the failure happened AFTER the
    # context build, so the dashboard can show what was attempted.
    assert result.context_used != {}


# ── 7. health endpoint shape ────────────────────────────────────────


def test_health_endpoint_disabled(client, monkeypatch):
    """When AI is disabled, /ai/summary/health reports enabled=false
    with a human-readable message the frontend renders directly."""
    monkeypatch.setenv("AI_ENABLED", "false")
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    reset_summarizer_for_tests()

    response = client.get("/ai/summary/health")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["configured"] is False
    assert "model" in body
    assert "cache_ttl_seconds" in body
    assert body["message"] and "AI_ENABLED" in body["message"]


# ── 8. integration: POST /ai/summary when disabled returns 200 ──────
#
# Bonus coverage — confirms the route layer wires the summarizer
# correctly and never 500s on the disabled path. Mirrors the contract
# the frontend depends on.


def test_post_summary_disabled_returns_200(client, monkeypatch):
    monkeypatch.setenv("AI_ENABLED", "false")
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    reset_summarizer_for_tests()

    response = client.post("/ai/summary", json={"window_hours": 24})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "disabled"
    assert body["window_hours"] == 24


def test_post_summary_ok_path_with_mocked_claude(client, monkeypatch):
    """End-to-end happy path with the SDK constructor patched out so no
    real Anthropic client is built. Validates the response shape the
    frontend renders."""
    monkeypatch.setenv("AI_ENABLED", "true")
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-test")
    reset_summarizer_for_tests()

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _stub_message_response({
        "headline": "Elevated denial rate",
        "health": "elevated",
        "summary": "Auth failures up 200% vs 7d baseline.",
        "anomalies": ["sa-abc accounts for 80% of failures"],
        "top_risk": "Potential credential rotation issue for sa-abc",
        "recommended_actions": ["Verify sa-abc credentials"],
        "confidence": "medium",
    })

    # Patch get_summarizer's singleton so the route picks up our stub.
    summarizer = get_summarizer()
    summarizer._client = fake_client

    response = client.post("/ai/summary", json={"window_hours": 24, "force": True})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["headline"] == "Elevated denial rate"
    assert body["health"] == "elevated"
    assert body["recommended_actions"] == ["Verify sa-abc credentials"]
    # latency_ms is set on the ok path.
    assert isinstance(body["latency_ms"], int)
