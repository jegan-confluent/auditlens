"""
Identity enrichment module for Confluent Cloud principals.

Resolves raw principal IDs (sa-xxxxx, User:u-xxxxx) to human-readable names and emails.
"""

from .enricher import IdentityEnricher, IdentityInfo, IdentityType

__all__ = ['IdentityEnricher', 'IdentityInfo', 'IdentityType']
