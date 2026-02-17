"""
Confluent Cloud Admin API client.

Provides access to Confluent Cloud management APIs for:
- Environments
- Kafka clusters
- Topics
- ACLs
- Service accounts
- Users
"""

from .admin_client import (
    ConfluentCloudClient,
    Environment,
    KafkaCluster,
    Topic,
    ACL,
    get_client,
)

__all__ = [
    'ConfluentCloudClient',
    'Environment',
    'KafkaCluster',
    'Topic',
    'ACL',
    'get_client',
]
