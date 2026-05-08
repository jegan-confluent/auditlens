"""
Confluent Cloud Admin API client.

Wraps REST API calls for cluster, topic, ACL, and identity management.

Endpoints used:
- GET /org/v2/environments
- GET /cmk/v2/clusters?environment={env_id}
- GET /kafka/v3/clusters/{cluster_id}/topics
- GET /kafka/v3/clusters/{cluster_id}/acls
- GET /iam/v2/service-accounts
- GET /iam/v2/users

Usage:
    client = ConfluentCloudClient(api_key, api_secret)
    envs = client.list_environments()
    clusters = client.list_clusters(env_id)
    topics = client.list_topics(cluster_id, cluster_api_key, cluster_api_secret)
    acls = client.list_acls(cluster_id, cluster_api_key, cluster_api_secret)
"""

import logging
import os
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from urllib.parse import parse_qs, urlparse

import httpx
from cachetools import TTLCache


def _extract_page_token(next_value: Optional[str]) -> Optional[str]:
    # Confluent list endpoints return `metadata.next` as a fully-qualified URL
    # whose `page_token` query param is the actual continuation token. Passing
    # the whole URL back as `page_token=` double-encodes it and yields 400.
    if not next_value:
        return None
    if next_value.startswith(("http://", "https://")):
        token = parse_qs(urlparse(next_value).query).get("page_token", [None])[0]
        return token or None
    return next_value

logger = logging.getLogger(__name__)

# API base URLs
CONFLUENT_CLOUD_API_URL = "https://api.confluent.cloud"


@dataclass
class Environment:
    """Confluent Cloud environment."""
    id: str
    display_name: str
    stream_governance_package: Optional[str] = None
    created_at: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None


@dataclass
class KafkaCluster:
    """Confluent Cloud Kafka cluster."""
    id: str
    display_name: str
    environment_id: str
    availability: str  # SINGLE_ZONE, MULTI_ZONE
    cloud: str  # AWS, GCP, AZURE
    region: str
    bootstrap_endpoint: Optional[str] = None
    rest_endpoint: Optional[str] = None
    created_at: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None


@dataclass
class Topic:
    """Kafka topic."""
    name: str
    cluster_id: str
    partitions_count: int = 0
    replication_factor: int = 0
    is_internal: bool = False
    configs: Dict[str, str] = field(default_factory=dict)
    raw_data: Optional[Dict[str, Any]] = None


@dataclass
class ACL:
    """Kafka ACL entry."""
    cluster_id: str
    resource_type: str  # TOPIC, GROUP, CLUSTER, TRANSACTIONAL_ID
    resource_name: str
    pattern_type: str  # LITERAL, PREFIXED
    principal: str
    host: str
    operation: str  # READ, WRITE, CREATE, DELETE, ALTER, DESCRIBE, etc.
    permission: str  # ALLOW, DENY
    raw_data: Optional[Dict[str, Any]] = None


