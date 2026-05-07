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
from backend.app.services.triage_service import existing_event_fingerprints, get_triage_record, import_triage_snapshot


def _triage_file_path() -> Path:
    return Path(os.getenv("TRIAGE_STATE_FILE", "data/triage_state.json"))


def _load_triage_file(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Import legacy file-backed triage state into the database.")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without writing to the database.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing database triage rows.")
    parser.add_argument("--triage-file", type=str, help="Override the triage state file path.")
    args = parser.parse_args()

    path = Path(args.triage_file) if args.triage_file else _triage_file_path()
    entries = _load_triage_file(path)
    init_db()

    summary = {
        "triage_file": str(path),
        "scanned_entries": len(entries),
        "matched_entries": 0,
        "imported": 0,
        "updated": 0,
        "skipped_stale": 0,
        "skipped_existing": 0,
        "dry_run": args.dry_run,
        "force": args.force,
    }

    with SessionLocal() as db:
        fingerprints = existing_event_fingerprints(db, entries.keys())
        summary["matched_entries"] = len(fingerprints)
        for event_fingerprint, entry in entries.items():
            if event_fingerprint not in fingerprints:
                summary["skipped_stale"] += 1
                continue
            if not isinstance(entry, dict):
                summary["skipped_stale"] += 1
                continue
            triage_status = entry.get("triage_status")
            if not triage_status:
                summary["skipped_stale"] += 1
                continue
            existing = get_triage_record(db, event_fingerprint)
            if args.dry_run:
                if existing is None:
                    summary["imported"] += 1
                elif args.force:
                    summary["updated"] += 1
                else:
                    summary["skipped_existing"] += 1
                continue
            created, updated = import_triage_snapshot(
                db,
                event_fingerprint=event_fingerprint,
                triage_status=str(triage_status),
                triage_actor=entry.get("triage_actor"),
                triage_note=entry.get("triage_note"),
                triage_timestamp=entry.get("triage_timestamp"),
                triage_source="file_import",
                force=args.force,
            )
            if created:
                summary["imported"] += 1
            elif updated:
                summary["updated"] += 1
            else:
                summary["skipped_existing"] += 1

    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
