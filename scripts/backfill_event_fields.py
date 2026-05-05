#!/usr/bin/env python3
import argparse
import json

from backend.app.db.database import SessionLocal, init_db
from backend.app.services.backfill_service import backfill_source_fields_from_raw_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill persisted AuditLens event fields from raw payloads.")
    parser.add_argument("--source-fields", action="store_true", help="Backfill source/client/context fields.")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without updating rows.")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--force", action="store_true", help="Overwrite existing source fields.")
    args = parser.parse_args()
    if not args.source_fields:
        parser.error("choose at least one backfill target, for example --source-fields")
    init_db()
    with SessionLocal() as db:
        result = backfill_source_fields_from_raw_payload(db, dry_run=args.dry_run, limit=args.limit, force=args.force)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
