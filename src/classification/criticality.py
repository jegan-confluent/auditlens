"""
Criticality Classification Logic for Confluent Audit Log Intelligence System.

This module provides the core classification logic that determines the
criticality level of audit log events based on method names, result status,
and other event attributes.
"""

from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from .methods import (
    CRITICAL_METHODS,
    HIGH_METHODS,
    MEDIUM_METHODS,
    SECURITY_FAILURE_STATUSES,
    AUTHENTICATION_METHODS,
    AUTHORIZATION_CHECK_METHODS,
    READ_ONLY_METHODS,
    get_method_category,
    is_sensitive_method,
)

SIGNAL_ONLY_METHODS = AUTHENTICATION_METHODS | AUTHORIZATION_CHECK_METHODS


class CriticalityLevel(str, Enum):
    """Criticality levels for audit events."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class ClassificationResult:
    """Result of event classification."""
    criticality: CriticalityLevel
    reason: str
    is_security_event: bool
    is_deletion: bool
    is_creation: bool
    is_modification: bool
    method_category: str
    elevated: bool  # True if criticality was elevated due to failure status
    is_signal_candidate: bool
    signal_type: Optional[str] = None


def calculate_criticality(event: Dict[str, Any]) -> ClassificationResult:
    """
    Calculate the criticality level of an audit event.

    The classification follows this priority order:
    1. Security failures (UNAUTHENTICATED, PERMISSION_DENIED) → CRITICAL
    2. Explicit denied access (granted=False) → CRITICAL
    3. Method-based classification (CRITICAL_METHODS, HIGH_METHODS, etc.)
    4. Pattern-based classification (Delete, Create, Update patterns)
    5. Default to LOW for read operations and unknown methods

    Args:
        event: Dictionary containing audit event fields

    Returns:
        ClassificationResult with criticality level and metadata
    """
    # Extract relevant fields
    method_name = event.get('methodName', '') or ''
    result_status = str(event.get('resultStatus', '') or '').upper()
    granted = event.get('granted')

    # Determine method category
    method_category = get_method_category(method_name)
    is_deletion = method_category == 'deletion'
    is_creation = method_category == 'creation'
    is_modification = method_category == 'modification'

    # Check for security events
    is_security_event = (
        result_status in SECURITY_FAILURE_STATUSES or
        granted is False or
        result_status == 'FAILURE'
    )

    elevated = False

    is_auth_signal_method = method_name in SIGNAL_ONLY_METHODS

    # Priority 1: authentication/authorization failures are signal-driven, not high-risk per event
    if result_status in SECURITY_FAILURE_STATUSES and is_auth_signal_method:
        return ClassificationResult(
            criticality=CriticalityLevel.LOW,
            reason=f"Signal-driven auth failure: {method_name} ({result_status})",
            is_security_event=True,
            is_deletion=is_deletion,
            is_creation=is_creation,
            is_modification=is_modification,
            method_category=method_category,
            elevated=False,
            is_signal_candidate=True,
            signal_type="auth_failure",
        )

    if result_status in SECURITY_FAILURE_STATUSES:
        return ClassificationResult(
            criticality=CriticalityLevel.MEDIUM,
            reason=f"Security failure: {result_status}",
            is_security_event=True,
            is_deletion=is_deletion,
            is_creation=is_creation,
            is_modification=is_modification,
            method_category=method_category,
            elevated=True,
            is_signal_candidate=True,
            signal_type="auth_failure",
        )

    # Priority 2: Denied access handling
    # Authorization check methods (mds.Authorize, etc.) are routine RBAC checks
    # and should NOT be elevated to CRITICAL when denied - denials are normal
    if granted is False:
        if method_name in AUTHORIZATION_CHECK_METHODS:
            # Routine authorization check denial - classify as MEDIUM
            return ClassificationResult(
                criticality=CriticalityLevel.LOW,
                reason=f"Authorization check denied: {method_name}",
                is_security_event=True,
                is_deletion=is_deletion,
                is_creation=is_creation,
                is_modification=is_modification,
                method_category=method_category,
                elevated=False,
                is_signal_candidate=True,
                signal_type="authz_denial",
            )
        elif method_name in CRITICAL_METHODS or method_name in HIGH_METHODS:
            # Denied access on important methods is CRITICAL
            return ClassificationResult(
                criticality=CriticalityLevel.HIGH,
                reason=f"Access denied on sensitive operation: {method_name}",
                is_security_event=True,
                is_deletion=is_deletion,
                is_creation=is_creation,
                is_modification=is_modification,
                method_category=method_category,
                elevated=False,
                is_signal_candidate=True,
                signal_type="access_denied",
            )
        else:
            # Other denied access is searchable but not high-risk per event
            return ClassificationResult(
                criticality=CriticalityLevel.LOW,
                reason=f"Access denied: {method_name}",
                is_security_event=True,
                is_deletion=is_deletion,
                is_creation=is_creation,
                is_modification=is_modification,
                method_category=method_category,
                elevated=False,
                is_signal_candidate=True,
                signal_type="access_denied",
            )

    # Priority 3: Check explicit method classifications
    if method_name in CRITICAL_METHODS:
        return ClassificationResult(
            criticality=CriticalityLevel.CRITICAL,
            reason=f"Critical method: {method_name}",
            is_security_event=is_security_event,
            is_deletion=is_deletion,
            is_creation=is_creation,
            is_modification=is_modification,
            method_category=method_category,
            elevated=False,
            is_signal_candidate=False,
        )

    if method_name in HIGH_METHODS:
        return ClassificationResult(
            criticality=CriticalityLevel.HIGH,
            reason=f"High-priority method: {method_name}",
            is_security_event=is_security_event,
            is_deletion=is_deletion,
            is_creation=is_creation,
            is_modification=is_modification,
            method_category=method_category,
            elevated=False,
            is_signal_candidate=False,
        )

    if method_name in MEDIUM_METHODS:
        return ClassificationResult(
            criticality=CriticalityLevel.MEDIUM,
            reason=f"Medium-priority method: {method_name}",
            is_security_event=is_security_event,
            is_deletion=is_deletion,
            is_creation=is_creation,
            is_modification=is_modification,
            method_category=method_category,
            elevated=False,
            is_signal_candidate=False,
        )

    # Priority 4: Pattern-based classification for unknown methods
    if is_deletion:
        # Any deletion not explicitly classified is at least HIGH
        criticality = CriticalityLevel.HIGH
        reason = f"Deletion operation: {method_name}"
    elif method_name in AUTHORIZATION_CHECK_METHODS:
        # Authorization checks (granted=True path, since granted=False handled above)
        # are routine RBAC checks - classify as LOW
        criticality = CriticalityLevel.LOW
        reason = f"Authorization check: {method_name}"
    elif is_sensitive_method(method_name):
        # Sensitive operations (API keys, ACLs, etc.) are HIGH
        criticality = CriticalityLevel.HIGH
        reason = f"Sensitive operation: {method_name}"
    elif is_creation or is_modification:
        # Creations and modifications are MEDIUM
        criticality = CriticalityLevel.MEDIUM
        reason = f"Creation/modification: {method_name}"
    elif method_name in AUTHENTICATION_METHODS:
        # Authentication events are LOW by default (high volume)
        criticality = CriticalityLevel.LOW
        reason = f"Authentication: {method_name}"
    elif method_name in READ_ONLY_METHODS:
        # Read-only operations are LOW
        criticality = CriticalityLevel.LOW
        reason = f"Read operation: {method_name}"
    else:
        # Unknown methods default to LOW
        criticality = CriticalityLevel.LOW
        reason = f"Unclassified method: {method_name}"

    return ClassificationResult(
        criticality=criticality,
        reason=reason,
        is_security_event=is_security_event,
        is_deletion=is_deletion,
        is_creation=is_creation,
        is_modification=is_modification,
        method_category=method_category,
        elevated=elevated,
        is_signal_candidate=False,
    )


def classify_event(event: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    Classify an event and return the criticality level with enrichment data.

    This is a convenience function that returns a tuple suitable for
    adding to the event before routing.

    Args:
        event: Dictionary containing audit event fields

    Returns:
        Tuple of (criticality_level_string, enrichment_dict)
    """
    result = calculate_criticality(event)

    enrichment = {
        'criticality': result.criticality.value,
        'classification_reason': result.reason,
        'is_security_event': result.is_security_event,
        'is_deletion': result.is_deletion,
        'is_creation': result.is_creation,
        'is_modification': result.is_modification,
        'method_category': result.method_category,
        'criticality_elevated': result.elevated,
        'is_signal_candidate': result.is_signal_candidate,
        'signal_type': result.signal_type,
    }

    return result.criticality.value, enrichment


def get_criticality_stats(events: list) -> Dict[str, int]:
    """
    Get statistics on criticality distribution for a list of events.

    Args:
        events: List of event dictionaries

    Returns:
        Dictionary with counts per criticality level
    """
    stats = {
        'CRITICAL': 0,
        'HIGH': 0,
        'MEDIUM': 0,
        'LOW': 0,
        'total': 0,
        'security_events': 0,
        'deletions': 0,
        'elevated': 0,
    }

    for event in events:
        result = calculate_criticality(event)
        stats[result.criticality.value] += 1
        stats['total'] += 1
        if result.is_security_event:
            stats['security_events'] += 1
        if result.is_deletion:
            stats['deletions'] += 1
        if result.elevated:
            stats['elevated'] += 1

    return stats
