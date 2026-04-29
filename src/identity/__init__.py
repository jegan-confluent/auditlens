"""
Identity enrichment module for Confluent Cloud principals.

Resolves raw principal IDs (sa-xxxxx, User:u-xxxxx) to human-readable names and emails.
"""

from .enricher import IdentityEnricher, IdentityInfo, IdentityType
from .principal import normalize_principal, classify_principal_type, normalize_with_type

__all__ = [
    'IdentityEnricher',
    'IdentityInfo',
    'IdentityType',
    'normalize_principal',
    'classify_principal_type',
    'normalize_with_type',
]
