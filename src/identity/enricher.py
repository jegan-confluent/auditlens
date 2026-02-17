"""
Identity enrichment module for Confluent Cloud principals.

Resolves Confluent Cloud principal IDs to human-readable names/emails.

Usage:
    enricher = IdentityEnricher(cloud_api_key, cloud_api_secret)
    name = enricher.resolve("sa-abc123")  # → "payments-service (sa-abc123)"
    name = enricher.resolve("User:u-75rw9o")  # → "jegan@confluent.io (u-75rw9o)"

API Endpoints:
    - GET https://api.confluent.cloud/iam/v2/service-accounts
    - GET https://api.confluent.cloud/iam/v2/users
"""

import logging
import os
import re
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Any, List

import httpx
from cachetools import TTLCache

logger = logging.getLogger(__name__)

# Confluent Cloud API base URL
CONFLUENT_CLOUD_API_URL = "https://api.confluent.cloud"


class IdentityType(str, Enum):
    """Types of Confluent Cloud identities."""
    SERVICE_ACCOUNT = "service_account"
    USER = "user"
    IDENTITY_POOL = "identity_pool"
    UNKNOWN = "unknown"


@dataclass
class IdentityInfo:
    """Information about a resolved identity."""
    id: str
    identity_type: IdentityType
    display_name: str
    email: Optional[str] = None
    description: Optional[str] = None
    created_at: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        if self.email:
            return f"{self.display_name} ({self.id})"
        return f"{self.display_name} ({self.id})"


