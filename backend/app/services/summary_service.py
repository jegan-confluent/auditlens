from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, defer, load_only

from backend.app.db.models import AuditEvent
from backend.app.services.event_service import (
    EVENT_LIST_COLUMNS,
    SIGNAL_FILTER_MAX_SCAN,
    _apply_derived_prefilters,
    _event_filter_conditions,
    _matches_derived_filters,
    _parse_change_types,
    _parse_impact_types,
    _decision_mode_condition,
    _normalize_mode,
    _parse_signal_types,
)
from src.product.event_intelligence import flow_group_key
from src.product.event_normalization import canonical_resource_type


# Per-route statement timeout for /summary on Postgres. Phase 4 added this as
# a stopgap when /summary still issued seven sequential aggregations. After the
# Phase-4-followup single-pass refactor (this file) the route normally finishes
# well under 30s, but we keep the relaxed local timeout as defence in depth so
# a transient cost spike (concurrent forwarder write, autovacuum) cannot 500
# the route.
SUMMARY_ROUTE_STATEMENT_TIMEOUT_MS = 120_000

SUMMARY_SCAN_LIMIT = 5000

# GROUPING() bitmask values that the single-pass query produces. The argument
# order is (action_category, resource_type, result); a 1-bit means "this column
# is NOT part of this row's grouping set". So:
#   ()                  → all three rolled up → 0b111 = 7  (totals row)
#   (action_category)   → action_category grouped, others rolled up → 0b011 = 3
#   (resource_type)     → 0b101 = 5
#   (result)            → 0b110 = 6
_GID_TOTAL = 7
_GID_ACTION_CATEGORY = 3
_GID_RESOURCE_TYPE = 5
_GID_RESULT = 6


def _group_counts(db: Session, column, conditions: list[Any] | None = None) -> dict[str, int]:
    query = select(column, func.count()).group_by(column)
    if conditions:
        query = query.where(*conditions)
    rows = db.execute(query).all()
    return {str(key): int(count) for key, count in rows if key is not None}


def _top(counter: Counter[str], limit: int = 5) -> list[dict[str, Any]]:
    return [{"value": key, "count": count} for key, count in counter.most_common(limit)]


def _canonical_resource_counts(raw: dict[str, int]) -> dict[str, int]:
    output: dict[str, int] = {}
    for key, value in raw.items():
        canonical = canonical_resource_type(key)
        output[canonical] = output.get(canonical, 0) + value
    return output


def _aggregate_with_grouping_sets(
    db: Session, conditions: list[Any]
) -> tuple[int, int, int, dict[str, int], dict[str, int], dict[str, int]]:
    """Single Postgres scan that replaces six separate aggregations.

    Returns ``(base_total, base_failures, base_denials, by_action_category,
    by_resource_type, by_result)``. The ``by_resource_type`` dict here is the
    raw column values; the caller folds them through ``canonical_resource_type``.

    The query uses ``GROUP BY GROUPING SETS`` so Postgres scans the windowed
    rowset once and emits four buckets:

    * the empty grouping → row with ``GROUPING() = 7`` carrying the overall
      ``count(*)`` plus the ``count(*) FILTER (WHERE is_failure)`` /
      ``count(*) FILTER (WHERE is_denied)`` aggregates.
    * a row per ``action_category`` value (gid = 3).
    * a row per ``resource_type`` value (gid = 5).
    * a row per ``result`` value (gid = 6).
    """
    aggregation = (
        select(
            func.grouping(
                AuditEvent.action_category,
                AuditEvent.resource_type,
                AuditEvent.result,
            ).label("gid"),
            AuditEvent.action_category.label("action_category"),
            AuditEvent.resource_type.label("resource_type"),
            AuditEvent.result.label("result"),
            func.count().label("row_count"),
            func.count().filter(AuditEvent.is_failure.is_(True)).label("failure_count"),
            func.count().filter(AuditEvent.is_denied.is_(True)).label("denied_count"),
        )
        .group_by(
            text(
                "GROUPING SETS ("
                "(), "
                "(audit_events.action_category), "
                "(audit_events.resource_type), "
                "(audit_events.result)"
                ")"
            )
        )
    )
    if conditions:
        aggregation = aggregation.where(*conditions)

    base_total = base_failures = base_denials = 0
    by_action: dict[str, int] = {}
    by_resource: dict[str, int] = {}
    by_result: dict[str, int] = {}

    for row in db.execute(aggregation).all():
        gid = int(row.gid)
        count_val = int(row.row_count or 0)
        if gid == _GID_TOTAL:
            base_total = count_val
            base_failures = int(row.failure_count or 0)
            base_denials = int(row.denied_count or 0)
        elif gid == _GID_ACTION_CATEGORY and row.action_category is not None:
            by_action[str(row.action_category)] = count_val
        elif gid == _GID_RESOURCE_TYPE and row.resource_type is not None:
            by_resource[str(row.resource_type)] = count_val
        elif gid == _GID_RESULT and row.result is not None:
            by_result[str(row.result)] = count_val

    return base_total, base_failures, base_denials, by_action, by_resource, by_result


