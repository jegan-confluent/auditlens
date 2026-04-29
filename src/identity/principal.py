"""Principal normalization helpers for AuditLens foundation."""

from typing import Optional, Tuple


def normalize_principal(principal: Optional[str]) -> str:
    """Normalize principal IDs for grouping and search."""
    if not principal:
        return ""

    normalized = str(principal).strip()
    if normalized.startswith("User:"):
        normalized = normalized[5:]
    return normalized


def classify_principal_type(principal_normalized: Optional[str]) -> str:
    """Classify normalized principal IDs into stable product types."""
    if not principal_normalized:
        return "unknown"

    if principal_normalized.startswith("sa-"):
        return "service_account"
    if principal_normalized.startswith("u-"):
        return "user"
    return "unknown"


def normalize_with_type(principal: Optional[str]) -> Tuple[str, str]:
    """Normalize a principal and return its derived type."""
    normalized = normalize_principal(principal)
    return normalized, classify_principal_type(normalized)
