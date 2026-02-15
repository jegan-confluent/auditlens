"""
Classification module for audit event criticality determination.
"""

from .criticality import (
    CriticalityLevel,
    ClassificationResult,
    calculate_criticality,
    classify_event,
    get_criticality_stats,
)

from .methods import (
    CRITICAL_METHODS,
    HIGH_METHODS,
    MEDIUM_METHODS,
    SECURITY_FAILURE_STATUSES,
    AUTHENTICATION_METHODS,
    READ_ONLY_METHODS,
    get_method_category,
    is_sensitive_method,
)

__all__ = [
    # Criticality
    'CriticalityLevel',
    'ClassificationResult',
    'calculate_criticality',
    'classify_event',
    'get_criticality_stats',
    # Methods
    'CRITICAL_METHODS',
    'HIGH_METHODS',
    'MEDIUM_METHODS',
    'SECURITY_FAILURE_STATUSES',
    'AUTHENTICATION_METHODS',
    'READ_ONLY_METHODS',
    'get_method_category',
    'is_sensitive_method',
]
