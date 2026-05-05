#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.db.database import SessionLocal, init_db
from backend.app.services.backfill_service import backfill_source_fields_from_raw_payload
from backend.app.services.db_status_service import build_status_payload, format_status_lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill persisted AuditLens event fields from raw payloads.")
    parser.add_argument("--source-fields", action="store_true", help="Backfill source/client/context fields.")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without updating rows.")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--force", action="store_true", help="Overwrite existing source fields.")
    parser.add_argument("--allow-empty", action="store_true", help="Allow updates even when the target database is empty.")
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
        result = backfill_source_fields_from_raw_payload(db, dry_run=args.dry_run, limit=args.limit, force=args.force)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
