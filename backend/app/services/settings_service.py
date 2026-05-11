"""Key-value settings store backed by the app_settings table.

Secrets are AES-256-GCM encrypted before storage; only masked values
are ever returned through the API layer. The raw decrypt() is for
internal use only (e.g. cold_storage_service reading credentials).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.encryption import decrypt, encrypt
from backend.app.db.models import AppSettings

logger = logging.getLogger("auditlens.backend.settings")


def _mask(value: str) -> str:
    """Return ••••{last4} or •••• if shorter."""
    if not value:
        return ""
    tail = value[-4:] if len(value) >= 4 else value
    return f"••••{tail}"


def get(db: Session, category: str, key: str) -> str | None:
    """Return the plaintext value (decrypting if secret). Internal use only."""
    row = db.query(AppSettings).filter_by(category=category, key=key).first()
    if row is None:
        return None
    if row.is_secret and row.value_enc is not None:
        try:
            return decrypt(row.value_enc)
        except Exception as exc:
            logger.warning("Failed to decrypt %s/%s: %s", category, key, exc)
            return None
    return row.value


def set(db: Session, category: str, key: str, value: str, *, is_secret: bool = False, updated_by: str | None = None) -> None:
    """Upsert a setting. Encrypts automatically when is_secret=True."""
    row = db.query(AppSettings).filter_by(category=category, key=key).first()
    if row is None:
        row = AppSettings(category=category, key=key)
        db.add(row)
    row.is_secret = is_secret
    row.updated_by = updated_by
    row.updated_at = datetime.now(timezone.utc)
    if is_secret:
        row.value = None
        row.value_enc = encrypt(value)
    else:
        row.value = value
        row.value_enc = None
    db.commit()


def get_masked(db: Session, category: str, key: str) -> str | None:
    """Return masked value for API responses. Never exposes decrypted secrets."""
    row = db.query(AppSettings).filter_by(category=category, key=key).first()
    if row is None:
        return None
    if row.is_secret:
        return _mask(row.value or "****")
    return row.value


def is_set(db: Session, category: str, key: str) -> bool:
    """Return True if the setting exists and has a non-empty value."""
    row = db.query(AppSettings).filter_by(category=category, key=key).first()
    if row is None:
        return False
    if row.is_secret:
        return row.value_enc is not None and len(row.value_enc) > 0
    return bool(row.value)


def delete(db: Session, category: str, key: str) -> bool:
    """Delete a setting. Returns True if it existed."""
    row = db.query(AppSettings).filter_by(category=category, key=key).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def get_category(db: Session, category: str) -> dict[str, Any]:
    """Return all settings in a category with masked values."""
    rows = db.query(AppSettings).filter_by(category=category).all()
    return {
        row.key: {
            "is_secret": row.is_secret,
            "is_set": is_set(db, category, row.key),
            "masked": get_masked(db, category, row.key),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "updated_by": row.updated_by,
        }
        for row in rows
    }
