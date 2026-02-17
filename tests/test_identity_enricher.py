"""Unit tests for Identity Enricher module."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import httpx

from src.identity.enricher import (
    IdentityEnricher,
    IdentityInfo,
    IdentityType,
    get_enricher,
    resolve_principal,
)


class TestIdentityType:
    """Tests for IdentityType enum."""

    def test_identity_type_values(self):
        """Test that identity types have expected values."""
        assert IdentityType.SERVICE_ACCOUNT.value == "service_account"
        assert IdentityType.USER.value == "user"
        assert IdentityType.IDENTITY_POOL.value == "identity_pool"
        assert IdentityType.UNKNOWN.value == "unknown"


class TestIdentityInfo:
    """Tests for IdentityInfo dataclass."""

    def test_identity_info_str_with_email(self):
        """Test string representation with email."""
        info = IdentityInfo(
            id="u-abc123",
            identity_type=IdentityType.USER,
            display_name="John Doe",
            email="john@example.com",
        )
        assert str(info) == "John Doe (u-abc123)"

    def test_identity_info_str_without_email(self):
        """Test string representation without email."""
        info = IdentityInfo(
            id="sa-def456",
            identity_type=IdentityType.SERVICE_ACCOUNT,
            display_name="payments-service",
        )
        assert str(info) == "payments-service (sa-def456)"


class TestIdentityEnricher:
    """Tests for IdentityEnricher class."""

    def test_enricher_disabled_without_credentials(self):
        """Test that enricher is disabled without credentials."""
        enricher = IdentityEnricher(api_key=None, api_secret=None)
        assert enricher.enabled is False

    def test_enricher_enabled_with_credentials(self):
        """Test that enricher is enabled with credentials."""
        enricher = IdentityEnricher(api_key="test-key", api_secret="test-secret")
        assert enricher.enabled is True

    def test_resolve_returns_basic_info_when_disabled(self):
        """Test that resolve returns basic info when enricher is disabled."""
        enricher = IdentityEnricher(api_key=None, api_secret=None)
        info = enricher.resolve("sa-abc123")

        assert info.id == "sa-abc123"
        assert info.identity_type == IdentityType.SERVICE_ACCOUNT
        assert info.display_name == "sa-abc123"

    def test_resolve_empty_principal(self):
        """Test resolving an empty principal."""
        enricher = IdentityEnricher(api_key=None, api_secret=None)
        info = enricher.resolve("")

        assert info.id == "unknown"
        assert info.identity_type == IdentityType.UNKNOWN
        assert info.display_name == "Unknown"

    def test_resolve_none_principal(self):
        """Test resolving a None principal."""
        enricher = IdentityEnricher(api_key=None, api_secret=None)
        info = enricher.resolve(None)

        assert info.id == "unknown"
        assert info.identity_type == IdentityType.UNKNOWN

    def test_normalize_principal_id_removes_user_prefix(self):
        """Test that User: prefix is removed."""
        enricher = IdentityEnricher(api_key=None, api_secret=None)
        normalized = enricher._normalize_principal_id("User:u-abc123")
        assert normalized == "u-abc123"

    def test_normalize_principal_id_service_account(self):
        """Test that service account ID is normalized correctly."""
        enricher = IdentityEnricher(api_key=None, api_secret=None)
        normalized = enricher._normalize_principal_id("sa-def456")
        assert normalized == "sa-def456"

    def test_extract_principal_id_service_account(self):
        """Test extracting service account ID."""
        enricher = IdentityEnricher(api_key=None, api_secret=None)
        id_, type_ = enricher._extract_principal_id("sa-abc123")

        assert id_ == "sa-abc123"
        assert type_ == IdentityType.SERVICE_ACCOUNT

    def test_extract_principal_id_user(self):
        """Test extracting user ID."""
        enricher = IdentityEnricher(api_key=None, api_secret=None)
        id_, type_ = enricher._extract_principal_id("u-xyz789")

        assert id_ == "u-xyz789"
        assert type_ == IdentityType.USER

    def test_extract_principal_id_user_with_prefix(self):
        """Test extracting user ID with User: prefix."""
        enricher = IdentityEnricher(api_key=None, api_secret=None)
        id_, type_ = enricher._extract_principal_id("User:u-xyz789")

        assert id_ == "u-xyz789"
        assert type_ == IdentityType.USER

    def test_extract_principal_id_identity_pool(self):
        """Test extracting identity pool ID."""
        enricher = IdentityEnricher(api_key=None, api_secret=None)
        id_, type_ = enricher._extract_principal_id("pool-abc")

        assert id_ == "pool-abc"
        assert type_ == IdentityType.IDENTITY_POOL

    def test_extract_principal_id_unknown(self):
        """Test extracting unknown ID type."""
        enricher = IdentityEnricher(api_key=None, api_secret=None)
        id_, type_ = enricher._extract_principal_id("unknown-id")

        assert id_ == "unknown-id"
        assert type_ == IdentityType.UNKNOWN

    def test_cache_behavior(self):
        """Test that cache stores and returns values."""
        enricher = IdentityEnricher(api_key=None, api_secret=None)

        # First resolve should return basic info
        info1 = enricher.resolve("sa-test")
        assert info1.id == "sa-test"

        # Second resolve should return cached value
        info2 = enricher.resolve("sa-test")
        assert info2.id == info1.id

    def test_batch_resolve(self):
        """Test batch resolve functionality."""
        enricher = IdentityEnricher(api_key=None, api_secret=None)

        principals = ["sa-abc", "u-def", "sa-ghi"]
        results = enricher.batch_resolve(principals)

        assert len(results) == 3
        assert "sa-abc" in results
        assert "u-def" in results
        assert "sa-ghi" in results

    def test_resolve_display(self):
        """Test resolve_display returns string."""
        enricher = IdentityEnricher(api_key=None, api_secret=None)
        display = enricher.resolve_display("sa-abc123")

        assert isinstance(display, str)
        assert "sa-abc123" in display

    def test_get_stats(self):
        """Test get_stats returns expected fields."""
        enricher = IdentityEnricher(api_key="key", api_secret="secret")
        stats = enricher.get_stats()

        assert "enabled" in stats
        assert "identities_loaded" in stats
        assert "cache_size" in stats
        assert "cache_maxsize" in stats
        assert "cache_ttl" in stats

    @patch('src.identity.enricher.httpx.Client')
    def test_load_service_accounts_with_mock(self, mock_client_class):
        """Test loading service accounts with mocked API."""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "sa-test123",
                    "display_name": "test-service",
                    "description": "Test service account",
                    "metadata": {"created_at": "2024-01-01T00:00:00Z"},
                }
            ],
            "metadata": {}
        }
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        enricher = IdentityEnricher(api_key="test", api_secret="secret")
        enricher._load_service_accounts(mock_client)

        assert "sa-test123" in enricher._service_accounts
        info = enricher._service_accounts["sa-test123"]
        assert info.display_name == "test-service"

    @patch('src.identity.enricher.httpx.Client')
    def test_load_users_with_mock(self, mock_client_class):
        """Test loading users with mocked API."""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "u-test456",
                    "email": "test@example.com",
                    "full_name": "Test User",
                    "metadata": {"created_at": "2024-01-01T00:00:00Z"},
                }
            ],
            "metadata": {}
        }
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        enricher = IdentityEnricher(api_key="test", api_secret="secret")
        enricher._load_users(mock_client)

        assert "u-test456" in enricher._users
        info = enricher._users["u-test456"]
        assert info.display_name == "Test User"
        assert info.email == "test@example.com"


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_get_enricher_singleton(self):
        """Test that get_enricher returns singleton."""
        with patch('src.identity.enricher._enricher_instance', None):
            enricher1 = get_enricher()
            enricher2 = get_enricher()
            # Both should be same instance
            assert enricher1 is enricher2

    def test_resolve_principal_function(self):
        """Test resolve_principal convenience function."""
        with patch('src.identity.enricher._enricher_instance', None):
            result = resolve_principal("sa-test")
            assert "sa-test" in result
