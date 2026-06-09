"""Auth-failure burst detector.

Per-actor sliding-window failure counter. When an actor crosses
``count_threshold`` failures within ``window_seconds``, fires a single
notifier system alert and resets the actor's window — subsequent
failures arm a fresh window so noisy actors don't drown the channel.

Distinct from src/anomaly/rate_tracker.py:
- RateTracker emits anomalies to the audit.alerts.v1 Kafka topic for
  downstream consumers (SIEM ingestion).
- BurstDetector fires a chat-channel notification (Slack/Teams) via
  notifier.send_system_alert so on-call sees the burst immediately.

The two are complementary; both can fire on the same incident.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Protocol


logger = logging.getLogger(__name__)


class _NotifierProtocol(Protocol):
    def send_system_alert(self, title: str, body: str) -> int: ...


class BurstDetector:
    """Sliding-window failure counter with notifier dispatch on burst.

    Thread-safe. Designed to live as a singleton in the forwarder hot
    path and be hit on every auth-failure / denied event.
    """

    def __init__(
        self,
        count_threshold: int,
        window_seconds: int,
        notifier: _NotifierProtocol | None = None,
    ) -> None:
        if count_threshold < 1:
            raise ValueError("count_threshold must be >= 1")
        if window_seconds < 1:
            raise ValueError("window_seconds must be >= 1")
        self._count_threshold = count_threshold
        self._window_seconds = window_seconds
        self._notifier = notifier
        # actor -> list of monotonic timestamps (oldest first).
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    @property
    def count_threshold(self) -> int:
        return self._count_threshold

    @property
    def window_seconds(self) -> int:
        return self._window_seconds

    def record(self, actor: str, *, now: float | None = None) -> bool:
        """Record a failure for ``actor``. Return True if a burst alert
        was just dispatched (allows callers to record metrics).

        ``now`` is an injection point for deterministic tests; production
        callers should leave it unset.
        """
        if not actor:
            return False
        ts = now if now is not None else time.monotonic()
        cutoff = ts - self._window_seconds
        fired = False
        with self._lock:
            timestamps = self._failures.get(actor, [])
            # Drop timestamps older than the window. The list stays
            # bounded by count_threshold because we reset after firing.
            while timestamps and timestamps[0] < cutoff:
                timestamps.pop(0)
            timestamps.append(ts)
            if len(timestamps) >= self._count_threshold:
                fired = True
                count = len(timestamps)
                # Reset BEFORE dispatch so a slow notifier call doesn't
                # widen the window for re-entrant calls on the same actor.
                self._failures[actor] = []
            else:
                self._failures[actor] = timestamps
                count = 0
        if fired:
            self._dispatch(actor, count)
        return fired

    def _dispatch(self, actor: str, count: int) -> None:
        if self._notifier is None:
            return
        title = "Auth failure burst detected"
        body = (
            f"{actor} has {count} auth failures in the last "
            f"{self._window_seconds}s (threshold {self._count_threshold}). "
            f"signal_reason=auth_burst"
        )
        try:
            sent = self._notifier.send_system_alert(title, body)
            logger.warning(
                "auth_burst alert fired actor=%s count=%d destinations=%d",
                actor,
                count,
                sent,
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("auth_burst dispatch failed actor=%s: %s", actor, exc)

    def actor_count(self, actor: str) -> int:
        """Return the current windowed failure count for ``actor`` (test helper)."""
        with self._lock:
            return len(self._failures.get(actor, []))
