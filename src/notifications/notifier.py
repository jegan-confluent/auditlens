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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
        self._dedup: dict[tuple[str, str], float] = {}
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
