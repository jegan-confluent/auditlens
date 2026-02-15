"""
Routing module for multi-topic event routing based on criticality.
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
