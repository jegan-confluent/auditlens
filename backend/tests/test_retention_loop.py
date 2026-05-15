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
    from backend.app.core.config import Settings

    cleanup_calls = []
    settings_zero = Settings(
        EVENT_RETENTION_DAYS=0,
        RAW_PAYLOAD_RETENTION_DAYS=7,
        NOISE_RETENTION_DAYS=3,
    )

    sleep_count = 0

    async def fake_sleep(seconds):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 2:
            raise asyncio.CancelledError

    async def run():
        with (
            patch.object(main_mod.asyncio, "sleep", side_effect=fake_sleep),
            patch("backend.app.main.get_settings", return_value=settings_zero),
            patch.object(main_mod, "cleanup_retention", side_effect=lambda *a, **kw: cleanup_calls.append(True)),
        ):
            try:
                await main_mod._retention_loop()
            except asyncio.CancelledError:
                pass

    asyncio.run(run())
    assert cleanup_calls == [], "cleanup_retention should not be called when event_retention_days=0"


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
