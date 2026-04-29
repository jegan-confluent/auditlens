"""
Legacy routing module.

The AuditLens foundation does not use criticality-specific transport topics as
its primary contract. This module remains only for explicit compatibility
testing behind `ENABLE_LEGACY_MULTI_TOPIC_ROUTING=true`.
"""

from .topic_router import (
    TopicRouter,
    TopicConfig,
    RouterConfig,
    RoutingResult,
    RoutingStats,
    verify_prerequisites,
    create_topics_if_missing,
)

__all__ = [
    'TopicRouter',
    'TopicConfig',
    'RouterConfig',
    'RoutingResult',
    'RoutingStats',
    'verify_prerequisites',
    'create_topics_if_missing',
]
