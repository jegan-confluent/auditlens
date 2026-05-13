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
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Any, List
from urllib.parse import parse_qs, urlparse

import httpx
from cachetools import TTLCache


def _extract_page_token(next_value: Optional[str]) -> Optional[str]:
    # Confluent's IAM/v2 list endpoints return `metadata.next` as a fully-qualified
    # URL containing the next page's `page_token` query param. Passing that whole
    # URL back in as `page_token=` double-encodes it and produces 400 Bad Request.
    if not next_value:
        return None
    if next_value.startswith(("http://", "https://")):
        token = parse_qs(urlparse(next_value).query).get("page_token", [None])[0]
        return token or None
    return next_value

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
        refresh_interval_seconds: int = 55 * 60,  # 55 min — well under TTL
    ):
        self.api_key = api_key or os.getenv("CONFLUENT_CLOUD_API_KEY")
        self.api_secret = api_secret or os.getenv("CONFLUENT_CLOUD_API_SECRET")
        self.enabled = bool(self.api_key and self.api_secret)

        # TTL cache for resolved identities
        self._cache: TTLCache = TTLCache(maxsize=cache_maxsize, ttl=cache_ttl)
        self._lock = threading.RLock()

        # Pre-loaded identity maps. The hot path (resolve()) NEVER blocks on
        # populating these — a daemon thread runs the API calls. Until the
        # first refresh completes, resolve() returns a basic IdentityInfo
        # with display_name=raw_id; downstream renderers detect that with the
        # display!=raw_id check and show the raw id in italic-grey.
        self._service_accounts: Dict[str, IdentityInfo] = {}
        self._users: Dict[str, IdentityInfo] = {}
        self._identities_loaded = False
        self._load_lock = threading.Lock()
        self._refresh_interval_seconds = max(60, int(refresh_interval_seconds))
        self._refresh_thread: Optional[threading.Thread] = None
        self._refresh_thread_started = threading.Event()
        self._last_refresh_at: Optional[float] = None
        self._last_refresh_error: Optional[str] = None
        self._last_refresh_partial: bool = False
        self._stop_event = threading.Event()

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
        """Synchronously load identities once. Kept for backwards
        compatibility (tests + manual ``refresh()`` callers); the runtime
        path now uses ``start_background_refresh()`` which never blocks the
        consume loop on the 11 sequential HTTP requests this performs."""
        if self._identities_loaded or not self.enabled:
            return

        with self._load_lock:
            if self._identities_loaded:  # Double-check after acquiring lock
                return

            logger.info("Loading identities from Confluent Cloud API...")

            try:
                service_accounts, users = self._fetch_all_identities()
                with self._lock:
                    self._service_accounts = service_accounts
                    self._users = users
                self._identities_loaded = True
                self._last_refresh_at = time.time()
                self._last_refresh_error = None
                logger.info(
                    "Loaded %d service accounts and %d users",
                    len(service_accounts),
                    len(users),
                )

            except Exception as e:
                logger.error("Failed to load identities from Confluent Cloud: %s", e)
                self._last_refresh_error = str(e)
                # Mark as loaded to avoid repeated failures from lazy callers.
                self._identities_loaded = True

    def _fetch_all_identities(self) -> tuple[Dict[str, IdentityInfo], Dict[str, IdentityInfo]]:
        """Fetch all SAs and users from Confluent Cloud into NEW dicts.

        The dicts are returned to the caller for atomic swap; nothing on
        ``self`` is mutated here. That means a refresh failure midway
        through cannot leave the live cache half-replaced.
        """
        self._last_refresh_partial = False
        service_accounts: Dict[str, IdentityInfo] = {}
        users: Dict[str, IdentityInfo] = {}
        with self._get_client() as client:
            self._load_service_accounts_into(client, service_accounts)
            self._load_users_into(client, users)
        return service_accounts, users

    def start_background_refresh(self, *, initial_load_async: bool = True) -> None:
        """Kick off the background refresh thread.

        Idempotent — calling this more than once is a no-op. The very
        first refresh runs INSIDE the daemon thread by default so the
        forwarder's startup path doesn't pay the 6-8 s identity-load
        cost. Tests that need synchronous state can call
        ``start_background_refresh(initial_load_async=False)``.
        """
        if not self.enabled:
            return
        if self._refresh_thread_started.is_set():
            return
        self._refresh_thread_started.set()

        def loop() -> None:
            # Initial load.
            try:
                service_accounts, users = self._fetch_all_identities()
                with self._lock:
                    self._service_accounts = service_accounts
                    self._users = users
                self._identities_loaded = True
                self._last_refresh_at = time.time()
                if self._last_refresh_partial:
                    self._last_refresh_error = "partial load: rate limited during IAM pagination"
                    logger.warning("Identity cache partially loaded (rate limited during pagination)")
                else:
                    self._last_refresh_error = None
                    logger.info(
                        "Identity cache loaded: %d service accounts, %d users",
                        len(service_accounts),
                        len(users),
                    )
            except Exception as exc:
                self._last_refresh_error = str(exc)
                logger.warning("Initial identity cache load failed; will retry on schedule: %s", exc)
                # Mark as loaded so resolve() doesn't fall back to the legacy
                # blocking lazy-load path.
                self._identities_loaded = True

            while not self._stop_event.is_set():
                self._stop_event.wait(timeout=self._refresh_interval_seconds)
                if self._stop_event.is_set():
                    break
                try:
                    service_accounts, users = self._fetch_all_identities()
                    with self._lock:
                        self._service_accounts = service_accounts
                        self._users = users
                        # Drop the per-resolve TTL cache so resolve() returns
                        # the freshly-fetched names rather than serving stale
                        # entries until their individual TTL ticks over.
                        self._cache.clear()
                    self._last_refresh_at = time.time()
                    if self._last_refresh_partial:
                        self._last_refresh_error = "partial load: rate limited during IAM pagination"
                        logger.warning("Identity cache partially refreshed (rate limited during pagination)")
                    else:
                        self._last_refresh_error = None
                        logger.info(
                            "Identity cache refreshed: %d service accounts, %d users",
                            len(service_accounts),
                            len(users),
                        )
                except Exception as exc:
                    self._last_refresh_error = str(exc)
                    logger.warning("Identity cache refresh failed (keeping old cache): %s", exc)

        if not initial_load_async:
            # Synchronous initial load for tests; subsequent refreshes still
            # happen in the daemon.
            try:
                service_accounts, users = self._fetch_all_identities()
                with self._lock:
                    self._service_accounts = service_accounts
                    self._users = users
                self._identities_loaded = True
                self._last_refresh_at = time.time()
                if self._last_refresh_partial:
                    self._last_refresh_error = "partial load: rate limited during IAM pagination"
            except Exception as exc:
                self._last_refresh_error = str(exc)
                logger.warning("Synchronous initial identity load failed: %s", exc)
                self._identities_loaded = True

            def loop_post_initial() -> None:
                while not self._stop_event.is_set():
                    self._stop_event.wait(timeout=self._refresh_interval_seconds)
                    if self._stop_event.is_set():
                        break
                    try:
                        service_accounts, users = self._fetch_all_identities()
                        with self._lock:
                            self._service_accounts = service_accounts
                            self._users = users
                            self._cache.clear()
                        self._last_refresh_at = time.time()
                        if self._last_refresh_partial:
                            self._last_refresh_error = "partial load: rate limited during IAM pagination"
                        else:
                            self._last_refresh_error = None
                    except Exception as exc:
                        self._last_refresh_error = str(exc)
                        logger.warning("Identity cache refresh failed: %s", exc)

            self._refresh_thread = threading.Thread(target=loop_post_initial, daemon=True, name="auditlens-identity-refresh")
        else:
            self._refresh_thread = threading.Thread(target=loop, daemon=True, name="auditlens-identity-refresh")
        self._refresh_thread.start()

    def _load_service_accounts_into(self, client: httpx.Client, target: Dict[str, IdentityInfo]) -> None:
        """Load all service accounts with pagination into ``target``."""
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
                    target[sa_id] = info

                    # Also index by resource ID (e.g., "sa-abc123")
                    if sa_id.startswith("sa-"):
                        target[sa_id] = info

                # Check for more pages
                page_token = _extract_page_token(data.get("metadata", {}).get("next"))
                if not page_token:
                    break

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.warning("Rate limited loading service accounts, stopping pagination")
                    self._last_refresh_partial = True
                    break
                raise

    # Backwards-compat shims for callers that still reference the old methods
    # (e.g. older tests). They write into self._service_accounts / self._users
    # the way the legacy code did.
    def _load_service_accounts(self, client: httpx.Client) -> None:
        self._load_service_accounts_into(client, self._service_accounts)

    def _load_users_into(self, client: httpx.Client, target: Dict[str, IdentityInfo]) -> None:
        """Load all users with pagination into ``target``."""
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
                    target[user_id] = info

                    # Also index by prefixed ID (e.g., "User:u-xxxxx")
                    if user_id.startswith("u-"):
                        target[f"User:{user_id}"] = info

                # Check for more pages
                page_token = _extract_page_token(data.get("metadata", {}).get("next"))
                if not page_token:
                    break

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.warning("Rate limited loading users, stopping pagination")
                    self._last_refresh_partial = True
                    break
                raise

    def _load_users(self, client: httpx.Client) -> None:
        self._load_users_into(client, self._users)

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

        Hot path; MUST NOT block on network I/O. The identity dicts are
        populated by the background-refresh thread (see
        ``start_background_refresh``). If the cache hasn't been primed yet
        — first ~1 s of process lifetime, or after a refresh failure with
        no prior successful load — a basic IdentityInfo with
        ``display_name=raw_id`` is returned and downstream code displays
        the raw id in the unenriched style.

        Tests that expect the legacy lazy-load behaviour can call
        ``_load_identities()`` directly before invoking ``resolve()``.

        Args:
            principal: The principal ID (e.g., "sa-abc123", "User:u-75rw9o")

        Returns:
            IdentityInfo with resolved details, or a basic IdentityInfo if
            resolution fails / the cache hasn't been loaded yet.
        """
        if not principal:
            return IdentityInfo(
                id="unknown",
                identity_type=IdentityType.UNKNOWN,
                display_name="Unknown",
            )

        with self._lock:
            cached = self._cache.get(principal)
            if cached is not None:
                return cached

            # Lazy-load fallback for callers (tests, manual scripts) that
            # construct an enricher and call resolve() without ever invoking
            # start_background_refresh. The runtime path always primes via
            # start_background_refresh, so this branch is cold in production
            # — but keeping it preserves the historical contract.
            if not self._identities_loaded and not self._refresh_thread_started.is_set():
                # Release the lock before doing network I/O.
                pass
            else:
                normalized_id, identity_type = self._extract_principal_id(principal)
                info = None
                if identity_type == IdentityType.SERVICE_ACCOUNT:
                    info = self._service_accounts.get(normalized_id)
                elif identity_type == IdentityType.USER:
                    info = self._users.get(normalized_id) or self._users.get(principal)
                if not info:
                    info = IdentityInfo(
                        id=normalized_id,
                        identity_type=identity_type,
                        display_name=normalized_id,
                    )
                self._cache[principal] = info
                return info

        # Lazy-load fallback path (no background refresher started).
        if not self._identities_loaded:
            self._load_identities()

        normalized_id, identity_type = self._extract_principal_id(principal)
        info = None
        if identity_type == IdentityType.SERVICE_ACCOUNT:
            info = self._service_accounts.get(normalized_id)
        elif identity_type == IdentityType.USER:
            info = self._users.get(normalized_id) or self._users.get(principal)
        if not info:
            info = IdentityInfo(
                id=normalized_id,
                identity_type=identity_type,
                display_name=normalized_id,
            )
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

    def stop(self, timeout: float = 2.0) -> None:
        """Signal the background refresh thread to stop and wait briefly for it to exit."""
        self._stop_event.set()
        if self._refresh_thread is not None and self._refresh_thread.is_alive():
            self._refresh_thread.join(timeout=timeout)

    def refresh(self) -> None:
        """Force refresh of identity cache."""
        with self._lock:
            self._cache.clear()
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
            "refresh_partial": self._last_refresh_partial,
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
