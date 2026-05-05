#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.db.database import SessionLocal, init_db
from backend.app.services.backfill_service import backfill_source_fields_from_raw_payload
from backend.app.services.db_status_service import build_status_payload, format_status_lines


def _parse_timestamp(value: str, flag: str) -> datetime:
    text = value.strip()
    if not text:
        raise ValueError(f"invalid {flag} timestamp: empty value")
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid {flag} timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill persisted AuditLens event fields from raw payloads.")
    parser.add_argument("--source-fields", action="store_true", help="Backfill source/client/context fields.")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without updating rows.")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--force", action="store_true", help="Overwrite existing source fields.")
    parser.add_argument("--allow-empty", action="store_true", help="Allow updates even when the target database is empty.")
    parser.add_argument("--hours", type=int, help="Backfill rows from the last N hours.")
    parser.add_argument("--since", type=str, help="Backfill rows with timestamp >= ISO timestamp.")
    parser.add_argument("--until", type=str, help="Backfill rows with timestamp <= ISO timestamp.")
    parser.add_argument("--order", choices=["oldest", "newest"], default="oldest", help="Row traversal order.")
    parser.add_argument("--sleep-ms", type=int, default=0, help="Sleep between batches when processing multiple batches.")
    parser.add_argument("--debug-sample", type=int, default=0, help="Print redacted diagnostics for the first N candidate rows.")
    parser.add_argument("--id", type=int, dest="target_id", help="Restrict the backfill to a single AuditEvent id.")
    args = parser.parse_args()
    if not args.source_fields:
        parser.error("choose at least one backfill target, for example --source-fields")

    status = build_status_payload(
        api_database_url=os.environ.get("DATABASE_URL"),
        forwarder_database_url=os.environ.get("FORWARDER_DATABASE_URL"),
    )
    for line in format_status_lines(status):
        print(line)

    init_db()
    with SessionLocal() as db:
        if not args.dry_run and not args.allow_empty and status["audit_events_rows"] == 0:
            print("Refusing to update an empty audit_events table. Re-run with --allow-empty if this is intentional.", file=sys.stderr)
            return 1
        since = None
        until = None
        try:
            if args.since:
                since = _parse_timestamp(args.since, "--since")
            if args.until:
                until = _parse_timestamp(args.until, "--until")
        except ValueError as exc:
            parser.error(str(exc))
        result = backfill_source_fields_from_raw_payload(
            db,
            dry_run=args.dry_run,
            limit=args.limit,
            force=args.force,
            hours=args.hours,
            since=since,
            until=until,
            order=args.order,
            sleep_ms=args.sleep_ms,
            target_id=args.target_id,
            debug_sample=args.debug_sample,
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
