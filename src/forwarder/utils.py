"""Shared utility functions used by audit_forwarder and extracted sub-modules."""

import re
from datetime import datetime, timezone


def extract_from_crn(crn, field):
    """Extract field from CRN string."""
    if not crn:
        return None
    match = re.search(f'{field}=([^/]+)', str(crn))
    return match.group(1) if match else None


def utc_now_iso() -> str:
    """Return RFC3339 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
