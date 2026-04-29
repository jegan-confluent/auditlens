"""Tests for principal normalization used by AuditLens foundation."""

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