class IdentityEnricher:
    """
    Resolves Confluent Cloud principal IDs to human-readable information.

    Uses TTL cache to avoid hammering the API. Thread-safe.

    Args:
        api_key: Confluent Cloud API key (not Kafka API key)
        api_secret: Confluent Cloud API secret
        cache_ttl: Cache TTL in seconds (default: 1 hour)
        cache_maxsize: Maximum cache entries (default: 10000)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        cache_ttl: int = 3600,  # 1 hour
        cache_maxsize: int = 10000,
    ):
        self.api_key = api_key or os.getenv("CONFLUENT_CLOUD_API_KEY")
        self.api_secret = api_secret or os.getenv("CONFLUENT_CLOUD_API_SECRET")
        self.enabled = bool(self.api_key and self.api_secret)

        # TTL cache for resolved identities
        self._cache: TTLCache = TTLCache(maxsize=cache_maxsize, ttl=cache_ttl)
        self._lock = threading.Lock()

        # Pre-loaded identity maps (loaded on first resolve)
        self._service_accounts: Dict[str, IdentityInfo] = {}
        self._users: Dict[str, IdentityInfo] = {}
        self._identities_loaded = False
        self._load_lock = threading.Lock()

        if self.enabled:
            logger.info("IdentityEnricher initialized with Confluent Cloud API credentials")
        else:
            logger.warning(
                "IdentityEnricher disabled: CONFLUENT_CLOUD_API_KEY or "
                "CONFLUENT_CLOUD_API_SECRET not configured"
            )

    def _get_client(self) -> httpx.Client:
        """Create an authenticated HTTP client."""
        return httpx.Client(
            base_url=CONFLUENT_CLOUD_API_URL,
            auth=(self.api_key, self.api_secret),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=30.0,
        )

    def _load_identities(self) -> None:
        """Load all service accounts and users from Confluent Cloud API."""
        if self._identities_loaded or not self.enabled:
            return

        with self._load_lock:
            if self._identities_loaded:  # Double-check after acquiring lock
                return

            logger.info("Loading identities from Confluent Cloud API...")

            try:
                with self._get_client() as client:
                    # Load service accounts
                    self._load_service_accounts(client)

                    # Load users
                    self._load_users(client)

                self._identities_loaded = True
                logger.info(
                    "Loaded %d service accounts and %d users",
                    len(self._service_accounts),
                    len(self._users),
                )

            except Exception as e:
                logger.error("Failed to load identities from Confluent Cloud: %s", e)
                # Mark as loaded to avoid repeated failures
                self._identities_loaded = True

    def _load_service_accounts(self, client: httpx.Client) -> None:
        """Load all service accounts with pagination."""
        page_token = None

        while True:
            params = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token

            try:
                response = client.get("/iam/v2/service-accounts", params=params)
                response.raise_for_status()
                data = response.json()

                for sa in data.get("data", []):
                    sa_id = sa.get("id", "")
                    display_name = sa.get("display_name", sa_id)
                    description = sa.get("description", "")

                    info = IdentityInfo(
                        id=sa_id,
                        identity_type=IdentityType.SERVICE_ACCOUNT,
                        display_name=display_name,
                        description=description,
                        created_at=sa.get("metadata", {}).get("created_at"),
                        raw_data=sa,
                    )
                    self._service_accounts[sa_id] = info

                    # Also index by resource ID (e.g., "sa-abc123")
                    if sa_id.startswith("sa-"):
                        self._service_accounts[sa_id] = info

                # Check for more pages
                page_token = data.get("metadata", {}).get("next")
                if not page_token:
                    break

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.warning("Rate limited loading service accounts, stopping pagination")
                    break
                raise

    def _load_users(self, client: httpx.Client) -> None:
        """Load all users with pagination."""
        page_token = None

        while True:
            params = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token

            try:
                response = client.get("/iam/v2/users", params=params)
                response.raise_for_status()
                data = response.json()

                for user in data.get("data", []):
                    user_id = user.get("id", "")
                    email = user.get("email", "")
                    full_name = user.get("full_name", email)

                    info = IdentityInfo(
                        id=user_id,
                        identity_type=IdentityType.USER,
                        display_name=full_name if full_name else email,
                        email=email,
                        created_at=user.get("metadata", {}).get("created_at"),
                        raw_data=user,
                    )
                    self._users[user_id] = info

                    # Also index by prefixed ID (e.g., "User:u-xxxxx")
                    if user_id.startswith("u-"):
                        self._users[f"User:{user_id}"] = info

                # Check for more pages
                page_token = data.get("metadata", {}).get("next")
                if not page_token:
                    break

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.warning("Rate limited loading users, stopping pagination")
                    break
                raise

    def _normalize_principal_id(self, principal: str) -> str:
        """
        Normalize a principal ID to a standard format.

        Examples:
            "sa-abc123" → "sa-abc123"
            "User:u-75rw9o" → "u-75rw9o"
            "User:sa-abc123" → "sa-abc123"
        """
        if not principal:
            return ""

        # Remove "User:" prefix if present
        if principal.startswith("User:"):
            principal = principal[5:]

        return principal

    def _extract_principal_id(self, principal: str) -> tuple[str, IdentityType]:
        """
        Extract the principal ID and determine its type.

        Returns:
            Tuple of (normalized_id, identity_type)
        """
        normalized = self._normalize_principal_id(principal)

        if normalized.startswith("sa-"):
            return normalized, IdentityType.SERVICE_ACCOUNT
        elif normalized.startswith("u-"):
            return normalized, IdentityType.USER
        elif normalized.startswith("pool-"):
            return normalized, IdentityType.IDENTITY_POOL
        else:
            return normalized, IdentityType.UNKNOWN

    def resolve(self, principal: str) -> IdentityInfo:
        """
        Resolve a principal ID to identity information.

        Args:
            principal: The principal ID (e.g., "sa-abc123", "User:u-75rw9o")

        Returns:
            IdentityInfo with resolved details, or a basic IdentityInfo if resolution fails
        """
        if not principal:
            return IdentityInfo(
                id="unknown",
                identity_type=IdentityType.UNKNOWN,
                display_name="Unknown",
            )

        # Check cache first
        with self._lock:
            if principal in self._cache:
                return self._cache[principal]

        # Load identities if not already loaded
        if not self._identities_loaded:
            self._load_identities()

        # Extract ID and type
        normalized_id, identity_type = self._extract_principal_id(principal)

        # Look up in pre-loaded data
        info = None
        if identity_type == IdentityType.SERVICE_ACCOUNT:
            info = self._service_accounts.get(normalized_id)
        elif identity_type == IdentityType.USER:
            info = self._users.get(normalized_id) or self._users.get(principal)

        # If not found, return basic info
        if not info:
            info = IdentityInfo(
                id=normalized_id,
                identity_type=identity_type,
                display_name=normalized_id,  # Use ID as display name
            )

        # Cache the result
        with self._lock:
            self._cache[principal] = info

        return info

    def resolve_display(self, principal: str) -> str:
        """
        Resolve a principal ID to a display string.

        Args:
            principal: The principal ID (e.g., "sa-abc123", "User:u-75rw9o")

        Returns:
            Human-readable display string like "payments-service (sa-abc123)"
        """
        info = self.resolve(principal)
        return str(info)

    def batch_resolve(self, principals: List[str]) -> Dict[str, IdentityInfo]:
        """
        Resolve multiple principal IDs in batch.

        Args:
            principals: List of principal IDs

        Returns:
            Dictionary mapping principal ID to IdentityInfo
        """
        results = {}
        for principal in principals:
            results[principal] = self.resolve(principal)
        return results

    def get_all_service_accounts(self) -> List[IdentityInfo]:
        """Get all loaded service accounts."""
        if not self._identities_loaded:
            self._load_identities()
        return list(self._service_accounts.values())

    def get_all_users(self) -> List[IdentityInfo]:
        """Get all loaded users."""
        if not self._identities_loaded:
            self._load_identities()
        return list(self._users.values())

    def refresh(self) -> None:
        """Force refresh of identity cache."""
        with self._lock:
            self._cache.clear()
        with self._load_lock:
            self._service_accounts.clear()
            self._users.clear()
            self._identities_loaded = False
        self._load_identities()

    def get_stats(self) -> Dict[str, Any]:
        """Get enricher statistics."""
        return {
            "enabled": self.enabled,
            "identities_loaded": self._identities_loaded,
            "service_accounts_count": len(self._service_accounts),
            "users_count": len(self._users),
            "cache_size": len(self._cache),
            "cache_maxsize": self._cache.maxsize,
            "cache_ttl": self._cache.ttl,
        }


# Module-level singleton for convenience
_enricher_instance: Optional[IdentityEnricher] = None


def get_enricher() -> IdentityEnricher:
    """Get or create the global IdentityEnricher instance."""
    global _enricher_instance
    if _enricher_instance is None:
        _enricher_instance = IdentityEnricher()
    return _enricher_instance


def resolve_principal(principal: str) -> str:
    """
    Convenience function to resolve a principal ID to a display string.

    Args:
        principal: The principal ID (e.g., "sa-abc123", "User:u-75rw9o")

    Returns:
        Human-readable display string
    """
    return get_enricher().resolve_display(principal)
