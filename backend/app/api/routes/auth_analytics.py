"""GET /auth/analytics — top API keys + source IPs by kafka.Authentication volume.

Reads audit_events_noise (auth events are bulk-noise). Resolution chain for
the actor display name, in order:

  1. audit_events_noise.actor_display_name on the row itself
     (populated at ingest via the principalResourceId swap in
     minimal_normalize, and via the offline backfill script that mines
     audit_events.raw_payload_json for User:N → u-xxx mappings).
  2. audit_events.actor_display_name cross-join — covers actors that
     appear in the enriched table but not yet on the noise row (e.g.,
     legacy rows ingested before migration 0031).
  3. actor_mappings.yml manual override.
  4. Raw actor as the last resort.

Two windows supported: 1d, 7d.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.routes.patterns import _require_viewer
from backend.app.core.limiter import limiter
from backend.app.db.database import get_db
from src.product.actor_enrichment import get_actor_mapping_file


class AuthAnalyticsActor(BaseModel):
    actor: str
    actor_display_name: str | None = None
    actor_email: str | None = None
    auth_count: int
    unique_ips: int
    pct_of_total: float
    trend: Literal["up", "down", "stable"]


class AuthAnalyticsSourceIp(BaseModel):
    source_ip: str
    auth_count: int
    unique_actors: int
    cloud_provider: str


class AuthAnalyticsConcentration(BaseModel):
    top3_pct: float


class AuthAnalyticsResponse(BaseModel):
    total_auth_events: int
    time_window: str
    top_actors: list[AuthAnalyticsActor]
    top_source_ips: list[AuthAnalyticsSourceIp]
    concentration: AuthAnalyticsConcentration

logger = logging.getLogger("auditlens.backend.auth_analytics")

router = APIRouter(tags=["auth_analytics"])

_TIME_WINDOWS = {"1d": timedelta(days=1), "7d": timedelta(days=7)}

# audit_events_noise can grow large; cap the per-query budget so a misuse
# can't tie up a worker. Project rule #77: dialect-guard so SQLite tests pass.
_STMT_TIMEOUT_MS = 10000


def _cloud_provider_from_ip(ip: str) -> str:
    """Best-effort cloud-provider label keyed by /8 prefix.

    Order matters: 35.x overlaps AWS and GCP, and the spec asks GCP to
    win for that octet. Confluent Internal (134.238/16) is checked
    before public AWS/GCP blocks so a Confluent IP can never get
    mislabeled as a public-cloud one.
    """
    if not ip:
        return "Unknown"
    # RFC1918 internal
    if ip.startswith("10.") or ip.startswith("192.168."):
        return "Internal"
    if any(ip.startswith(f"172.{n}.") for n in range(16, 32)):
        return "Internal"
    # Confluent Internal (specific before public blocks)
    if ip.startswith("134.238."):
        return "Confluent Internal"
    # GCP first — owns 34.x and shares 35.x with AWS; spec says GCP wins for 35.x.
    if ip.startswith("34.") or ip.startswith("35."):
        return "GCP"
    # AWS — public allocations 3/18/44/52/54 (35 already routed to GCP above).
    if any(ip.startswith(f"{p}.") for p in ("3", "18", "44", "52", "54")):
        return "AWS"
    # Azure
    if any(ip.startswith(f"{p}.") for p in ("20", "40", "104")):
        return "Azure"
    return "Unknown"


@router.get("/auth/analytics", response_model=AuthAnalyticsResponse)
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

    # Also pull the noise table's own actor_display_name + actor_email so
    # the route can render them without a cross-join when the row already
    # carries the enrichment (migration 0031 + minimal_normalize swap).
    # MAX() works on string columns under both Postgres and SQLite and
    # picks any non-NULL value within the group.
    actor_rows = db.execute(text(
        """
        SELECT actor,
               COUNT(*) AS auth_count,
               COUNT(DISTINCT source_ip) AS unique_ips,
               SUM(CASE WHEN timestamp < :half THEN 1 ELSE 0 END) AS first_half,
               SUM(CASE WHEN timestamp >= :half THEN 1 ELSE 0 END) AS second_half,
               MAX(actor_display_name) AS noise_display_name,
               MAX(actor_email) AS noise_email
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

    # Fallback resolution: cross-join into the enriched audit_events table.
    # Only used when the noise row itself has no actor_display_name.
    # DISTINCT ON keeps one row per actor (Postgres-specific). On SQLite
    # (test runs only) skip this step and fall through to actor_mappings.yml.
    actor_list = [row.actor for row in actor_rows if row.actor]
    display_map: dict[str, str] = {}
    email_map: dict[str, str] = {}
    if actor_list and db.get_bind().dialect.name == "postgresql":
        # Bound the cross-table lookup by the same time window the noise
        # query used — keeps the scan index-friendly and consistent with
        # what the noise side already paid for.
        display_rows = db.execute(text(
            """
            SELECT DISTINCT ON (actor) actor, actor_display_name, actor_email
            FROM audit_events
            WHERE actor = ANY(:actors)
              AND timestamp >= :cutoff
              AND actor_display_name IS NOT NULL
              AND actor_display_name <> ''
            """
        ), {"actors": actor_list, "cutoff": cutoff}).all()
        for r in display_rows:
            if r.actor_display_name:
                display_map[r.actor] = r.actor_display_name
            if r.actor_email:
                email_map[r.actor] = r.actor_email

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

    def _display_name(actor_value: str, noise_display: str | None) -> str:
        # 1. Noise row's own actor_display_name (populated at ingest time).
        if noise_display:
            return noise_display
        # 2. audit_events cross-join (legacy rows / pre-0031 backfill).
        hit = display_map.get(actor_value)
        if hit:
            return hit
        # 3. actor_mappings.yml manual override.
        name = mapping.get(actor_value)
        if name:
            return name
        # 4. "User:" prefix strip + retry the mapping lookup.
        if actor_value.startswith("User:"):
            stripped = actor_value[5:]
            name = mapping.get(stripped)
            if name:
                return name
        # 5. Raw actor as last resort.
        return actor_value

    def _email(actor_value: str, noise_email: str | None) -> str | None:
        if noise_email:
            return noise_email
        return email_map.get(actor_value)

    top_actors = []
    for row in actor_rows:
        actor_value = row.actor or ""
        auth_count = int(row.auth_count or 0)
        noise_display = getattr(row, "noise_display_name", None)
        noise_email = getattr(row, "noise_email", None)
        top_actors.append({
            "actor": actor_value,
            "actor_display_name": _display_name(actor_value, noise_display),
            "actor_email": _email(actor_value, noise_email),
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
