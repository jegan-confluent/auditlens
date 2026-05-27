"""AuditLens notification layer.

Single notifier with pluggable destinations (slack, teams, webhook), per-destination
filters, dedup, retry-with-backoff, and non-blocking daemon-thread dispatch.

The processor thread calls notify(event); HTTP work happens off-thread. notify()
catches every exception and never raises into the caller.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


logger = logging.getLogger(__name__)


def _read_version() -> str:
    candidate = Path(__file__).resolve().parents[2] / "VERSION"
    try:
        return candidate.read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


_AUDITLENS_VERSION = _read_version()


_SIGNAL_EMOJI = {
    "action_required": "🔴",
    "attention": "🟡",
    "informational": "🟢",
    "noise": "⚪",
}


def _safe(value: Any, default: str = "—") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _resource_display(event: dict) -> str:
    for key in ("resource_display", "resource_display_short"):
        value = event.get(key)
        if value:
            return str(value)
    name = event.get("resource_name") or ""
    rtype = event.get("resource_type") or ""
    if rtype and name:
        return f"{rtype}/{name}"
    return _safe(name or rtype)


def _actor_display(event: dict) -> str:
    return _safe(event.get("actor_display_name") or event.get("actor"))


def _cluster_display(event: dict) -> str:
    name = event.get("cluster_name")
    cid = event.get("cluster_id")
    if name and cid:
        return f"{name} ({cid})"
    return _safe(name or cid)


def _environment_display(event: dict) -> str:
    name = event.get("environment_name")
    eid = event.get("environment_id")
    if name and eid:
        return f"{name} ({eid})"
    return _safe(name or eid)


def _format_timestamp(value: Any) -> str:
    """Render an ISO/epoch timestamp as 'May 10, 2026 14:32 UTC' for humans."""
    if not value:
        return "—"
    text = str(value)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    except ValueError:
        return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%b %-d, %Y %H:%M UTC")


DEDUP_WINDOW_SECONDS = 300
DEDUP_PRUNE_EVERY_N_CALLS = 1000
THREAD_TIMEOUT_SECONDS = 30
RETRY_BACKOFFS_SECONDS = (2, 4, 8)
HTTP_REQUEST_TIMEOUT_SECONDS = 5

# Rate-limit window: per-destination cap measured over a 60-second sliding
# window. A 0 limit means "unlimited" (skip rate check). When the cap is hit,
# subsequent events in the window are counted as suppressed and a single
# summary notification is delivered at window-roll, either lazily on the
# next notify() call or eagerly by the polling thread below.
RATE_LIMIT_DEFAULT = 10
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_POLL_SECONDS = 10
RATE_LIMIT_SAMPLE_CAP = 5

# Daily digest poll cadence and per-destination buffer cap. The buffer is
# bounded so a noisy day cannot exhaust memory — once full, oldest events
# are dropped (FIFO).
DIGEST_POLL_SECONDS = 60
DIGEST_BUFFER_MAX = 1000
_DIGEST_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
VALID_MODES = {"realtime", "digest"}

VALID_TYPES = {"slack", "teams", "webhook", "pagerduty"}

_RISK_ORDER = {
    "informational": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

# PagerDuty Events API v2 enqueue endpoint. Fixed per the public PD contract;
# per-destination integration_key (routing_key) selects the service.
PAGERDUTY_ENDPOINT_URL = "https://events.pagerduty.com/v2/enqueue"


def _pagerduty_severity(signal_type: str | None, risk_level: str | None) -> str:
    """Map AuditLens signal_type + risk_level to PagerDuty severity.

    action_required + critical risk → "critical"
    action_required + high risk     → "error"
    action_required (other)         → "error"  (escalated, but not "critical")
    attention                       → "warning"
    everything else                 → "info"
    """
    s = (signal_type or "").lower()
    r = (risk_level or "").lower()
    if s == "action_required":
        if r == "critical":
            return "critical"
        return "error"
    if s == "attention":
        return "warning"
    return "info"


# Placeholder markers that indicate the operator has NOT actually
# configured a webhook. These show up in our notifications.example.yml
# template and in copy-paste configs operators didn't finish editing.
# Matching any of these substrings means "this URL is not real — skip
# silently". The check fires BEFORE _validate_webhook_url, so a stale
# placeholder never produces a noisy ERROR/WARNING about SSRF or DNS
# failure; the operator sees a single DEBUG line and nothing else.
#
# Match is case-insensitive substring. `services/REPLACE` covers both
# `REPLACE_ME` and `REPLACE_DIGEST_CHANNEL` from the example file.
_PLACEHOLDER_URL_MARKERS: tuple[str, ...] = (
    "REPLACE_ME",
    "REPLACE_WITH",
    "company.webhook",
    "your-siem",
    "services/REPLACE",
)


def _is_placeholder_url(value: str) -> bool:
    """Return True when ``value`` is one of the example-file placeholders.

    Empty strings count as placeholders too — an unset webhook_url is
    just as much "unconfigured" as a REPLACE_ME literal.
    """
    if not value:
        return True
    haystack = value.lower()
    return any(marker.lower() in haystack for marker in _PLACEHOLDER_URL_MARKERS)


def _validate_webhook_url(url: str) -> None:
    """Validate webhook URL is https and does not resolve to a private/internal IP (SSRF protection)."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"Webhook URL must use https, got '{parsed.scheme}': {url}")
    host = parsed.hostname or ""
    if not host:
        raise ValueError(f"Webhook URL has no hostname: {url}")
    try:
        resolved_ip = socket.gethostbyname(host)
        ip = ipaddress.ip_address(resolved_ip)
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve webhook hostname '{host}': {exc}")
    if (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_unspecified):
        raise ValueError(
            f"Webhook URL resolves to non-public IP ({ip}) — SSRF risk. Host: {host}"
        )