class ConfluentCloudClient:
    """
    Client for Confluent Cloud Admin REST APIs.

    Provides methods to list environments, clusters, topics, and ACLs.
    Uses caching to reduce API calls.

    Args:
        api_key: Confluent Cloud API key
        api_secret: Confluent Cloud API secret
        cache_ttl: Cache TTL in seconds (default: 5 minutes)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        cache_ttl: int = 300,  # 5 minutes
    ):
        self.api_key = api_key or os.getenv("CONFLUENT_CLOUD_API_KEY")
        self.api_secret = api_secret or os.getenv("CONFLUENT_CLOUD_API_SECRET")
        self.enabled = bool(self.api_key and self.api_secret)

        # Cache for API responses
        self._cache: TTLCache = TTLCache(maxsize=1000, ttl=cache_ttl)
        self._lock = threading.Lock()

        # Track rate limit state
        self._rate_limit_reset: float = 0

        if self.enabled:
            logger.info("ConfluentCloudClient initialized")
        else:
            logger.warning(
                "ConfluentCloudClient disabled: CONFLUENT_CLOUD_API_KEY or "
                "CONFLUENT_CLOUD_API_SECRET not configured"
            )

    def _get_client(self, base_url: str = CONFLUENT_CLOUD_API_URL) -> httpx.Client:
        """Create an authenticated HTTP client."""
        return httpx.Client(
            base_url=base_url,
            auth=(self.api_key, self.api_secret),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=30.0,
        )

    def _handle_rate_limit(self, response: httpx.Response) -> bool:
        """
        Handle rate limit response.

        Returns True if rate limited and should retry.
        """
        if response.status_code == 429:
            # Check Retry-After header
            retry_after = response.headers.get("Retry-After", "60")
            try:
                wait_seconds = int(retry_after)
            except ValueError:
                wait_seconds = 60

            self._rate_limit_reset = time.time() + wait_seconds
            logger.warning("Rate limited, waiting %d seconds", wait_seconds)
            return True
        return False

    def _wait_for_rate_limit(self) -> None:
        """Wait if we're rate limited."""
        if time.time() < self._rate_limit_reset:
            wait_time = self._rate_limit_reset - time.time()
            if wait_time > 0:
                logger.info("Waiting %.1f seconds for rate limit reset", wait_time)
                time.sleep(min(wait_time, 60))  # Cap at 60 seconds

    def _get_cached(self, key: str) -> Optional[Any]:
        """Get a value from cache."""
        with self._lock:
            return self._cache.get(key)

    def _set_cached(self, key: str, value: Any) -> None:
        """Set a value in cache."""
        with self._lock:
            self._cache[key] = value

    def list_environments(self) -> List[Environment]:
        """
        List all environments in the organization.

        Returns:
            List of Environment objects
        """
        if not self.enabled:
            return []

        cache_key = "environments"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        self._wait_for_rate_limit()

        environments = []
        page_token = None

        try:
            with self._get_client() as client:
                while True:
                    params = {"page_size": 100}
                    if page_token:
                        params["page_token"] = page_token

                    response = client.get("/org/v2/environments", params=params)

                    if self._handle_rate_limit(response):
                        break

                    response.raise_for_status()
                    data = response.json()

                    for env in data.get("data", []):
                        environments.append(Environment(
                            id=env.get("id", ""),
                            display_name=env.get("display_name", ""),
                            stream_governance_package=env.get("stream_governance", {}).get("package"),
                            created_at=env.get("metadata", {}).get("created_at"),
                            raw_data=env,
                        ))

                    page_token = _extract_page_token(data.get("metadata", {}).get("next"))
                    if not page_token:
                        break

        except Exception as e:
            logger.error("Failed to list environments: %s", e)
            return []

        self._set_cached(cache_key, environments)
        return environments

    def list_clusters(self, environment_id: Optional[str] = None) -> List[KafkaCluster]:
        """
        List Kafka clusters, optionally filtered by environment.

        Args:
            environment_id: Optional environment ID to filter by

        Returns:
            List of KafkaCluster objects
        """
        if not self.enabled:
            return []

        cache_key = f"clusters:{environment_id or 'all'}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        self._wait_for_rate_limit()

        clusters = []
        page_token = None

        try:
            with self._get_client() as client:
                while True:
                    params = {"page_size": 100}
                    if environment_id:
                        params["environment"] = environment_id
                    if page_token:
                        params["page_token"] = page_token

                    response = client.get("/cmk/v2/clusters", params=params)

                    if self._handle_rate_limit(response):
                        break

                    response.raise_for_status()
                    data = response.json()

                    for cluster in data.get("data", []):
                        spec = cluster.get("spec", {})
                        clusters.append(KafkaCluster(
                            id=cluster.get("id", ""),
                            display_name=spec.get("display_name", ""),
                            environment_id=spec.get("environment", {}).get("id", ""),
                            availability=spec.get("availability", ""),
                            cloud=spec.get("cloud", ""),
                            region=spec.get("region", ""),
                            bootstrap_endpoint=spec.get("kafka_bootstrap_endpoint"),
                            rest_endpoint=spec.get("http_endpoint"),
                            created_at=cluster.get("metadata", {}).get("created_at"),
                            raw_data=cluster,
                        ))

                    page_token = _extract_page_token(data.get("metadata", {}).get("next"))
                    if not page_token:
                        break

        except Exception as e:
            logger.error("Failed to list clusters: %s", e)
            return []

        self._set_cached(cache_key, clusters)
        return clusters

    def list_topics(
        self,
        cluster_id: str,
        cluster_api_key: str,
        cluster_api_secret: str,
        rest_endpoint: Optional[str] = None,
    ) -> List[Topic]:
        """
        List topics in a Kafka cluster.

        Note: Requires cluster-specific API credentials, not Cloud API credentials.

        Args:
            cluster_id: Kafka cluster ID (lkc-xxxxx)
            cluster_api_key: Cluster API key
            cluster_api_secret: Cluster API secret
            rest_endpoint: Optional REST endpoint URL (auto-detected if not provided)

        Returns:
            List of Topic objects
        """
        cache_key = f"topics:{cluster_id}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        # If no REST endpoint provided, try to get it from cluster info
        if not rest_endpoint:
            clusters = self.list_clusters()
            for c in clusters:
                if c.id == cluster_id and c.rest_endpoint:
                    rest_endpoint = c.rest_endpoint
                    break

        if not rest_endpoint:
            logger.error("No REST endpoint available for cluster %s", cluster_id)
            return []

        topics = []

        try:
            with httpx.Client(
                base_url=rest_endpoint,
                auth=(cluster_api_key, cluster_api_secret),
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            ) as client:
                response = client.get(f"/kafka/v3/clusters/{cluster_id}/topics")
                response.raise_for_status()
                data = response.json()

                for topic in data.get("data", []):
                    topics.append(Topic(
                        name=topic.get("topic_name", ""),
                        cluster_id=cluster_id,
                        partitions_count=topic.get("partitions_count", 0),
                        replication_factor=topic.get("replication_factor", 0),
                        is_internal=topic.get("is_internal", False),
                        raw_data=topic,
                    ))

        except Exception as e:
            logger.error("Failed to list topics for cluster %s: %s", cluster_id, e)
            return []

        self._set_cached(cache_key, topics)
        return topics

    def list_acls(
        self,
        cluster_id: str,
        cluster_api_key: str,
        cluster_api_secret: str,
        rest_endpoint: Optional[str] = None,
    ) -> List[ACL]:
        """
        List ACLs in a Kafka cluster.

        Note: Requires cluster-specific API credentials, not Cloud API credentials.

        Args:
            cluster_id: Kafka cluster ID (lkc-xxxxx)
            cluster_api_key: Cluster API key
            cluster_api_secret: Cluster API secret
            rest_endpoint: Optional REST endpoint URL

        Returns:
            List of ACL objects
        """
        cache_key = f"acls:{cluster_id}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        # If no REST endpoint provided, try to get it from cluster info
        if not rest_endpoint:
            clusters = self.list_clusters()
            for c in clusters:
                if c.id == cluster_id and c.rest_endpoint:
                    rest_endpoint = c.rest_endpoint
                    break

        if not rest_endpoint:
            logger.error("No REST endpoint available for cluster %s", cluster_id)
            return []

        acls = []

        try:
            with httpx.Client(
                base_url=rest_endpoint,
                auth=(cluster_api_key, cluster_api_secret),
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            ) as client:
                response = client.get(f"/kafka/v3/clusters/{cluster_id}/acls")
                response.raise_for_status()
                data = response.json()

                for acl in data.get("data", []):
                    acls.append(ACL(
                        cluster_id=cluster_id,
                        resource_type=acl.get("resource_type", ""),
                        resource_name=acl.get("resource_name", ""),
                        pattern_type=acl.get("pattern_type", ""),
                        principal=acl.get("principal", ""),
                        host=acl.get("host", ""),
                        operation=acl.get("operation", ""),
                        permission=acl.get("permission", ""),
                        raw_data=acl,
                    ))

        except Exception as e:
            logger.error("Failed to list ACLs for cluster %s: %s", cluster_id, e)
            return []

        self._set_cached(cache_key, acls)
        return acls

    def get_topic_acls(
        self,
        cluster_id: str,
        cluster_api_key: str,
        cluster_api_secret: str,
        topic_name: Optional[str] = None,
        rest_endpoint: Optional[str] = None,
    ) -> Dict[str, List[ACL]]:
        """
        Get ACLs grouped by topic.

        Args:
            cluster_id: Kafka cluster ID
            cluster_api_key: Cluster API key
            cluster_api_secret: Cluster API secret
            topic_name: Optional specific topic to filter
            rest_endpoint: Optional REST endpoint URL

        Returns:
            Dictionary mapping topic name to list of ACLs
        """
        acls = self.list_acls(cluster_id, cluster_api_key, cluster_api_secret, rest_endpoint)

        topic_acls: Dict[str, List[ACL]] = {}

        for acl in acls:
            if acl.resource_type != "TOPIC":
                continue

            if topic_name and acl.resource_name != topic_name:
                # Check for prefix match if pattern type is PREFIXED
                if acl.pattern_type == "PREFIXED" and topic_name.startswith(acl.resource_name):
                    pass
                else:
                    continue

            if acl.resource_name not in topic_acls:
                topic_acls[acl.resource_name] = []
            topic_acls[acl.resource_name].append(acl)

        return topic_acls

    def get_principal_acls(
        self,
        cluster_id: str,
        cluster_api_key: str,
        cluster_api_secret: str,
        principal: Optional[str] = None,
        rest_endpoint: Optional[str] = None,
    ) -> Dict[str, List[ACL]]:
        """
        Get ACLs grouped by principal.

        Args:
            cluster_id: Kafka cluster ID
            cluster_api_key: Cluster API key
            cluster_api_secret: Cluster API secret
            principal: Optional specific principal to filter
            rest_endpoint: Optional REST endpoint URL

        Returns:
            Dictionary mapping principal to list of ACLs
        """
        acls = self.list_acls(cluster_id, cluster_api_key, cluster_api_secret, rest_endpoint)

        principal_acls: Dict[str, List[ACL]] = {}

        for acl in acls:
            if principal and acl.principal != principal:
                continue

            if acl.principal not in principal_acls:
                principal_acls[acl.principal] = []
            principal_acls[acl.principal].append(acl)

        return principal_acls

    def refresh_cache(self) -> None:
        """Clear all cached data."""
        with self._lock:
            self._cache.clear()
        logger.info("ConfluentCloudClient cache cleared")

    def get_stats(self) -> Dict[str, Any]:
        """Get client statistics."""
        return {
            "enabled": self.enabled,
            "cache_size": len(self._cache),
            "cache_maxsize": self._cache.maxsize,
            "cache_ttl": self._cache.ttl,
            "rate_limit_reset": self._rate_limit_reset,
        }


# Module-level singleton
_client_instance: Optional[ConfluentCloudClient] = None


def get_client() -> ConfluentCloudClient:
    """Get or create the global ConfluentCloudClient instance."""
    global _client_instance
    if _client_instance is None:
        _client_instance = ConfluentCloudClient()
    return _client_instance
