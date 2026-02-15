"""
Aggregation module for Confluent Audit Log Intelligence System.

Provides intelligent aggregation of high-volume events into actionable alerts.
"""

from .denial_aggregator import (
    DenialAggregator,
    AggregatorConfig,
    AggregatedDenialAlert,
    DenialBucket,
)

__all__ = [
    'DenialAggregator',
    'AggregatorConfig',
    'AggregatedDenialAlert',
    'DenialBucket',
]