@dataclass
class NotificationDestination:
    """Single notification target loaded from notifications.yml."""

    name: str
    type: str
    webhook_url: str
    enabled: bool
    filters: dict[str, Any]
    # PagerDuty Events API v2 routing key. Empty for slack/teams/webhook.
    integration_key: str = ""
    # Burst protection: cap deliveries per 60s window. 0 = unlimited.
    rate_limit_per_minute: int = RATE_LIMIT_DEFAULT
    # Delivery cadence: "realtime" (per event, default) or "digest" (one
    # summary at digest_schedule HH:MM UTC).
    mode: str = "realtime"
    digest_schedule: str = "09:00"


class AuditLensNotifier:
    """Filter, dedup, format, and dispatch audit events to configured destinations."""

    def __init__(self, config_path: str = "notifications.yml") -> None:
        self._config_path = config_path
        self._destinations: list[NotificationDestination] = []
        self._dedup: dict[tuple[str, str], float] = {}
        self._dedup_lock = threading.Lock()
        self._call_count = 0
        self._mtime: float | None = None
        # Per-destination rate-limit state: {name: {window_start, sent, suppressed, sample}}
        self._rate_lock = threading.Lock()
        self._rate_state: dict[str, dict[str, Any]] = {}
        self._rate_timer_lock = threading.Lock()
        self._rate_timer_started = False
        # Digest mode state: per-destination buffer of accepted events and
        # the YYYY-MM-DD of the last digest delivery (UTC). Both reset on
        # process restart by design.
        self._digest_lock = threading.Lock()
        self._digest_buffer: dict[str, list[dict]] = {}
        self._digest_last_sent: dict[str, str] = {}
        self._digest_timer_lock = threading.Lock()
        self._digest_timer_started = False
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
        integration_key = str(entry.get("integration_key") or "")
        # Placeholder safety net: fire BEFORE _validate_webhook_url so a
        # stale `https://hooks.slack.com/services/REPLACE_ME` (a real
        # host, so SSRF validation passes, but the path is fake — every
        # event would produce a 404 WARNING) and a stale
        # `https://company.webhook.office.com/REPLACE_ME` (host doesn't
        # resolve, so _validate_webhook_url raises ERROR) both get
        # demoted to a single DEBUG line at load time. Operators see
        # nothing in the default INFO log stream. Identical handling
        # for the PagerDuty integration_key.
        check_target = integration_key if dtype == "pagerduty" else webhook_url
        if _is_placeholder_url(check_target):
            logger.debug(
                "Skipping %s — placeholder URL not configured (%s)",
                name,
                "integration_key" if dtype == "pagerduty" else "webhook_url",
            )
            return None
        if dtype == "pagerduty":
            try:
                _validate_webhook_url(PAGERDUTY_ENDPOINT_URL)
            except ValueError as exc:
                logger.error("Skipping pagerduty destination '%s' (endpoint unreachable): %s", name, exc)
                return None
        else:
            try:
                _validate_webhook_url(webhook_url)
            except ValueError as exc:
                logger.error("Skipping destination '%s': %s", name, exc)
                return None
        signal_types = filters.get("signal_type")
        if not isinstance(signal_types, list) or not signal_types:
            logger.warning(
                "notifications.yml: %s.filters.signal_type is required and must be a non-empty list — skipping",
                name,
            )
            return None
        rate_raw = entry.get("rate_limit_per_minute", RATE_LIMIT_DEFAULT)
        try:
            rate_limit = int(rate_raw)
            if rate_limit < 0:
                raise ValueError("rate_limit_per_minute must be >= 0")
        except (TypeError, ValueError):
            logger.warning(
                "notifications.yml: %s.rate_limit_per_minute must be a non-negative int — using default %d",
                name,
                RATE_LIMIT_DEFAULT,
            )
            rate_limit = RATE_LIMIT_DEFAULT
        mode = str(entry.get("mode") or "realtime").lower()
        if mode not in VALID_MODES:
            logger.warning(
                "notifications.yml: %s.mode %r is not one of %s — using realtime",
                name,
                mode,
                sorted(VALID_MODES),
            )
            mode = "realtime"
        digest_schedule = str(entry.get("digest_schedule") or "09:00")
        if not _DIGEST_TIME_RE.match(digest_schedule):
            logger.warning(
                "notifications.yml: %s.digest_schedule %r must be HH:MM (UTC, 00:00-23:59) — using 09:00",
                name,
                digest_schedule,
            )
            digest_schedule = "09:00"
        # PagerDuty in digest mode is nonsensical (it is an alerting channel,
        # not a daily-summary channel). Demote to realtime with a warning so
        # the operator can fix the config.
        if mode == "digest" and dtype == "pagerduty":
            logger.warning(
                "notifications.yml: %s is type=pagerduty mode=digest — demoting to realtime "
                "(PagerDuty is for actionable alerts, not daily summaries)",
                name,
            )
            mode = "realtime"
        return NotificationDestination(
            name=name,
            type=dtype,
            webhook_url=webhook_url,
            enabled=enabled,
            filters=filters,
            integration_key=integration_key,
            rate_limit_per_minute=rate_limit,
            mode=mode,
            digest_schedule=digest_schedule,
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
    def _check_and_record_dedup(self, fingerprint: str, dest: str) -> bool:
        """Atomically check and record dedup. Returns True if duplicate (skip)."""
        with self._dedup_lock:
            key = (fingerprint, dest)
            last = self._dedup.get(key)
            if last and (time.time() - last) < DEDUP_WINDOW_SECONDS:
                return True
            self._dedup[key] = time.time()
            self._call_count += 1
            if self._call_count >= DEDUP_PRUNE_EVERY_N_CALLS:
                self._prune_dedup_locked()
                self._call_count = 0
            return False

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
    def send_test(self, event: dict) -> list[dict[str, Any]]:
        """Synchronously dispatch a test event to every ENABLED destination.

        Bypasses filters, dedup, rate-limiting, and the daemon-thread
        retry loop so the operator gets an accurate per-destination
        pass/fail result inline in the UI. Disabled destinations are
        reported as 'skipped' so the operator can tell whether the
        absence of delivery is by design or a config error.
        """
        try:
            self._maybe_reload()
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("notifier.send_test reload failed: %s", exc)
        results: list[dict[str, Any]] = []
        for destination in self._destinations:
            if not destination.enabled:
                results.append({
                    "destination": destination.name,
                    "type": destination.type,
                    "status": "skipped",
                    "error": None,
                    "reason": "destination disabled",
                })
                continue
            try:
                ok = self._dispatch(event, destination)
                results.append({
                    "destination": destination.name,
                    "type": destination.type,
                    "status": "sent" if ok else "error",
                    "error": None if ok else "dispatch returned False",
                })
            except Exception as exc:
                results.append({
                    "destination": destination.name,
                    "type": destination.type,
                    "status": "error",
                    "error": f"{exc.__class__.__name__}: {exc}",
                })
        return results

    def notify(self, event: dict) -> None:
        """Fire matching destinations off-thread. Never raises."""
        try:
            self._maybe_reload()
            if not self._destinations:
                return
            self._ensure_rate_timer()
            self._ensure_digest_timer()
            fingerprint = self._event_fingerprint(event)
            for destination in self._destinations:
                if not destination.enabled:
                    continue
                if not self.should_notify(event, destination):
                    continue
                if destination.mode == "digest":
                    self._append_to_digest_buffer(destination.name, event)
                    continue
                if destination.rate_limit_per_minute > 0:
                    sample_item = {
                        "actor": event.get("actor_display_name") or event.get("actor") or "",
                        "action": event.get("action") or event.get("methodName") or "",
                    }
                    allowed, pending = self._consume_rate_slot(
                        destination.name, destination.rate_limit_per_minute, sample_item
                    )
                    if pending is not None:
                        self._spawn_burst_summary(destination, pending["count"], pending["sample"])
                    if not allowed:
                        continue
                if self._check_and_record_dedup(fingerprint, destination.name):
                    continue
                t = threading.Thread(
                    target=self._send_with_retry,
                    args=(event, destination),
                    name=f"notify-{destination.name}",
                    daemon=True,
                )
                t.start()
        except Exception as exc:
            logger.exception("notifier.notify failed unexpectedly: %s", exc)

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    def _consume_rate_slot(
        self, name: str, limit: int, event_sample: dict
    ) -> tuple[bool, dict | None]:
        """Try to consume a delivery slot for destination ``name``.

        Returns (allowed, pending_summary). ``pending_summary`` is non-None
        when the window just rolled over with suppressed > 0 — the caller
        should dispatch a burst summary before continuing.
        """
        now = time.monotonic()
        with self._rate_lock:
            state = self._rate_state.get(name)
            pending_summary: dict | None = None
            if state is None or now - state["window_start"] >= RATE_LIMIT_WINDOW_SECONDS:
                if state is not None and state["suppressed"] > 0:
                    pending_summary = {
                        "count": state["suppressed"],
                        "sample": list(state["sample"]),
                    }
                state = {"window_start": now, "sent": 0, "suppressed": 0, "sample": []}
                self._rate_state[name] = state
            if state["sent"] < limit:
                state["sent"] += 1
                return True, pending_summary
            state["suppressed"] += 1
            if len(state["sample"]) < RATE_LIMIT_SAMPLE_CAP:
                state["sample"].append(event_sample)
            return False, pending_summary

    def _ensure_rate_timer(self) -> None:
        """Start the background flusher on first notify(). Idempotent."""
        with self._rate_timer_lock:
            if self._rate_timer_started:
                return
            t = threading.Thread(
                target=self._rate_timer_loop,
                name="notifier-rate-flush",
                daemon=True,
            )
            t.start()
            self._rate_timer_started = True

    def _rate_timer_loop(self) -> None:
        """Daemon: every RATE_LIMIT_POLL_SECONDS, roll over any expired windows
        and send burst summaries for destinations that had suppressed events.
        Without this, a burst followed by silence would never emit a summary.
        """
        while True:
            time.sleep(RATE_LIMIT_POLL_SECONDS)
            try:
                self._flush_expired_windows()
            except Exception as exc:
                logger.warning("rate limit flush failed: %s", exc)

    def _flush_expired_windows(self) -> None:
        now = time.monotonic()
        pending: list[tuple[str, int, list]] = []
        with self._rate_lock:
            for dest_name, state in self._rate_state.items():
                if now - state["window_start"] >= RATE_LIMIT_WINDOW_SECONDS:
                    if state["suppressed"] > 0:
                        pending.append((dest_name, state["suppressed"], list(state["sample"])))
                    state["window_start"] = now
                    state["sent"] = 0
                    state["suppressed"] = 0
                    state["sample"] = []
        if not pending:
            return
        # Resolve destinations outside the lock — _destinations is mutated
        # only by _load_config(), which itself runs under the GIL serially.
        by_name = {d.name: d for d in self._destinations}
        for dest_name, count, sample in pending:
            destination = by_name.get(dest_name)
            if destination is not None and destination.enabled:
                self._spawn_burst_summary(destination, count, sample)

    def _spawn_burst_summary(
        self, destination: NotificationDestination, count: int, sample: list
    ) -> None:
        t = threading.Thread(
            target=self._send_burst_summary,
            args=(destination, count, sample),
            name=f"notify-burst-{destination.name}",
            daemon=True,
        )
        t.start()

    def _send_burst_summary(
        self, destination: NotificationDestination, count: int, sample: list
    ) -> None:
        """Build a synthetic 'X events suppressed' event and dispatch it
        through the destination's normal formatter. Bypasses rate + dedup
        so the summary itself is never suppressed."""
        try:
            actors = sorted(
                {
                    str(item.get("actor"))
                    for item in sample
                    if isinstance(item, dict) and item.get("actor")
                }
            )[:3]
            actor_hint = ", ".join(actors) if actors else "(see logs)"
            event = {
                "signal_type": "informational",
                "event_title": f"AuditLens: {count} notification(s) suppressed",
                "event_summary": (
                    f"Rate limit hit on destination '{destination.name}'. "
                    f"{count} additional event(s) in the last minute were not delivered "
                    f"individually. Recent actors: {actor_hint}."
                ),
                "action": "rate_limit_burst",
                "actor_display_name": destination.name,
                "actor": destination.name,
                "resource_name": "rate_limit",
                "resource_type": "—",
                "risk_level": "—",
                "result": "—",
                "recommended_action": (
                    "Tune notifications.yml rate_limit_per_minute if this is frequent."
                ),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_fingerprint": f"burst:{destination.name}:{int(time.time())}",
            }
            self._send_with_retry(event, destination)
        except Exception as exc:
            logger.warning(
                "burst summary dispatch failed for %s: %s", destination.name, exc
            )

    # ------------------------------------------------------------------
    # Digest mode (daily summary)
    # ------------------------------------------------------------------
    def _append_to_digest_buffer(self, name: str, event: dict) -> None:
        """Append a copy of the relevant event fields to the destination's
        digest buffer. Bounded at DIGEST_BUFFER_MAX (FIFO drop)."""
        snapshot = {
            "signal_type": event.get("signal_type"),
            "actor": event.get("actor_display_name") or event.get("actor"),
            "action": event.get("action") or event.get("methodName"),
            "resource": _resource_display(event),
            "risk_level": event.get("risk_level"),
            "timestamp": event.get("timestamp"),
        }
        with self._digest_lock:
            buf = self._digest_buffer.setdefault(name, [])
            buf.append(snapshot)
            if len(buf) > DIGEST_BUFFER_MAX:
                # Drop oldest to keep memory bounded.
                del buf[: len(buf) - DIGEST_BUFFER_MAX]

    def _ensure_digest_timer(self) -> None:
        """Start the daily-digest polling thread lazily on first notify()."""
        with self._digest_timer_lock:
            if self._digest_timer_started:
                return
            t = threading.Thread(
                target=self._digest_loop,
                name="notifier-digest",
                daemon=True,
            )
            t.start()
            self._digest_timer_started = True

    def _digest_loop(self) -> None:
        while True:
            time.sleep(DIGEST_POLL_SECONDS)
            try:
                self._maybe_send_digests()
            except Exception as exc:
                logger.warning("digest loop failed: %s", exc)

    def _maybe_send_digests(self) -> None:
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        for destination in list(self._destinations):
            if destination.mode != "digest" or not destination.enabled:
                continue
            schedule = destination.digest_schedule
            if not _DIGEST_TIME_RE.match(schedule):
                continue  # already warned at parse time
            target_h, target_m = (int(part) for part in schedule.split(":"))
            if (now.hour, now.minute) < (target_h, target_m):
                continue
            if self._digest_last_sent.get(destination.name) == today:
                continue
            with self._digest_lock:
                events = list(self._digest_buffer.get(destination.name, []))
                self._digest_buffer[destination.name] = []
                self._digest_last_sent[destination.name] = today
            if not events:
                logger.info(
                    "Digest for %s on %s — no events buffered, marking sent",
                    destination.name,
                    today,
                )
                continue
            t = threading.Thread(
                target=self._send_digest,
                args=(destination, events, today),
                name=f"digest-{destination.name}",
                daemon=True,
            )
            t.start()

    def _send_digest(
        self,
        destination: NotificationDestination,
        events: list[dict],
        date_str: str,
    ) -> None:
        """Aggregate buffered events and dispatch the daily summary."""
        try:
            action_required = [e for e in events if e.get("signal_type") == "action_required"]
            attention = [e for e in events if e.get("signal_type") == "attention"]
            top_actors = Counter(
                str(e.get("actor") or "—") for e in action_required
            ).most_common(3)
            top_actions = Counter(
                str(e.get("action") or "—") for e in attention
            ).most_common(3)
            top_resource = Counter(
                str(e.get("resource") or "—") for e in events
            ).most_common(1)
            dashboard_url = (os.getenv("DASHBOARD_URL") or "").strip()
            if destination.type == "slack":
                payload = self._format_slack_digest(
                    date_str=date_str,
                    action_required_count=len(action_required),
                    attention_count=len(attention),
                    top_actors=top_actors,
                    top_actions=top_actions,
                    top_resource=top_resource[0] if top_resource else None,
                    dashboard_url=dashboard_url,
                )
                self._post_json(destination.webhook_url, payload)
                return
            # Non-slack digest: synthesize an informational event and route
            # through the destination's standard formatter. Less polished
            # than the Slack Block Kit version but works for teams/webhook.
            summary_parts: list[str] = [
                f"{len(action_required)} action_required",
                f"{len(attention)} attention",
            ]
            if top_actors:
                summary_parts.append(
                    "Top actors: " + ", ".join(f"{a} ({n})" for a, n in top_actors)
                )
            if top_actions:
                summary_parts.append(
                    "Top actions: " + ", ".join(f"{a} ({n})" for a, n in top_actions)
                )
            if top_resource:
                summary_parts.append(
                    f"Top resource: {top_resource[0][0]} ({top_resource[0][1]})"
                )
            if dashboard_url:
                summary_parts.append(f"Dashboard: {dashboard_url}")
            synthetic = {
                "signal_type": "informational",
                "event_title": f"AuditLens Daily Digest — {date_str}",
                "event_summary": " · ".join(summary_parts),
                "action": "daily_digest",
                "actor_display_name": destination.name,
                "actor": destination.name,
                "resource_name": "digest",
                "resource_type": "—",
                "risk_level": "—",
                "result": "—",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_fingerprint": f"digest:{destination.name}:{date_str}",
            }
            self._send_with_retry(synthetic, destination)
        except Exception as exc:
            logger.warning(
                "digest dispatch failed for %s: %s", destination.name, exc
            )

    def _format_slack_digest(
        self,
        *,
        date_str: str,
        action_required_count: int,
        attention_count: int,
        top_actors: list[tuple[str, int]],
        top_actions: list[tuple[str, int]],
        top_resource: tuple[str, int] | None,
        dashboard_url: str,
    ) -> dict:
        blocks: list[dict] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"AuditLens Daily Digest — {date_str}",
                    "emoji": False,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"🔴 *{action_required_count}* action_required  ·  "
                        f"🟡 *{attention_count}* attention"
                    ),
                },
            },
        ]
        if top_actors:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Top action_required actors:*\n"
                        + "\n".join(f"• {a} — {n}" for a, n in top_actors),
                    },
                }
            )
        if top_actions:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Top attention actions:*\n"
                        + "\n".join(f"• {a} — {n}" for a, n in top_actions),
                    },
                }
            )
        if top_resource is not None:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*Top resource affected:* {top_resource[0]} "
                            f"({top_resource[1]} event(s))"
                        ),
                    },
                }
            )
        if dashboard_url:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"<{dashboard_url}|Open AuditLens dashboard →>",
                    },
                }
            )
        return {
            "blocks": blocks,
            "text": (
                f"AuditLens Daily Digest — {date_str}: "
                f"{action_required_count} action_required, {attention_count} attention"
            ),
        }

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
        if destination.type == "pagerduty":
            return self._send_pagerduty(event, destination)
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

    def _send_pagerduty(
        self, event: dict, destination: NotificationDestination
    ) -> bool:
        return self._post_json(
            PAGERDUTY_ENDPOINT_URL,
            self._format_pagerduty(event, destination),
        )

    def _format_pagerduty(
        self, event: dict, destination: NotificationDestination
    ) -> dict:
        signal_type = (event.get("signal_type") or "informational").lower()
        severity = _pagerduty_severity(signal_type, event.get("risk_level"))
        title = _safe(
            event.get("event_title") or event.get("action"),
            default="AuditLens event",
        )
        dedup_key = str(
            event.get("event_fingerprint") or self._event_fingerprint(event)
        )
        return {
            "routing_key": destination.integration_key,
            "event_action": "trigger",
            "dedup_key": dedup_key,
            "payload": {
                # PagerDuty enforces 1024 chars on summary; truncate defensively.
                "summary": title[:1024],
                "severity": severity,
                "source": "AuditLens",
                "custom_details": {
                    "actor": _actor_display(event),
                    "action": _safe(event.get("action") or event.get("methodName")),
                    "resource": _resource_display(event),
                    "signal_type": signal_type,
                    "risk_level": _safe(event.get("risk_level")),
                    "recommended_action": _safe(event.get("recommended_action")),
                },
            },
        }

    def _format_slack(self, event: dict) -> dict:
        signal_type = (event.get("signal_type") or "informational").lower()
        emoji = _SIGNAL_EMOJI.get(signal_type, "🟢")
        title = _safe(event.get("event_title") or event.get("action"), default="Audit event")
        header_text = f"{emoji} {signal_type.upper()} — {title}"

        action = _safe(event.get("action") or event.get("methodName"))
        actor = _actor_display(event)
        resource = _resource_display(event)
        cluster = _cluster_display(event)
        environment = _environment_display(event)
        result_raw = _safe(event.get("result"))
        risk = _safe(event.get("risk_level"))
        time_str = _format_timestamp(event.get("timestamp"))

        is_failure = result_raw.lower() in {"failure", "denied", "fail", "failed", "deny"}
        result_text = f"*{result_raw}*" if is_failure else result_raw

        fields = [
            {"type": "mrkdwn", "text": f"*Action:*\n{action}"},
            {"type": "mrkdwn", "text": f"*Actor:*\n{actor}"},
            {"type": "mrkdwn", "text": f"*Resource:*\n{resource}"},
            {"type": "mrkdwn", "text": f"*Cluster:*\n{cluster}"},
            {"type": "mrkdwn", "text": f"*Environment:*\n{environment}"},
            {"type": "mrkdwn", "text": f"*Result:*\n{result_text}"},
            {"type": "mrkdwn", "text": f"*Risk:*\n{risk}"},
            {"type": "mrkdwn", "text": f"*Time:*\n{time_str}"},
        ]

        blocks: list[dict] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": header_text[:150], "emoji": True},
            },
            {"type": "section", "fields": fields},
        ]

        summary = event.get("event_summary")
        if summary:
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": str(summary)}],
                }
            )

        recommended = event.get("recommended_action")
        if recommended:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"⚡ {recommended}",
                    },
                }
            )

        return {"blocks": blocks, "text": header_text}

    def _format_teams(self, event: dict) -> dict:
        signal_type = (event.get("signal_type") or "informational").lower()
        emoji = _SIGNAL_EMOJI.get(signal_type, "🟢")
        title = _safe(event.get("event_title") or event.get("action"), default="Audit event")

        if signal_type == "action_required":
            color = "attention"
        elif signal_type == "attention":
            color = "warning"
        else:
            color = "default"

        facts = [
            {"title": "Action", "value": _safe(event.get("action") or event.get("methodName"))},
            {"title": "Actor", "value": _actor_display(event)},
            {"title": "Resource", "value": _resource_display(event)},
            {"title": "Cluster", "value": _cluster_display(event)},
            {"title": "Environment", "value": _environment_display(event)},
            {"title": "Result", "value": _safe(event.get("result"))},
            {"title": "Risk", "value": _safe(event.get("risk_level"))},
            {"title": "Time", "value": _format_timestamp(event.get("timestamp"))},
        ]

        body: list[dict] = [
            {
                "type": "TextBlock",
                "size": "Large",
                "weight": "Bolder",
                "color": color,
                "text": f"{emoji} {signal_type.upper()} — {title}",
                "wrap": True,
            },
            {"type": "FactSet", "facts": facts},
        ]

        summary = event.get("event_summary")
        if summary:
            body.append(
                {
                    "type": "TextBlock",
                    "text": str(summary),
                    "wrap": True,
                    "isSubtle": True,
                }
            )

        recommended = event.get("recommended_action")
        if recommended:
            body.append(
                {
                    "type": "TextBlock",
                    "text": f"⚡ {recommended}",
                    "wrap": True,
                    "weight": "Bolder",
                    "color": color,
                }
            )

        adaptive_card = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": body,
        }

        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": adaptive_card,
                }
            ],
        }

    def _format_webhook(self, event: dict) -> dict:
        resource_value = event.get("resource_display") or event.get("resource_display_short")
        if not resource_value:
            rtype = event.get("resource_type") or ""
            rname = event.get("resource_name") or ""
            resource_value = f"{rtype}/{rname}" if (rtype and rname) else (rname or rtype or "")

        return {
            "alert_type": "audit_event",
            "signal_type": event.get("signal_type") or "",
            "event_title": event.get("event_title") or event.get("action") or "",
            "event_summary": event.get("event_summary") or "",
            "action": event.get("action") or event.get("methodName") or "",
            "actor": event.get("actor_display_name") or event.get("actor") or "",
            "actor_id": event.get("actor") or event.get("actor_id") or "",
            "resource": resource_value,
            "resource_type": event.get("resource_type") or "",
            "cluster_id": event.get("cluster_id") or "",
            "cluster_name": event.get("cluster_name") or "",
            "environment_id": event.get("environment_id") or "",
            "environment_name": event.get("environment_name") or "",
            "result": event.get("result") or "",
            "risk_level": event.get("risk_level") or "",
            "recommended_action": event.get("recommended_action") or "",
            "timestamp": event.get("timestamp") or "",
            "event_fingerprint": event.get("event_fingerprint") or "",
            "auditlens_version": _AUDITLENS_VERSION,
        }
