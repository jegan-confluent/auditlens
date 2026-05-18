"""Unit tests for the auto-retention background loop in backend/app/main.py."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def test_retention_loop_calls_cleanup_service(monkeypatch):
    """_retention_loop calls cleanup_retention when event_retention_days > 0."""
    import backend.app.main as main_mod

    cleanup_calls = []
    sleep_count = 0

    async def fake_sleep(seconds):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 2:
            raise asyncio.CancelledError

    async def fake_to_thread(fn):
        # Run synchronously in the test so we can observe calls
        return fn()

    with (
        patch.object(main_mod.asyncio, "sleep", side_effect=fake_sleep),
        patch.object(main_mod, "SessionLocal", return_value=MagicMock()),
        patch.object(main_mod, "cleanup_retention", side_effect=lambda *a, **kw: cleanup_calls.append(True) or {}),
        patch.object(main_mod.asyncio, "to_thread", side_effect=fake_to_thread),
    ):
        try:
            asyncio.run(main_mod._retention_loop())
        except asyncio.CancelledError:
            pass

    assert len(cleanup_calls) >= 1, "_retention_loop should call cleanup_retention at least once"


def test_retention_loop_skips_when_retention_days_zero(monkeypatch):
    """_retention_loop does not call cleanup when event_retention_days == 0."""
    import backend.app.main as main_mod

    cleanup_calls = []
    zero_retention = {"event_retention_days": 0, "raw_payload_retention_days": 7, "noise_retention_days": 3}

    sleep_count = 0

    async def fake_sleep(seconds):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 2:
            raise asyncio.CancelledError

    async def fake_to_thread(fn):
        return fn()

    async def run():
        with (
            patch.object(main_mod.asyncio, "sleep", side_effect=fake_sleep),
            patch.object(main_mod, "SessionLocal", return_value=MagicMock()),
            patch("backend.app.main.get_effective_retention", return_value=zero_retention),
            patch.object(main_mod, "cleanup_retention", side_effect=lambda *a, **kw: cleanup_calls.append(True)),
            patch.object(main_mod.asyncio, "to_thread", side_effect=fake_to_thread),
        ):
            try:
                await main_mod._retention_loop()
            except asyncio.CancelledError:
                pass

    asyncio.run(run())
    assert cleanup_calls == [], "cleanup_retention should not be called when event_retention_days=0"


def test_get_effective_retention_uses_db_value():
    """get_effective_retention returns DB value when present."""
    from unittest.mock import MagicMock
    from backend.app.services import settings_service

    db = MagicMock()

    def fake_get(db_, category, key):
        return {"event_retention_days": "14", "raw_payload_retention_days": "10", "noise_retention_days": "5"}.get(key)

    with patch.object(settings_service, "get", side_effect=fake_get):
        result = settings_service.get_effective_retention(db)

    assert result["event_retention_days"] == 14
    assert result["raw_payload_retention_days"] == 10
    assert result["noise_retention_days"] == 5


def test_get_effective_retention_falls_back_to_env():
    """get_effective_retention falls back to env/config defaults when DB row absent."""
    from unittest.mock import MagicMock
    from backend.app.services import settings_service

    db = MagicMock()

    with patch.object(settings_service, "get", return_value=None):
        result = settings_service.get_effective_retention(db)

    assert result["event_retention_days"] > 0
    assert result["raw_payload_retention_days"] > 0
    assert result["noise_retention_days"] > 0


def test_get_effective_retention_non_integer_falls_back():
    """get_effective_retention falls back when DB value is non-integer."""
    from unittest.mock import MagicMock
    from backend.app.services import settings_service

    db = MagicMock()

    with patch.object(settings_service, "get", return_value="not-a-number"):
        result = settings_service.get_effective_retention(db)

    # All three must be positive ints from config defaults
    assert isinstance(result["event_retention_days"], int)
    assert result["event_retention_days"] > 0


def test_retention_loop_non_fatal_on_exception(monkeypatch):
    """_retention_loop does not propagate cleanup exceptions."""
    import backend.app.main as main_mod

    sleep_count = 0

    async def fake_sleep(seconds):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 2:
            raise asyncio.CancelledError

    async def run():
        with (
            patch.object(main_mod.asyncio, "sleep", side_effect=fake_sleep),
            patch.object(main_mod, "SessionLocal", side_effect=RuntimeError("db down")),
        ):
            try:
                await main_mod._retention_loop()
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                raise AssertionError(f"_retention_loop must not propagate exceptions: {exc}") from exc

    asyncio.run(run())
