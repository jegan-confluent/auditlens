#!/usr/bin/env python3
"""Backfill classification fields for audit_events rows.

Re-runs derive_action_category and the signal-classification cascade against
each event's raw_payload_json and writes back action_category / signal_type /
signal_reason / resource_type when the new value differs from the stored one.

Targets rows where signal_type is missing/empty or action_category is the
catch-all "Other" — i.e. rows that the previous classifier could not
confidently classify. Idempotent: rows whose recomputed values match the
stored values are skipped, so the script is safe to re-run.

Usage:
    DATABASE_URL=postgresql://... python scripts/backfill_classification.py
    python scripts/backfill_classification.py --dry-run
    python scripts/backfill_classification.py --database-url sqlite:///path

Run manually after deploying the cascade fixes. Not invoked automatically.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

# Make the repo root importable regardless of where the script is invoked.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from sqlalchemy import create_engine, text  # noqa: E402

from src.product.db_writer import normalize_database_url  # noqa: E402
from src.product.event_normalization import normalize_event  # noqa: E402


BATCH_SIZE = 1000
PROGRESS_INTERVAL = 10000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("backfill_classification")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing any rows.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="SQLAlchemy database URL (defaults to $DATABASE_URL).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"Rows per SELECT batch (default: {BATCH_SIZE}).",
    )
    return parser.parse_args()


def _load_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


_FIELDS = ("action_category", "signal_type", "signal_reason", "resource_type")


def _build_update(row, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return an UPDATE row dict if recomputation differs, else None."""
    try:
        normalized = normalize_event(payload)
    except Exception as exc:
        logger.warning("normalize_event failed for id=%s: %s", row.id, exc)
        return None

    existing = {field: getattr(row, field) for field in _FIELDS}
    new = {field: normalized.get(field) for field in _FIELDS}
    if all((new[f] or "") == (existing[f] or "") for f in _FIELDS):
        return None
    return {**new, "id": row.id}


def main() -> int:
    args = _parse_args()
    if not args.database_url:
        logger.error("DATABASE_URL not set; pass --database-url or export it.")
        return 1

    engine = create_engine(normalize_database_url(args.database_url), future=True)

    select_sql = text(
        """
        SELECT id, raw_payload_json, action_category, signal_type,
               signal_reason, resource_type
        FROM audit_events
        WHERE id > :last_id
          AND (
            signal_type IS NULL
            OR signal_type = ''
            OR action_category = 'Other'
          )
        ORDER BY id
        LIMIT :limit
        """
    )
    update_sql = text(
        """
        UPDATE audit_events
        SET action_category = :action_category,
            signal_type = :signal_type,
            signal_reason = :signal_reason,
            resource_type = :resource_type
        WHERE id = :id
        """
    )

    last_id = 0
    scanned = 0
    changed = 0
    last_progress = 0

    while True:
        with engine.connect() as conn:
            rows = conn.execute(
                select_sql,
                {"last_id": last_id, "limit": args.batch_size},
            ).all()
        if not rows:
            break

        updates: list[dict[str, Any]] = []
        for row in rows:
            scanned += 1
            payload = _load_payload(row.raw_payload_json)
            if not payload:
                last_id = row.id
                continue
            update = _build_update(row, payload)
            if update is not None:
                updates.append(update)
            last_id = row.id

        if updates:
            changed += len(updates)
            if args.dry_run:
                # Sample the first few diffs per batch so the user can see
                # what would change without dumping every row.
                for update in updates[:3]:
                    logger.info(
                        "would update id=%s -> %s",
                        update["id"],
                        {k: v for k, v in update.items() if k != "id"},
                    )
            else:
                with engine.begin() as conn:
                    conn.execute(update_sql, updates)

        if scanned - last_progress >= PROGRESS_INTERVAL:
            logger.info(
                "progress scanned=%s changed=%s last_id=%s",
                scanned, changed, last_id,
            )
            last_progress = scanned

    logger.info(
        "done scanned=%s changed=%s dry_run=%s",
        scanned, changed, args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
