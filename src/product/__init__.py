"""AuditLens productization helpers."""

from .auth import (
    AccessToken,
    AuthConfig,
    AuthResult,
    Authenticator,
    Role,
)
from .persistence import PersistenceConfig, SQLiteProductStore, heal_sqlite_on_startup


def __getattr__(name):
    if name in {"BootstrapError", "BootstrapInputs", "CANONICAL_TOPICS", "SOURCE_AUDIT_TOPIC"}:
        from . import bootstrap

        return getattr(bootstrap, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "AccessToken",
    "AuthConfig",
    "AuthResult",
    "Authenticator",
    "Role",
    "BootstrapError",
    "BootstrapInputs",
    "CANONICAL_TOPICS",
    "SOURCE_AUDIT_TOPIC",
    "PersistenceConfig",
    "SQLiteProductStore",
    "heal_sqlite_on_startup",
]
