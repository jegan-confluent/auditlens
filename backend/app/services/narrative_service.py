"""Narrative service — builds a plain-English story of actor activity."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.app.db.models import AuditEvent
from backend.app.services.event_service import parse_time_window

_SIGNAL_RANK = {"action_required": 4, "attention": 3, "informational": 2, "noise": 1}

_CATEGORY_ORDER = ["Security", "Delete", "Create", "Modify", "API Key", "Other"]


def _peak_signal(signals: list[str]) -> str:
    if not signals:
        return "noise"
    return max(signals, key=lambda s: _SIGNAL_RANK.get(s, 0))


def _detect_anomalies(events: list[AuditEvent], actor_id: str) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []

    # Off-hours: any event outside 06:00–22:00 UTC
    off_hours = [
        e for e in events
        if e.timestamp and not (6 <= e.timestamp.hour < 22)
    ]
    if off_hours:
        anomalies.append({
            "type": "off_hours",
            "description": f"{len(off_hours)} event(s) occurred outside business hours (06:00–22:00 UTC).",
            "severity": "medium",
        })

    # Multiple tools: distinct non-null client_tool values
    tools = {e.client_tool for e in events if e.client_tool}
    if len(tools) >= 2:
        anomalies.append({
            "type": "multiple_tools",
            "description": f"Activity from {len(tools)} different tools: {', '.join(sorted(tools))}.",
            "severity": "low",
        })

    # Deletion spike: >5 Delete-category events
    deletions = [e for e in events if e.action_category == "Delete"]
    if len(deletions) > 5:
        anomalies.append({
            "type": "deletion_spike",
            "description": f"{len(deletions)} deletion events detected — unusually high volume.",
            "severity": "high",
        })

    return anomalies


def _build_chapter(category: str, events: list[AuditEvent]) -> dict[str, Any]:
    signals = [e._signal_type for e in events if e._signal_type]
    peak = _peak_signal(signals)
    actions = list({e.normalized_action or e.action for e in events if e.action})[:5]
    resources = list({e.resource_name for e in events if e.resource_name and e.resource_name != "-"})[:5]
    return {
        "category": category,
        "event_count": len(events),
        "peak_signal": peak,
        "actions": actions,
        "resources": resources,
    }


def get_actor_narrative(db: Session, actor_id: str, time_window: str = "24h") -> dict[str, Any]:
    since = parse_time_window(time_window)
    query = db.query(AuditEvent).filter(AuditEvent.actor == actor_id)
    if since is not None:
        query = query.filter(AuditEvent.timestamp >= since)
    events: list[AuditEvent] = query.order_by(AuditEvent.timestamp.desc()).all()

    total_events = len(events)
    non_noise = [e for e in events if e._signal_type != "noise" and not e.is_routine_noise]
    non_noise_count = len(non_noise)

    # Actor display name from most recent event
    actor_display_name: str | None = None
    for e in events:
        if e._actor_display_name:
            actor_display_name = e._actor_display_name
            break

    # Group by action_category
    by_category: dict[str, list[AuditEvent]] = defaultdict(list)
    for e in events:
        cat = e.action_category or "Other"
        by_category[cat].append(e)

    chapters = [
        _build_chapter(cat, by_category[cat])
        for cat in _CATEGORY_ORDER
        if cat in by_category
    ]
    # Append any categories not in the fixed order
    for cat, evts in by_category.items():
        if cat not in _CATEGORY_ORDER:
            chapters.append(_build_chapter(cat, evts))

    anomalies = _detect_anomalies(events, actor_id)

    headline = (
        f"{actor_display_name or actor_id} made {non_noise_count} meaningful change(s) "
        f"in the last {time_window}."
    )

    return {
        "actor": actor_id,
        "actor_display_name": actor_display_name,
        "time_window": time_window,
        "total_events": total_events,
        "non_noise_count": non_noise_count,
        "headline": headline,
        "chapters": chapters,
        "anomalies": anomalies,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
