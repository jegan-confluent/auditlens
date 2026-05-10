"""Tests for the SQLite hot cache runtime guard.

The forwarder no longer dual-writes to the legacy SQLiteProductStore in
product mode by default. The decision function is small; we exercise it
in isolation across the supported flag values so the precedence rule
between ENABLE_SQLITE_HOT_CACHE and PRODUCT_MODE is locked down.
"""

from __future__ import annotations

import importlib

import pytest

import audit_forwarder as fwd


def _reload_with_env(monkeypatch, *, database_url: str, hot_cache: str | None = None):
    """Reload audit_forwarder under controlled environment.

    PRODUCT_MODE and ENABLE_SQLITE_HOT_CACHE are computed at module
    import time, so we set the env, reload the module, and read back.
    """
    monkeypatch.setenv("DATABASE_URL", database_url)
    if hot_cache is None:
        monkeypatch.delenv("ENABLE_SQLITE_HOT_CACHE", raising=False)
    else:
        monkeypatch.setenv("ENABLE_SQLITE_HOT_CACHE", hot_cache)
    return importlib.reload(fwd)


def test_auto_disables_hot_cache_in_product_mode(monkeypatch):
    mod = _reload_with_env(
        monkeypatch,
        database_url="postgresql://u:p@host:5432/auditlens",
        hot_cache="auto",
    )
    assert mod.PRODUCT_MODE is True
    assert mod._sqlite_hot_cache_enabled() is False


def test_auto_enables_hot_cache_in_demo_mode(monkeypatch):
    mod = _reload_with_env(
        monkeypatch,
        database_url="sqlite:///./data/test.db",
        hot_cache="auto",
    )
    assert mod.PRODUCT_MODE is False
    assert mod._sqlite_hot_cache_enabled() is True


def test_default_value_is_auto(monkeypatch):
    """Unset ENABLE_SQLITE_HOT_CACHE must behave the same as 'auto'."""
    mod = _reload_with_env(
        monkeypatch,
        database_url="postgresql://u:p@host/db",
        hot_cache=None,
    )
    assert mod.ENABLE_SQLITE_HOT_CACHE == "auto"
    assert mod._sqlite_hot_cache_enabled() is False


def test_true_forces_on_even_in_product_mode(monkeypatch):
    mod = _reload_with_env(
        monkeypatch,
        database_url="postgresql://u:p@host/db",
        hot_cache="true",
    )
    assert mod.PRODUCT_MODE is True
    assert mod._sqlite_hot_cache_enabled() is True


def test_false_forces_off_even_in_demo_mode(monkeypatch):
    mod = _reload_with_env(
        monkeypatch,
        database_url="sqlite:///./data/demo.db",
        hot_cache="false",
    )
    assert mod.PRODUCT_MODE is False
    assert mod._sqlite_hot_cache_enabled() is False


@pytest.mark.parametrize("truthy", ["true", "True", "TRUE", "1", "yes", "on"])
def test_truthy_aliases_force_on(monkeypatch, truthy):
    mod = _reload_with_env(
        monkeypatch,
        database_url="postgresql://u:p@host/db",
        hot_cache=truthy,
    )
    assert mod._sqlite_hot_cache_enabled() is True


@pytest.mark.parametrize("falsy", ["false", "False", "FALSE", "0", "no", "off"])
def test_falsy_aliases_force_off(monkeypatch, falsy):
    mod = _reload_with_env(
        monkeypatch,
        database_url="sqlite:///demo.db",
        hot_cache=falsy,
    )
    assert mod._sqlite_hot_cache_enabled() is False


def test_unknown_value_falls_through_to_auto(monkeypatch):
    """Any unrecognised flag value is treated as 'auto' so a typo doesn't
    silently force-enable the legacy store in production."""
    mod = _reload_with_env(
        monkeypatch,
        database_url="postgresql://u:p@host/db",
        hot_cache="maybe",
    )
    # Falls through to PRODUCT_MODE check → disabled because PG.
    assert mod._sqlite_hot_cache_enabled() is False
    mod = _reload_with_env(
        monkeypatch,
        database_url="sqlite:///demo.db",
        hot_cache="maybe",
    )
    # Falls through to PRODUCT_MODE check → enabled because non-PG.
    assert mod._sqlite_hot_cache_enabled() is True


def test_initialize_product_store_skips_when_disabled(monkeypatch):
    """When the guard says skip, initialize_product_store_or_exit must
    leave product_store = None and not raise. All call sites in the
    forwarder already guard with `if product_store: …`."""
    # PERSISTENCE_ENABLED defaults to true and PersistenceConfig is
    # frozen, so we don't need to fiddle with it — we set DATABASE_URL
    # to PG which trips the guard ahead of any SQLite open attempt.
    monkeypatch.setenv("PERSISTENCE_ENABLED", "true")
    mod = _reload_with_env(
        monkeypatch,
        database_url="postgresql://u:p@host/db",
        hot_cache="auto",
    )
    assert mod.PERSISTENCE_CONFIG.enabled is True
    mod.product_store = None
    mod.initialize_product_store_or_exit()
    assert mod.product_store is None


def test_postgresql_psycopg_url_also_detects_product_mode(monkeypatch):
    """The forwarder normalizes postgresql:// to postgresql+psycopg://
    inside the DB writer; both prefixes must trigger product mode."""
    mod = _reload_with_env(
        monkeypatch,
        database_url="postgresql+psycopg://u:p@host/db",
        hot_cache="auto",
    )
    assert mod.PRODUCT_MODE is True
    assert mod._sqlite_hot_cache_enabled() is False
