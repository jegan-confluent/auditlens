#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.db.database import SessionLocal, init_db
from backend.app.services.backfill_service import backfill_resource_intelligence_from_raw_payload
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
    parser = argparse.ArgumentParser(description="Backfill historical resource intelligence and resource catalog entries.")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without updating rows.")
    parser.add_argument("--limit", type=int, default=1000, help="Maximum rows to scan.")
    parser.add_argument("--hours", type=int, help="Backfill rows from the last N hours.")
    parser.add_argument("--since", type=str, help="Backfill rows with timestamp >= ISO timestamp.")
    parser.add_argument("--until", type=str, help="Backfill rows with timestamp <= ISO timestamp.")
    parser.add_argument("--batch-size", type=int, default=250, help="Rows to process per batch.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing enriched resource fields.")
    args = parser.parse_args()

    since = None
    until = None
    try:
        if args.since:
            since = _parse_timestamp(args.since, "--since")
        if args.until:
            until = _parse_timestamp(args.until, "--until")
    except ValueError as exc:
        parser.error(str(exc))

    status = build_status_payload(recent_window_hours=4)
    for line in format_status_lines(status):
        print(line)

    init_db()
    with SessionLocal() as db:
        result = backfill_resource_intelligence_from_raw_payload(
            db,
            dry_run=args.dry_run,
            limit=args.limit,
            force=args.force,
            hours=args.hours,
            since=since,
            until=until,
            batch_size=args.batch_size,
        )
    print(json.dumps(result, sort_keys=True))
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "backfill_resource_intelligence.log"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(
            f"{timestamp} dry_run={args.dry_run} force={args.force} "
            f"hours={args.hours if args.hours is not None else '-'} "
            f"limit={args.limit} scanned={result['scanned']} updated={result['updated']} "
            f"skipped={result['skipped']} catalog_upserted={result['catalog_upserted']} "
            f"catalog_failed={result['catalog_failed']} invalid_json={result['invalid_json']}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