def _headline(action_required: int, attention: int) -> tuple[str, str]:
    if action_required:
        return "action_required", "Action needed. Failures, denied access, or destructive changes were detected."
    if attention:
        return "review_needed", "Review needed. Configuration or access changes were detected."
    return "all_clear", "No action needed. Most activity is routine authentication and authorization."


def _short_digest(total: int, noise: int, attention: int, action_required: int, destructive: int) -> str:
    if not total:
        return "No events found for the selected window."
    routine_pct = round((noise / total) * 100) if total else 0
    if action_required:
        return f"{total:,} events found. {routine_pct}% are routine noise. {attention:,} need review. {action_required:,} require action, including {destructive:,} destructive events."
    if attention:
        return f"{total:,} events found. {routine_pct}% are routine noise. {attention:,} configuration or access changes need review."
    return f"{total:,} events found. {routine_pct}% are routine auth/read activity. No destructive or failed events detected."


def _flow_groups(events: list[AuditEvent], limit: int = 5) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str, int], list[AuditEvent]] = {}
    for event in events:
        groups.setdefault(flow_group_key(event, window_seconds=60), []).append(event)

    def priority(group: list[AuditEvent]) -> tuple[int, int, datetime]:
        representative = group[0]
        signal_priority = {"action_required": 0, "attention": 1, "informational": 2, "noise": 3}.get(representative.signal_type, 4)
        latest = max(event.timestamp for event in group)
        return signal_priority, -len(group), -latest.timestamp()

    rows = sorted(groups.values(), key=priority)[:limit]
    output: list[dict[str, Any]] = []
    for group in rows:
        representative = group[0]
        first_seen = min(event.timestamp for event in group)
        last_seen = max(event.timestamp for event in group)
        signal_type = representative.signal_type
        resource = representative.resource_display_short
        subject = representative.subject
        family = representative.resource_family
        if representative.signal_type == "action_required":
            title = f"{len(group)} action-needed events detected for {subject}"
        elif representative.signal_type == "attention" and representative.impact_type == "configuration_change":
            title = f"{len(group)} config changes by {subject}"
        elif representative.signal_type == "noise" and representative.impact_type == "authorization_check":
            title = f"{len(group)} routine authorization checks by {subject}"
        elif representative.signal_type == "noise" and representative.impact_type == "authentication":
            title = f"{len(group)} authentications by {subject}"
        else:
            title = f"{len(group)} {representative.decision_label.lower()} events by {subject}"
        if family != "unknown" and resource != "Unknown" and representative.signal_type != "action_required":
            title = f"{title} on {resource}"
        output.append(
            {
                "group_title": title,
                "group_summary": f"{representative.decision_label}: {representative.event_title}",
                "event_count": len(group),
                "first_seen": first_seen.isoformat() if isinstance(first_seen, datetime) else str(first_seen),
                "last_seen": last_seen.isoformat() if isinstance(last_seen, datetime) else str(last_seen),
                "subject": subject,
                "signal_type": signal_type,
                "decision_label": representative.decision_label,
                "risk_level": representative.risk_level,
                "impact_type": representative.impact_type,
                "resource_family": family,
                "resource_display_short": resource,
                "recommended_action": representative.recommended_action,
                "representative_event_ids": [event.id for event in group[:10]],
            }
        )
    return output


