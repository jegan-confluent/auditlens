from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from backend.app.core.config import get_settings
from backend.app.db.database import build_engine, init_db
from backend.app.db.models import AuditEvent


def redact_database_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername.startswith("sqlite"):
        return url.render_as_string(hide_password=True)
    return url.set(password="***").render_as_string(hide_password=True)


def database_mode(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername.startswith("sqlite"):
        return "sqlite"
    if url.drivername.startswith("postgresql"):
        return "postgres"
    return "unknown"


def sqlite_path(database_url: str) -> str | None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return None
    path = url.database or ""
    if not path or path == ":memory:":
        return path or None
    return str(Path(path))


def _count_events(engine) -> tuple[int, int]:
    with engine.connect() as conn:
        total = conn.execute(select(func.count()).select_from(AuditEvent.__table__)).scalar_one()
        missing_source_ip = conn.execute(
            select(func.count()).select_from(AuditEvent.__table__).where(
                (AuditEvent.source_ip.is_(None)) | (AuditEvent.source_ip == "")
            )
        ).scalar_one()
    return int(total or 0), int(missing_source_ip or 0)


def build_status_payload(*, api_database_url: str | None = None, forwarder_database_url: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    api_url = api_database_url or settings.database_url
    forwarder_url = forwarder_database_url or os.environ.get("FORWARDER_DATABASE_URL") or api_url
    api_engine = build_engine(api_url)
    init_db(api_engine)
    total_rows, missing_source_ip = _count_events(api_engine)
    payload: dict[str, Any] = {
        "db_mode": database_mode(api_url),
        "api_db": redact_database_url(api_url),
        "forwarder_db": redact_database_url(forwarder_url),
        "urls_match": redact_database_url(api_url) == redact_database_url(forwarder_url),
        "audit_events_rows": total_rows,
        "missing_source_ip_rows": missing_source_ip,
    }
    api_mode = database_mode(api_url)
    if api_mode == "sqlite":
        payload["sqlite_path"] = sqlite_path(api_url)
    else:
        url = make_url(api_url)
        payload["postgres_host"] = url.host
        payload["postgres_port"] = url.port
        payload["postgres_db"] = url.database
    return payload


def format_status_lines(payload: dict[str, Any]) -> list[str]:
    lines = [
        f"DB mode: {payload['db_mode']}",
        f"API DB: {payload['api_db']}",
        f"Forwarder DB: {payload['forwarder_db']}",
        f"API and forwarder DB URLs match: {'yes' if payload['urls_match'] else 'no'}",
        f"audit_events rows: {payload['audit_events_rows']}",
        f"missing source_ip rows: {payload['missing_source_ip_rows']}",
    ]
    if payload["db_mode"] == "sqlite" and payload.get("sqlite_path"):
        lines.append(f"SQLite file: {payload['sqlite_path']}")
    if payload["db_mode"] == "postgres":
        lines.append(
            "Postgres target: "
            f"{payload.get('postgres_host')}:{payload.get('postgres_port')}/{payload.get('postgres_db')}"
        )
    return lines


def main() -> int:
    payload = build_status_payload()
    for line in format_status_lines(payload):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
