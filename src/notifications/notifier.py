"""AuditLens notification layer.

Single notifier with pluggable destinations (slack, teams, webhook), per-destination
filters, dedup, retry-with-backoff, and non-blocking daemon-thread dispatch.

The processor thread calls notify(event); HTTP work happens off-thread. notify()
catches every exception and never raises into the caller.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

import yaml


logger = logging.getLogger(__name__)


DEDUP_WINDOW_SECONDS = 300
DEDUP_PRUNE_EVERY_N_CALLS = 1000
THREAD_TIMEOUT_SECONDS = 30
RETRY_BACKOFFS_SECONDS = (2, 4, 8)
HTTP_REQUEST_TIMEOUT_SECONDS = 5

VALID_TYPES = {"slack", "teams", "webhook"}

_RISK_ORDER = {
    "informational": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


@dataclass
class NotificationDestination:
    """Single notification target loaded from notifications.yml."""

    name: str
    type: str
    webhook_url: str
    enabled: bool
    filters: dict[str, Any]


class AuditLensNotifier:
    """Filter, dedup, format, and dispatch audit events to configured destinations."""

    def __init__(self, config_path: str = "notifications.yml") -> None:
        self._config_path = config_path
        self._destinations: list[NotificationDestination] = []
        self._dedup: dict[str, float] = {}
        self._dedup_lock = threading.Lock()
        self._call_count = 0
        self._mtime: float | None = None
        self._load_config()

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------
    def has_destinations(self) -> bool:
        """True if at least one enabled destination is configured."""
        return any(d.enabled for d in self._destinations)

    def _load_config(self) -> None:
        """Load/reload notifications.yml. Safe to call at any time; never raises."""
        path = self._config_path
        if not os.path.isfile(path):
            logger.info("No notifications.yml found at %s — notifications disabled", path)
            self._destinations = []
            self._mtime = None
            return
        try:
            mtime = os.path.getmtime(path)
            with open(path, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh)
        except (yaml.YAMLError, OSError) as exc:
            logger.warning(
                "Failed to load %s (%s) — notifications disabled", path, exc
            )
            self._destinations = []
            self._mtime = None
            return

        entries: list = []
        if isinstance(raw, dict):
            value = raw.get("destinations")
            if isinstance(value, list):
                entries = value
            elif value is not None:
                logger.warning(
                    "%s: 'destinations' must be a list — disabling", path
                )
                self._destinations = []
                self._mtime = mtime
                return

        destinations: list[NotificationDestination] = []
        for entry in entries:
            dest = self._parse_destination(entry)
            if dest is not None:
                destinations.append(dest)

        self._destinations = destinations
        self._mtime = mtime
        enabled_count = sum(1 for d in destinations if d.enabled)
        logger.info(
            "Notifications loaded: %d destination(s), %d enabled",
            len(destinations),
            enabled_count,
        )

    def _parse_destination(self, entry: Any) -> NotificationDestination | None:
        if not isinstance(entry, dict):
            logger.warning("notifications.yml: destination is not a mapping — skipping")
            return None
        name = str(entry.get("name") or "unnamed")
        dtype = str(entry.get("type") or "").lower()
        webhook_url = str(entry.get("webhook_url") or "")
        enabled = bool(entry.get("enabled", True))
        filters = entry.get("filters") or {}
        if not isinstance(filters, dict):
            logger.warning(
                "notifications.yml: %s.filters must be a mapping — skipping", name
            )
            return None
        if dtype not in VALID_TYPES:
            logger.warning(
                "notifications.yml: %s has invalid type %r — skipping", name, dtype
            )
            return None
        signal_types = filters.get("signal_type")
        if not isinstance(signal_types, list) or not signal_types:
            logger.warning(
                "notifications.yml: %s.filters.signal_type is required and must be a non-empty list — skipping",
                name,
            )
            return None
        return NotificationDestination(
            name=name,
            type=dtype,
            webhook_url=webhook_url,
            enabled=enabled,
            filters=filters,
        )

    def _maybe_reload(self) -> None:
        try:
            mtime = os.path.getmtime(self._config_path)
        except OSError:
            return
        if self._mtime is None or mtime != self._mtime:
            logger.info("notifications.yml changed — reloading")
            self._load_config()

    # ------------------------------------------------------------------
    # Filter logic
    # ------------------------------------------------------------------
    def should_notify(self, event: dict, destination: NotificationDestination) -> bool:
        """Check if event matches destination filters (AND across filters)."""
        signal_type = (event.get("signal_type") or "").strip()
        if not signal_type:
            return False
        filters = destination.filters or {}
        allowed_signals = filters.get("signal_type") or []
        if signal_type not in allowed_signals:
            return False
        min_risk = filters.get("min_risk_level")
        if min_risk:
            event_risk = (event.get("risk_level") or "").strip().lower()
            event_rank = _RISK_ORDER.get(event_risk, -1)
            min_rank = _RISK_ORDER.get(str(min_risk).lower(), 0)
            if event_rank < min_rank:
                return False
        action_categories = filters.get("action_category")
        if action_categories:
            cat = event.get("action_category") or ""
            if cat not in action_categories:
                return False
        exclude_actions = filters.get("exclude_actions") or []
        if exclude_actions:
            action = event.get("action") or event.get("methodName") or ""
            if action in exclude_actions:
                return False
        return True

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------
    def _is_duplicate(self, event_fingerprint: str, destination_name: str) -> bool:
        """True if (fingerprint, dest) was sent within DEDUP_WINDOW_SECONDS."""
        key = f"{event_fingerprint}:{destination_name}"
        with self._dedup_lock:
            last = self._dedup.get(key)
            if last is None:
                return False
            return (time.time() - last) < DEDUP_WINDOW_SECONDS

    def _record_dedup(self, event_fingerprint: str, destination_name: str) -> None:
        key = f"{event_fingerprint}:{destination_name}"
        with self._dedup_lock:
            self._dedup[key] = time.time()
            self._call_count += 1
            if self._call_count >= DEDUP_PRUNE_EVERY_N_CALLS:
                self._prune_dedup_locked()
                self._call_count = 0

    def _prune_dedup_locked(self) -> None:
        cutoff = time.time() - DEDUP_WINDOW_SECONDS
        stale = [k for k, ts in self._dedup.items() if ts < cutoff]
        for k in stale:
            self._dedup.pop(k, None)

    def _event_fingerprint(self, event: dict) -> str:
        fp = event.get("event_fingerprint")
        if fp:
            return str(fp)
        return (
            f"{event.get('action', '')}"
            f"{event.get('actor', '')}"
            f"{event.get('timestamp', '')}"
        )

    # ------------------------------------------------------------------
    # Dispatch (non-blocking)
    # ------------------------------------------------------------------
    def notify(self, event: dict) -> None:
        """Fire matching destinations off-thread. Never raises."""
        try:
            self._maybe_reload()
            if not self._destinations:
                return
            fingerprint = self._event_fingerprint(event)
            for destination in self._destinations:
                if not destination.enabled:
                    continue
                if not self.should_notify(event, destination):
                    continue
                if self._is_duplicate(fingerprint, destination.name):
                    continue
                self._record_dedup(fingerprint, destination.name)
                t = threading.Thread(
                    target=self._send_with_retry,
                    args=(event, destination),
                    name=f"notify-{destination.name}",
                    daemon=True,
                )
                t.start()
        except Exception as exc:
            logger.exception("notifier.notify failed unexpectedly: %s", exc)

    def _send_with_retry(
        self, event: dict, destination: NotificationDestination
    ) -> None:
        deadline = time.monotonic() + THREAD_TIMEOUT_SECONDS
        attempts = [0] + list(RETRY_BACKOFFS_SECONDS)
        last_err: Exception | None = None
        for attempt_idx, backoff in enumerate(attempts):
            if backoff:
                time.sleep(backoff)
            if time.monotonic() >= deadline:
                logger.warning(
                    "notify %s exceeded %ds budget — abandoning",
                    destination.name,
                    THREAD_TIMEOUT_SECONDS,
                )
                return
            try:
                if self._dispatch(event, destination):
                    return
            except Exception as exc:
                last_err = exc
                logger.warning(
                    "notify %s attempt %d failed: %s",
                    destination.name,
                    attempt_idx + 1,
                    exc,
                )
        if last_err is not None:
            logger.error(
                "notify %s gave up after %d attempts: %s",
                destination.name,
                len(attempts),
                last_err,
            )

    def _dispatch(
        self, event: dict, destination: NotificationDestination
    ) -> bool:
        if destination.type == "slack":
            return self._send_slack(event, destination)
        if destination.type == "teams":
            return self._send_teams(event, destination)
        if destination.type == "webhook":
            return self._send_webhook(event, destination)
        logger.warning("notify %s: unknown type %r", destination.name, destination.type)
        return False

    def _post_json(self, url: str, payload: dict) -> bool:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(  # noqa: S310 — webhook URLs are operator-supplied
            req, timeout=HTTP_REQUEST_TIMEOUT_SECONDS
        ) as resp:
            status = getattr(resp, "status", 200)
            if 200 <= status < 300:
                return True
            raise RuntimeError(f"HTTP {status} from {url}")

    # ------------------------------------------------------------------
    # Send + format (rich formatters land in Fix 3)
    # ------------------------------------------------------------------
    def _send_slack(
        self, event: dict, destination: NotificationDestination
    ) -> bool:
        return self._post_json(destination.webhook_url, self._format_slack(event))

    def _send_teams(
        self, event: dict, destination: NotificationDestination
    ) -> bool:
        return self._post_json(destination.webhook_url, self._format_teams(event))

    def _send_webhook(
        self, event: dict, destination: NotificationDestination
    ) -> bool:
        return self._post_json(destination.webhook_url, self._format_webhook(event))

    def _format_slack(self, event: dict) -> dict:
        # Placeholder — Fix 3 replaces with Block Kit payload.
        return {"text": str(event.get("event_title") or event.get("action") or "audit event")}

    def _format_teams(self, event: dict) -> dict:
        # Placeholder — Fix 3 replaces with Adaptive Card payload.
        return {"text": str(event.get("event_title") or event.get("action") or "audit event")}

    def _format_webhook(self, event: dict) -> dict:
        # Placeholder — Fix 3 replaces with structured webhook payload.
        return {"alert_type": "audit_event"}
