"""FIX 1 regression: User: prefix must be stripped so the same person is never
stored as two distinct actors (User:u-zmknkp7 vs u-zmknkp7).

Tests cover:
  - normalize_principal() in actor_enrichment
  - normalize_event() preferring principal_normalized over raw principal
  - flatten_audit() setting principal_normalized correctly for u- / sa- forms
"""
from datetime import datetime, timezone

import audit_forwarder as forwarder
from src.product.actor_enrichment import normalize_principal
from src.product.event_normalization import normalize_event


# ── normalize_principal ────────────────────────────────────────────────────────

def test_normalize_principal_user_u_prefix():
    assert normalize_principal("User:u-zmknkp7") == "u-zmknkp7"


def test_normalize_principal_user_sa_prefix():
    assert normalize_principal("User:sa-8nwyn7") == "sa-8nwyn7"


def test_normalize_principal_already_clean():
    assert normalize_principal("u-zmknkp7") == "u-zmknkp7"


def test_normalize_principal_numeric_strips_prefix():
    # Numeric form — prefix is stripped; caller resolves via principalResourceId
    assert normalize_principal("User:3958188") == "3958188"


# ── flatten_audit: principal_normalized set correctly ──────────────────────────

def _raw_event(principal: str, principal_resource_id: str | None = None) -> dict:
    authn: dict = {"principal": principal}
    if principal_resource_id:
        authn["principalResourceId"] = principal_resource_id
    return {
        "data": {
            "serviceName": "test",
            "methodName": "kafka.CreateTopics",
            "authenticationInfo": authn,
        }
    }


def test_flatten_audit_user_u_prefix_normalized():
    flat = forwarder.flatten_audit(_raw_event("User:u-zmknkp7"))
    assert flat["principal_normalized"] == "u-zmknkp7"
    assert flat["principal"] == "User:u-zmknkp7"  # raw preserved


def test_flatten_audit_user_sa_prefix_normalized():
    flat = forwarder.flatten_audit(_raw_event("User:sa-8nwyn7"))
    assert flat["principal_normalized"] == "sa-8nwyn7"


# ── normalize_event: actor uses principal_normalized, not raw principal ────────

def _flat_event(principal: str, principal_normalized: str) -> dict:
    return {
        "id": "evt-test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "methodName": "kafka.CreateTopics",
        "principal": principal,
        "principal_normalized": principal_normalized,
        "principal_raw": principal,
    }


def test_normalize_event_prefers_principal_normalized():
    """actor must be u-zmknkp7, not User:u-zmknkp7."""
    flat = _flat_event("User:u-zmknkp7", "u-zmknkp7")
    norm = normalize_event(flat)
    assert norm["actor"] == "u-zmknkp7"


def test_normalize_event_sa_prefers_principal_normalized():
    flat = _flat_event("User:sa-8nwyn7", "sa-8nwyn7")
    norm = normalize_event(flat)
    assert norm["actor"] == "sa-8nwyn7"


def test_normalize_event_already_clean_unchanged():
    flat = _flat_event("u-zmknkp7", "u-zmknkp7")
    norm = normalize_event(flat)
    assert norm["actor"] == "u-zmknkp7"


def test_normalize_event_numeric_uses_resolved_id():
    """User:3958188 + principalResourceId=u-79z161 → actor=u-79z161."""
    flat = _flat_event("User:3958188", "u-79z161")
    norm = normalize_event(flat)
    assert norm["actor"] == "u-79z161"
