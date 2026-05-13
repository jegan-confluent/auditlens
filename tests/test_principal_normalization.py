"""Tests for principal normalization used by AuditLens foundation."""

import audit_forwarder as forwarder
from src.identity import normalize_principal, classify_principal_type, normalize_with_type


def test_normalize_principal_strips_user_prefix():
    assert normalize_principal("User:sa-abc123") == "sa-abc123"


def test_normalize_principal_preserves_plain_ids():
    assert normalize_principal("u-abc123") == "u-abc123"


def test_classify_service_account():
    assert classify_principal_type("sa-abc123") == "service_account"


def test_classify_user():
    assert classify_principal_type("u-abc123") == "user"


def test_normalize_with_type_unknown():
    assert normalize_with_type("admin@example.com") == ("admin@example.com", "unknown")


def _make_event_with_principal(principal: str, principal_resource_id: str | None = None) -> dict:
    authn = {"principal": principal}
    if principal_resource_id is not None:
        authn["principalResourceId"] = principal_resource_id
    return {"data": {"serviceName": "test", "methodName": "kafka.CreateTopics", "authenticationInfo": authn}}


def test_flatten_audit_uses_principalResourceId_for_numeric_user():
    """User:3958188 + principalResourceId=u-79z161 → normalized to u-79z161."""
    evt = _make_event_with_principal("User:3958188", "u-79z161")
    flat = forwarder.flatten_audit(evt)
    assert flat["principal_normalized"] == "u-79z161"
    assert flat["principal_type"] == "user"
    assert flat["principal"] == "User:3958188"  # raw is preserved


def test_flatten_audit_no_override_when_no_principalResourceId():
    """Numeric User:NNNN without principalResourceId stays as numeric stripped form."""
    evt = _make_event_with_principal("User:3958188")
    flat = forwarder.flatten_audit(evt)
    assert flat["principal_normalized"] == "3958188"
    assert flat["principal_type"] == "unknown"


def test_flatten_audit_no_override_for_proper_user_id():
    """User:u-79z161 already has a valid Confluent ID — no principalResourceId override needed."""
    evt = _make_event_with_principal("User:u-79z161")
    flat = forwarder.flatten_audit(evt)
    assert flat["principal_normalized"] == "u-79z161"
    assert flat["principal_type"] == "user"
