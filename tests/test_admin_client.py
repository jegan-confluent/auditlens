"""Unit tests for Confluent Cloud Admin Client module."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import time
import httpx

from src.confluent_api.admin_client import (
    ConfluentCloudClient,
    Environment,
    KafkaCluster,
    Topic,
    ACL,
    get_client,
)


class TestDataClasses:
    """Tests for dataclass definitions."""

    def test_environment_dataclass(self):
        """Test Environment dataclass creation."""
        env = Environment(
            id="env-abc123",
            display_name="production",
            stream_governance_package="ESSENTIALS",
            created_at="2024-01-01T00:00:00Z",
        )
        assert env.id == "env-abc123"
        assert env.display_name == "production"
        assert env.stream_governance_package == "ESSENTIALS"

    def test_kafka_cluster_dataclass(self):
        """Test KafkaCluster dataclass creation."""
        cluster = KafkaCluster(
            id="lkc-abc123",
            display_name="main-cluster",
            environment_id="env-xyz",
            availability="MULTI_ZONE",
            cloud="AWS",
            region="us-west-2",
            bootstrap_endpoint="pkc-abc.us-west-2.aws.confluent.cloud:9092",
            rest_endpoint="https://pkc-abc.us-west-2.aws.confluent.cloud:443",
        )
        assert cluster.id == "lkc-abc123"
        assert cluster.cloud == "AWS"
        assert cluster.availability == "MULTI_ZONE"

    def test_topic_dataclass(self):
        """Test Topic dataclass creation."""
        topic = Topic(
            name="payments-events",
            cluster_id="lkc-abc123",
            partitions_count=6,
            replication_factor=3,
            is_internal=False,
        )
        assert topic.name == "payments-events"
        assert topic.partitions_count == 6
        assert topic.is_internal is False

    def test_acl_dataclass(self):
        """Test ACL dataclass creation."""
        acl = ACL(
            cluster_id="lkc-abc123",
            resource_type="TOPIC",
            resource_name="payments-events",
            pattern_type="LITERAL",
            principal="User:sa-abc123",
            host="*",
            operation="READ",
            permission="ALLOW",
        )
        assert acl.resource_type == "TOPIC"
        assert acl.principal == "User:sa-abc123"
        assert acl.permission == "ALLOW"


class TestConfluentCloudClient:
    """Tests for ConfluentCloudClient class."""

    def test_client_disabled_without_credentials(self):
        """Test that client is disabled without credentials."""
        client = ConfluentCloudClient(api_key=None, api_secret=None)
        assert client.enabled is False

    def test_client_enabled_with_credentials(self):
        """Test that client is enabled with credentials."""
        client = ConfluentCloudClient(api_key="test-key", api_secret="test-secret")
        assert client.enabled is True

    def test_list_environments_disabled(self):
        """Test that list_environments returns empty when disabled."""
        client = ConfluentCloudClient(api_key=None, api_secret=None)
        result = client.list_environments()
        assert result == []

    def test_list_clusters_disabled(self):
        """Test that list_clusters returns empty when disabled."""
        client = ConfluentCloudClient(api_key=None, api_secret=None)
        result = client.list_clusters()
        assert result == []

    def test_cache_behavior(self):
        """Test that cache stores values."""
        client = ConfluentCloudClient(api_key="test", api_secret="secret")

        # Set a value in cache
        client._set_cached("test_key", "test_value")

        # Retrieve it
        result = client._get_cached("test_key")
        assert result == "test_value"

    def test_cache_miss(self):
        """Test that cache returns None for missing keys."""
        client = ConfluentCloudClient(api_key="test", api_secret="secret")

        result = client._get_cached("nonexistent_key")
        assert result is None

    def test_get_stats(self):
        """Test get_stats returns expected fields."""
        client = ConfluentCloudClient(api_key="key", api_secret="secret")
        stats = client.get_stats()

        assert "enabled" in stats
        assert "cache_size" in stats
        assert "cache_maxsize" in stats
        assert "cache_ttl" in stats
        assert "rate_limit_reset" in stats
        assert stats["enabled"] is True

    def test_refresh_cache(self):
        """Test that refresh_cache clears all cached data."""
        client = ConfluentCloudClient(api_key="test", api_secret="secret")

        # Add some items to cache
        client._set_cached("key1", "value1")
        client._set_cached("key2", "value2")

        # Refresh cache
        client.refresh_cache()

        # Verify cache is empty
        assert client._get_cached("key1") is None
        assert client._get_cached("key2") is None


class TestRateLimiting:
    """Tests for rate limit handling."""

    def test_handle_rate_limit_429(self):
        """Test that 429 response triggers rate limit handling."""
        client = ConfluentCloudClient(api_key="test", api_secret="secret")

        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "30"}

        result = client._handle_rate_limit(mock_response)

        assert result is True
        assert client._rate_limit_reset > time.time()

    def test_handle_rate_limit_200(self):
        """Test that 200 response does not trigger rate limiting."""
        client = ConfluentCloudClient(api_key="test", api_secret="secret")

        mock_response = Mock()
        mock_response.status_code = 200

        result = client._handle_rate_limit(mock_response)

        assert result is False

    def test_handle_rate_limit_invalid_retry_after(self):
        """Test rate limit handling with invalid Retry-After header."""
        client = ConfluentCloudClient(api_key="test", api_secret="secret")

        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "invalid"}

        result = client._handle_rate_limit(mock_response)

        assert result is True
        # Should default to 60 seconds
        assert client._rate_limit_reset > time.time()


class TestPagination:
    """Tests for pagination handling."""

    @patch.object(ConfluentCloudClient, '_get_client')
    def test_list_environments_pagination(self, mock_get_client):
        """Test that list_environments handles pagination."""
        mock_client = MagicMock()
        mock_get_client.return_value.__enter__.return_value = mock_client

        # First page
        first_response = MagicMock()
        first_response.json.return_value = {
            "data": [
                {"id": "env-1", "display_name": "env1", "metadata": {}},
                {"id": "env-2", "display_name": "env2", "metadata": {}},
            ],
            "metadata": {"next": "page_token_123"},
        }
        first_response.status_code = 200
        first_response.raise_for_status = MagicMock()

        # Second page
        second_response = MagicMock()
        second_response.json.return_value = {
            "data": [
                {"id": "env-3", "display_name": "env3", "metadata": {}},
            ],
            "metadata": {},  # No next token
        }
        second_response.status_code = 200
        second_response.raise_for_status = MagicMock()

        mock_client.get.side_effect = [first_response, second_response]

        client = ConfluentCloudClient(api_key="test", api_secret="secret")
        environments = client.list_environments()

        assert len(environments) == 3
        assert environments[0].id == "env-1"
        assert environments[2].id == "env-3"
        assert mock_client.get.call_count == 2

    @patch.object(ConfluentCloudClient, '_get_client')
    def test_list_clusters_with_environment_filter(self, mock_get_client):
        """Test that list_clusters filters by environment."""
        mock_client = MagicMock()
        mock_get_client.return_value.__enter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "lkc-123",
                    "spec": {
                        "display_name": "cluster1",
                        "environment": {"id": "env-abc"},
                        "availability": "MULTI_ZONE",
                        "cloud": "AWS",
                        "region": "us-west-2",
                    },
                    "metadata": {},
                },
            ],
            "metadata": {},
        }
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        client = ConfluentCloudClient(api_key="test", api_secret="secret")
        clusters = client.list_clusters(environment_id="env-abc")

        assert len(clusters) == 1
        assert clusters[0].id == "lkc-123"

        # Verify environment filter was passed
        call_args = mock_client.get.call_args
        assert "environment" in call_args.kwargs.get("params", {})


class TestTopicListing:
    """Tests for topic listing."""

    def test_list_topics_no_rest_endpoint(self):
        """Test that list_topics returns empty without REST endpoint."""
        client = ConfluentCloudClient(api_key="test", api_secret="secret")

        # Mock list_clusters to return cluster without REST endpoint
        with patch.object(client, 'list_clusters', return_value=[
            KafkaCluster(
                id="lkc-123",
                display_name="test",
                environment_id="env-1",
                availability="SINGLE_ZONE",
                cloud="AWS",
                region="us-west-2",
                rest_endpoint=None,  # No REST endpoint
            )
        ]):
            result = client.list_topics("lkc-123", "key", "secret")
            assert result == []

    @patch('src.confluent_api.admin_client.httpx.Client')
    def test_list_topics_success(self, mock_httpx_client):
        """Test successful topic listing."""
        mock_client = MagicMock()
        mock_httpx_client.return_value.__enter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "topic_name": "payments-events",
                    "partitions_count": 6,
                    "replication_factor": 3,
                    "is_internal": False,
                },
                {
                    "topic_name": "_schemas",
                    "partitions_count": 1,
                    "replication_factor": 3,
                    "is_internal": True,
                },
            ],
        }
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        client = ConfluentCloudClient(api_key="test", api_secret="secret")
        topics = client.list_topics(
            "lkc-123",
            "cluster-key",
            "cluster-secret",
            rest_endpoint="https://pkc-test.confluent.cloud"
        )

        assert len(topics) == 2
        assert topics[0].name == "payments-events"
        assert topics[0].partitions_count == 6
        assert topics[1].is_internal is True


class TestACLListing:
    """Tests for ACL listing."""

    @patch('src.confluent_api.admin_client.httpx.Client')
    def test_list_acls_success(self, mock_httpx_client):
        """Test successful ACL listing."""
        mock_client = MagicMock()
        mock_httpx_client.return_value.__enter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "resource_type": "TOPIC",
                    "resource_name": "payments-events",
                    "pattern_type": "LITERAL",
                    "principal": "User:sa-abc123",
                    "host": "*",
                    "operation": "READ",
                    "permission": "ALLOW",
                },
                {
                    "resource_type": "TOPIC",
                    "resource_name": "payments-",
                    "pattern_type": "PREFIXED",
                    "principal": "User:sa-def456",
                    "host": "*",
                    "operation": "WRITE",
                    "permission": "ALLOW",
                },
            ],
        }
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        client = ConfluentCloudClient(api_key="test", api_secret="secret")
        acls = client.list_acls(
            "lkc-123",
            "cluster-key",
            "cluster-secret",
            rest_endpoint="https://pkc-test.confluent.cloud"
        )

        assert len(acls) == 2
        assert acls[0].resource_type == "TOPIC"
        assert acls[0].principal == "User:sa-abc123"
        assert acls[1].pattern_type == "PREFIXED"

    @patch('src.confluent_api.admin_client.httpx.Client')
    def test_get_topic_acls(self, mock_httpx_client):
        """Test getting ACLs grouped by topic."""
        mock_client = MagicMock()
        mock_httpx_client.return_value.__enter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "resource_type": "TOPIC",
                    "resource_name": "payments-events",
                    "pattern_type": "LITERAL",
                    "principal": "User:sa-abc123",
                    "host": "*",
                    "operation": "READ",
                    "permission": "ALLOW",
                },
                {
                    "resource_type": "GROUP",  # Not a TOPIC
                    "resource_name": "consumer-group",
                    "pattern_type": "LITERAL",
                    "principal": "User:sa-abc123",
                    "host": "*",
                    "operation": "READ",
                    "permission": "ALLOW",
                },
            ],
        }
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        client = ConfluentCloudClient(api_key="test", api_secret="secret")
        topic_acls = client.get_topic_acls(
            "lkc-123",
            "cluster-key",
            "cluster-secret",
            rest_endpoint="https://pkc-test.confluent.cloud"
        )

        # Should only include TOPIC ACLs
        assert "payments-events" in topic_acls
        assert len(topic_acls["payments-events"]) == 1
        assert "consumer-group" not in topic_acls

    @patch('src.confluent_api.admin_client.httpx.Client')
    def test_get_principal_acls(self, mock_httpx_client):
        """Test getting ACLs grouped by principal."""
        mock_client = MagicMock()
        mock_httpx_client.return_value.__enter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "resource_type": "TOPIC",
                    "resource_name": "topic1",
                    "pattern_type": "LITERAL",
                    "principal": "User:sa-abc123",
                    "host": "*",
                    "operation": "READ",
                    "permission": "ALLOW",
                },
                {
                    "resource_type": "TOPIC",
                    "resource_name": "topic2",
                    "pattern_type": "LITERAL",
                    "principal": "User:sa-abc123",
                    "host": "*",
                    "operation": "WRITE",
                    "permission": "ALLOW",
                },
            ],
        }
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        client = ConfluentCloudClient(api_key="test", api_secret="secret")
        principal_acls = client.get_principal_acls(
            "lkc-123",
            "cluster-key",
            "cluster-secret",
            rest_endpoint="https://pkc-test.confluent.cloud"
        )

        assert "User:sa-abc123" in principal_acls
        assert len(principal_acls["User:sa-abc123"]) == 2


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_get_client_singleton(self):
        """Test that get_client returns singleton."""
        with patch('src.confluent_api.admin_client._client_instance', None):
            client1 = get_client()
            client2 = get_client()
            # Both should be same instance
            assert client1 is client2


class TestErrorHandling:
    """Tests for error handling."""

    @patch.object(ConfluentCloudClient, '_get_client')
    def test_list_environments_api_error(self, mock_get_client):
        """Test that API errors are handled gracefully."""
        mock_client = MagicMock()
        mock_get_client.return_value.__enter__.return_value = mock_client
        mock_client.get.side_effect = httpx.HTTPError("Connection failed")

        client = ConfluentCloudClient(api_key="test", api_secret="secret")
        result = client.list_environments()

        # Should return empty list on error
        assert result == []

    @patch('src.confluent_api.admin_client.httpx.Client')
    def test_list_topics_api_error(self, mock_httpx_client):
        """Test that topic listing handles API errors."""
        mock_client = MagicMock()
        mock_httpx_client.return_value.__enter__.return_value = mock_client
        mock_client.get.side_effect = httpx.HTTPError("Connection failed")

        client = ConfluentCloudClient(api_key="test", api_secret="secret")
        result = client.list_topics(
            "lkc-123",
            "key",
            "secret",
            rest_endpoint="https://pkc-test.confluent.cloud"
        )

        # Should return empty list on error
        assert result == []
