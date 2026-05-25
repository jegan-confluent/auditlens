"""GET /auth/analytics — top API keys + source IPs by kafka.Authentication volume.

Reads audit_events_noise (auth events are bulk-noise). Display names come from
actor_mappings.yml at response time because audit_events_noise has no
actor_display_name column. Two windows supported: 1d, 7d.
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.routes.patterns import _require_viewer
from backend.app.core.limiter import limiter
from backend.app.db.database import get_db
from src.product.actor_enrichment import get_actor_mapping_file

logger = logging.getLogger("auditlens.backend.auth_analytics")

router = APIRouter(tags=["auth_analytics"])

_TIME_WINDOWS = {"1d": timedelta(days=1), "7d": timedelta(days=7)}

# audit_events_noise can grow large; cap the per-query budget so a misuse
# can't tie up a worker. Project rule #77: dialect-guard so SQLite tests pass.
_STMT_TIMEOUT_MS = 10000


def _cloud_provider_from_ip(ip: str) -> str:
    """Best-effort label. Only Internal (RFC1918) is reliable without a
    geo/ASN lookup — anything else returns Unknown so the UI doesn't lie."""
    if not ip:
        return "Unknown"
    if ip.startswith("10.") or ip.startswith("192.168."):
        return "Internal"
    if any(ip.startswith(f"172.{n}.") for n in range(16, 32)):
        return "Internal"
    return "Unknown"


@router.get("/auth/analytics")
@limiter.limit("60/minute")
def auth_analytics(
    request: Request,
    time_window: str = Query(default="1d", pattern=r"^(1d|7d)$"),
    db: Session = Depends(get_db),
    _auth: None = Depends(_require_viewer),
) -> dict:
    delta = _TIME_WINDOWS[time_window]
    now = datetime.now(timezone.utc)
    cutoff = now - delta
    half = now - delta / 2

    if db.get_bind().dialect.name == "postgresql":
        db.execute(text(f"SET LOCAL statement_timeout = {_STMT_TIMEOUT_MS}"))

    total_row = db.execute(text(
        """
        SELECT COUNT(*) AS n
        FROM audit_events_noise
        WHERE LOWER(action) = 'kafka.authentication'
          AND timestamp >= :cutoff
        """
    ), {"cutoff": cutoff}).one()
    total = int(total_row.n or 0)

    actor_rows = db.execute(text(
        """
        SELECT actor,
               COUNT(*) AS auth_count,
               COUNT(DISTINCT source_ip) AS unique_ips,
               SUM(CASE WHEN timestamp < :half THEN 1 ELSE 0 END) AS first_half,
               SUM(CASE WHEN timestamp >= :half THEN 1 ELSE 0 END) AS second_half
        FROM audit_events_noise
        WHERE LOWER(action) = 'kafka.authentication'
          AND timestamp >= :cutoff
          AND actor IS NOT NULL
          AND actor <> ''
        GROUP BY actor
        ORDER BY auth_count DESC
        LIMIT 10
        """
    ), {"cutoff": cutoff, "half": half}).all()

    mapping = get_actor_mapping_file()

    def _trend(first: int, second: int) -> str:
        if first == 0 and second == 0:
            return "stable"
        # max(first, 1) lets a 0→N jump register as "up" without div-zero.
        change_pct = (second - first) / max(first, 1) * 100
        if change_pct >= 20:
            return "up"
        if change_pct <= -20:
            return "down"
        return "stable"

    def _display_name(actor_value: str) -> str:
        name = mapping.get(actor_value)
        if name:
            return name
        # actor may carry the "User:" prefix from the audit principal; strip
        # and retry the lookup so mappings keyed on the bare resourceId hit.
        if actor_value.startswith("User:"):
            stripped = actor_value[5:]
            name = mapping.get(stripped)
            if name:
                return name
        return actor_value

    top_actors = []
    for row in actor_rows:
        actor_value = row.actor or ""
        auth_count = int(row.auth_count or 0)
        top_actors.append({
            "actor": actor_value,
            "actor_display_name": _display_name(actor_value),
            "auth_count": auth_count,
            "unique_ips": int(row.unique_ips or 0),
            "pct_of_total": round(100.0 * auth_count / total, 2) if total else 0.0,
            "trend": _trend(int(row.first_half or 0), int(row.second_half or 0)),
        })

    ip_rows = db.execute(text(
        """
        SELECT source_ip,
               COUNT(*) AS auth_count,
               COUNT(DISTINCT actor) AS unique_actors
        FROM audit_events_noise
        WHERE LOWER(action) = 'kafka.authentication'
          AND timestamp >= :cutoff
          AND source_ip IS NOT NULL
          AND source_ip <> ''
        GROUP BY source_ip
        ORDER BY auth_count DESC
        LIMIT 10
        """
    ), {"cutoff": cutoff}).all()

    top_source_ips = [
        {
            "source_ip": row.source_ip,
            "auth_count": int(row.auth_count or 0),
            "unique_actors": int(row.unique_actors or 0),
            "cloud_provider": _cloud_provider_from_ip(row.source_ip),
        }
        for row in ip_rows
    ]

    top3 = sum(a["auth_count"] for a in top_actors[:3])
    top3_pct = round(100.0 * top3 / total, 2) if total else 0.0

    return {
        "total_auth_events": total,
        "time_window": time_window,
        "top_actors": top_actors,
        "top_source_ips": top_source_ips,
        "concentration": {"top3_pct": top3_pct},
    }