def get_summary(
    db: Session,
    *,
    mode: str = "audit_trail",
    signal_type: str | None = None,
    hide_noise: bool = False,
    impact_type: str | None = None,
    change_type: str | None = None,
    **filters: Any,
) -> dict:
    is_postgres = db.get_bind().dialect.name == "postgresql"

    # Defence in depth: relax the per-statement timeout for this transaction
    # so transient cost spikes do not 500 the route. Single-pass aggregation
    # below normally finishes well inside Phase 2's 30s budget; this raises
    # the ceiling for outliers (concurrent forwarder writes, autovacuum). SET
    # LOCAL is scoped to the active transaction and reverts on commit.
    if is_postgres:
        db.execute(text(f"SET LOCAL statement_timeout = {SUMMARY_ROUTE_STATEMENT_TIMEOUT_MS}"))

    mode = _normalize_mode(mode)
    signal_types = _parse_signal_types(signal_type)
    impact_types = _parse_impact_types(impact_type)
    change_types = _parse_change_types(change_type)
    derived_filter_applied = bool(signal_types or impact_types or change_types) or hide_noise
    filters = _apply_derived_prefilters(filters, impact_types, change_types)
    conditions = _event_filter_conditions(**filters)
    if mode == "decision":
        conditions.append(_decision_mode_condition())

    scan_limit = SIGNAL_FILTER_MAX_SCAN if derived_filter_applied else SUMMARY_SCAN_LIMIT
    scan_query = (
        select(AuditEvent)
        .options(load_only(*EVENT_LIST_COLUMNS), defer(AuditEvent.raw_payload_json, raiseload=True))
        .order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc())
        .limit(scan_limit)
    )
    if conditions:
        scan_query = scan_query.where(*conditions)

    # Aggregations.
    #
    # Postgres + derived_filter_applied=False (the heavy production path):
    #   ONE GROUPING SETS query covers total/failures/denials and the three
    #   GROUP BYs in a single scan of the windowed rowset.
    # Postgres + derived_filter_applied=True:
    #   ONE count(*) query for ``base_total`` (used by summary_scope /
    #   sample_warning). The other counts come from the in-memory ``events``
    #   list because the derived predicate is evaluated in Python.
    # SQLite:
    #   Original three count queries — preserves existing test behaviour and
    #   avoids depending on Postgres-only GROUPING SETS in the demo path.
    base_total = base_failures = base_denials = 0
    db_by_action: dict[str, int] | None = None
    db_by_resource: dict[str, int] | None = None
    db_by_result: dict[str, int] | None = None

    if is_postgres and not derived_filter_applied:
        (
            base_total,
            base_failures,
            base_denials,
            db_by_action,
            db_by_resource_raw,
            db_by_result,
        ) = _aggregate_with_grouping_sets(db, conditions)
        db_by_resource = _canonical_resource_counts(db_by_resource_raw)
    elif is_postgres and derived_filter_applied:
        count_query = select(func.count(AuditEvent.id))
        if conditions:
            count_query = count_query.where(*conditions)
        base_total = int(db.scalar(count_query) or 0)
    else:
        # SQLite path — preserves the original per-aggregation queries.
        count_query = select(func.count(AuditEvent.id))
        failures_query = select(func.count(AuditEvent.id)).where(AuditEvent.is_failure.is_(True))
        denials_query = select(func.count(AuditEvent.id)).where(AuditEvent.is_denied.is_(True))
        if conditions:
            count_query = count_query.where(*conditions)
            failures_query = failures_query.where(*conditions)
            denials_query = denials_query.where(*conditions)
        base_total = int(db.scalar(count_query) or 0)
        base_failures = int(db.scalar(failures_query) or 0)
        base_denials = int(db.scalar(denials_query) or 0)

    scanned_events = list(db.scalars(scan_query).all())
    events = (
        [
            event
            for event in scanned_events
            if _matches_derived_filters(event, signal_types, hide_noise, impact_types, change_types)
        ]
        if derived_filter_applied
        else scanned_events
    )

    total = len(events) if derived_filter_applied else base_total
    failures = sum(1 for event in events if event.is_failure) if derived_filter_applied else base_failures
    denials = sum(1 for event in events if event.is_denied) if derived_filter_applied else base_denials

    signal_counts: Counter[str] = Counter(event.signal_type for event in events)
    reason_counts: Counter[str] = Counter(event.signal_reason for event in events)
    subject_counts: Counter[str] = Counter(event.subject for event in events if event.subject)
    resource_counts: Counter[str] = Counter(
        event.resource_display_name or event.resource_display_short
        for event in events
        if (event.resource_display_name or event.resource_display_short)
    )
    action_counts: Counter[str] = Counter(event.event_title for event in events if event.event_title)
    destructive = sum(1 for event in events if event.impact_type == "destructive")
    config_changes = sum(1 for event in events if event.impact_type == "configuration_change")
    access_changes = sum(1 for event in events if event.impact_type == "access_change")
    overall_status, headline = _headline(signal_counts["action_required"], signal_counts["attention"])
    summary_scope = "complete" if base_total <= scan_limit else "sampled"
    sample_warning = None
    if summary_scope == "sampled":
        sample_warning = f"Summary based on latest {len(scanned_events):,} of {base_total:,} matching events."

    # by_X output: in-memory counters when derived; otherwise the DB-derived
    # values (one query on Postgres, three queries on SQLite).
    if derived_filter_applied:
        out_by_action_category: dict[str, int] = dict(
            Counter(event.action_category for event in events if event.action_category)
        )
        out_by_resource_type: dict[str, int] = dict(
            Counter(canonical_resource_type(event.resource_type) for event in events if event.resource_type)
        )
        out_by_result: dict[str, int] = dict(Counter(event.result for event in events if event.result))
    elif is_postgres:
        out_by_action_category = db_by_action or {}
        out_by_resource_type = db_by_resource or {}
        out_by_result = db_by_result or {}
    else:
        out_by_action_category = _group_counts(db, AuditEvent.action_category, conditions)
        out_by_resource_type = _canonical_resource_counts(_group_counts(db, AuditEvent.resource_type, conditions))
        out_by_result = _group_counts(db, AuditEvent.result, conditions)

    return {
        "total_events": total,
        "scanned_events": len(scanned_events),
        "failures": failures,
        "denials": denials,
        "noise_count": int(signal_counts["noise"]),
        "informational_count": int(signal_counts["informational"]),
        "attention_count": int(signal_counts["attention"]),
        "action_required_count": int(signal_counts["action_required"]),
        "failure_count": failures,
        "denied_count": denials,
        "destructive_count": destructive,
        "configuration_change_count": config_changes,
        "access_change_count": access_changes,
        "top_subjects": _top(subject_counts),
        "top_resources": _top(resource_counts),
        "top_actions": _top(action_counts),
        "top_signal_reasons": _top(reason_counts),
        "flow_groups": _flow_groups(events),
        "summary_scope": summary_scope,
        "sample_limit": scan_limit,
        "sample_warning": sample_warning,
        "overall_status": overall_status,
        "headline": headline,
        "short_digest": _short_digest(
            len(events),
            signal_counts["noise"],
            signal_counts["attention"],
            signal_counts["action_required"],
            destructive,
        ),
        "by_action_category": out_by_action_category,
        "by_resource_type": out_by_resource_type,
        "by_result": out_by_result,
    }
