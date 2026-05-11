"""AES-256-GCM encryption for the app_settings secret values.

The key is read from SETTINGS_ENCRYPTION_KEY (base64-encoded 32 bytes).
If the env var is not set, a random key is generated in memory, logged,
and a warning is emitted to prompt the operator to persist it.

Uses Python's built-in `cryptography` package if available, otherwise
falls back to manual AES-GCM via the `cryptography` extra. If neither
is present, secrets cannot be stored (raises RuntimeError at call time).
"""
from __future__ import annotations

import base64
import logging
import os
import secrets
import struct
import threading
from typing import Final

logger = logging.getLogger("auditlens.backend.encryption")

_KEY_BYTES: Final[int] = 32
_NONCE_BYTES: Final[int] = 12
_TAG_BYTES: Final[int] = 16

_lock = threading.Lock()
_key_cache: bytes | None = None


def _load_key() -> bytes:
    global _key_cache
    with _lock:
        if _key_cache is not None:
            return _key_cache
        raw = os.environ.get("SETTINGS_ENCRYPTION_KEY", "").strip()
        if raw:
            try:
                key = base64.b64decode(raw)
                if len(key) != _KEY_BYTES:
                    raise ValueError(f"key must be {_KEY_BYTES} bytes, got {len(key)}")
                _key_cache = key
                return _key_cache
            except Exception as exc:
                raise RuntimeError(f"Invalid SETTINGS_ENCRYPTION_KEY: {exc}") from exc
        # Generate ephemeral key — warn operator
        key = secrets.token_bytes(_KEY_BYTES)
        encoded = base64.b64encode(key).decode()
        logger.warning(
            "SETTINGS_ENCRYPTION_KEY not set — using ephemeral key. "
            "Encrypted settings will be lost on restart. "
            "Add to .env: SETTINGS_ENCRYPTION_KEY=%s",
            encoded,
        )
        _key_cache = key
        return _key_cache


def encrypt(plaintext: str) -> bytes:
    """Encrypt plaintext → nonce(12) + ciphertext + tag(16) as bytes."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise RuntimeError("cryptography package required for encryption: pip install cryptography") from exc
    key = _load_key()
    nonce = secrets.token_bytes(_NONCE_BYTES)
    aesgcm = AESGCM(key)
    ct_with_tag = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return nonce + ct_with_tag


def decrypt(ciphertext: bytes) -> str:
    """Decrypt nonce(12) + ciphertext + tag(16) → plaintext string."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise RuntimeError("cryptography package required for decryption: pip install cryptography") from exc
    if len(ciphertext) < _NONCE_BYTES + _TAG_BYTES:
        raise ValueError("ciphertext too short")
    key = _load_key()
    nonce = ciphertext[:_NONCE_BYTES]
    ct_with_tag = ciphertext[_NONCE_BYTES:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct_with_tag, None).decode("utf-8")


def reset_key_cache() -> None:
    """Drop cached key. Used in tests."""
    global _key_cache
    with _lock:
        _key_cache = None
