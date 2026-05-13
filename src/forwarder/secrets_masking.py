"""Secrets masking utilities for safe logging."""

import re

# ──────────── secrets masking for safe logging ────────────
# Single source of truth for "is this field name sensitive?". Lower-case tokens
# that we expect after normalising - and . to _. New tokens: every commonly-used
# OAuth / IAM / API field that previously slipped past the redactor.
_SENSITIVE_KEY_TOKENS: tuple[str, ...] = (
    "password",
    "passphrase",
    "passwd",
    "secret",            # covers client_secret, api_secret, etc.
    "api_key",
    "apikey",
    "x_api_key",
    "token",             # covers access_token / refresh_token / id_token / bearer token
    "bearer",
    "credential",
    "authorization",
    "cookie",
    "private_key",
    "client_id",         # principal-style identifier; treat as sensitive in logs
)


def _key_is_sensitive(name: str) -> bool:
    normalized = name.lower().replace("-", "_").replace(".", "_")
    return any(token in normalized for token in _SENSITIVE_KEY_TOKENS)


# Build a separator-tolerant regex alternation for the sensitive tokens above.
# The `_` placeholders inside multi-word tokens become ``[_.\-]?`` so we match
# ``api_key``, ``api.key``, ``api-key``, and ``apikey`` against the same token.
def _token_pattern(token: str) -> str:
    escaped = re.escape(token)
    return escaped.replace(r"\_", r"[_.\-]?").replace(r"_", r"[_.\-]?")


_TOKEN_ALT = "|".join(_token_pattern(t) for t in _SENSITIVE_KEY_TOKENS)


def mask_config_for_logging(config: dict) -> dict:
    """
    Return config dict with secrets masked for safe logging.

    Use this when logging any configuration that might contain sensitive values.
    Masks: passwords, secrets, API keys, tokens, credentials, OAuth fields,
    cookies, and authorization headers.
    """
    masked = {}
    for k, v in config.items():
        if _key_is_sensitive(str(k)):
            masked[k] = '***MASKED***'
        else:
            masked[k] = v
    return masked


# Pre-compiled regexes for masking secrets out of a free-form *string*
# (Kafka error messages, exception strings, librdkafka diagnostics, etc.).
# We scrub two shapes:
#   1. ``key=value`` / ``key: value`` / ``key:"value"`` where the key matches a
#      sensitive token. Mask the value.
#   2. ``Bearer <token>`` / ``Basic <token>`` Authorization-header fragments.
# Order matters: Bearer/Basic Authorization fragments are scrubbed *before* the
# generic key=value pass so that ``Authorization: Bearer <token>`` becomes
# ``Authorization: Bearer ***MASKED***`` rather than the key=value pattern
# eating ``Bearer`` as the value of the ``Authorization:`` field and leaving
# the actual token unmasked at the tail.
_TEXT_MASK_PATTERNS = [
    re.compile(r"\b(?P<scheme>Bearer|Basic)\s+(?P<value>[A-Za-z0-9_\-\.=+/]{6,})", flags=re.IGNORECASE),
    re.compile(
        r"(?P<key>[A-Za-z0-9_.\-]*?(?:" + _TOKEN_ALT + r")[A-Za-z0-9_.\-]*?)"
        r"(?P<sep>\s*[:=]\s*)"
        r"(?P<quote>[\"']?)"
        r"(?P<value>[^\s\"'&,;]+)"
        r"(?P=quote)",
        flags=re.IGNORECASE,
    ),
]


def mask_sensitive_text(text: str | None) -> str | None:
    """
    Scrub secret-shaped substrings out of a free-form string.

    ``mask_config_for_logging`` works on dicts where keys carry the metadata
    needed for redaction. For raw error messages and exception strings we have
    no key to inspect, so we walk a curated set of regexes that catch the most
    common ``key=value`` / Authorization-header shapes.
    """
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    masked = text
    for pattern in _TEXT_MASK_PATTERNS:
        masked = pattern.sub(
            lambda match: (
                f"{match.group('scheme')} ***MASKED***"
                if "scheme" in match.groupdict() and match.group("scheme")
                else f"{match.group('key')}{match.group('sep')}{match.group('quote') or ''}***MASKED***{match.group('quote') or ''}"
            ),
            masked,
        )
    return masked
