"""BUG-8 regression: pattern occurrence_count must increment by 1 per detection window, not by the event count.

Before the fix, on_conflict_do_update set occurrence_count += item["count"]
(the window event count, e.g. 11), so each re-detection added 11 rows to
the counter rather than 1. After the fix it increments by 1.
"""
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine, select, text

from src.product.pattern_detector import PatternDetector, _patterns_table


def _make_detector(tmp_dir: str) -> PatternDetector:
    db_path = Path(tmp_dir) / "patterns.db"
    return PatternDetector(f"sqlite:///{db_path}")


def _row(engine, key: str) -> dict | None:
    with engine.connect() as conn:
        result = conn.execute(
            select(_patterns_table).where(_patterns_table.c.pattern_key == key)
        ).first()
    if result is None:
        return None
    return dict(result._mapping)


def test_occurrence_count_increments_by_one_per_detection():
    """Second detection of the same pattern must add 1 to occurrence_count, not item['count']."""
    with TemporaryDirectory() as tmp:
        det = PatternDetector(f"sqlite:///{Path(tmp) / 'p.db'}")
        now = time.time()
        item = {
            "key": "deadbeef" * 8,
            "actor": "u-test",
            "action": "kafka.Authentication",
            "resource_name": "my-topic",
            "count": 11,
            "ts": now,
        }

        # First detection → INSERT with occurrence_count=11, window_count=1
        det._upsert_pattern(item)
        row = _row(det._engine, item["key"])
        assert row is not None
        assert row["occurrence_count"] == 11
        assert row["window_count"] == 1

        # Second detection → UPDATE: occurrence_count should go to 12, NOT 22
        det._upsert_pattern({**item, "ts": now + 1})
        row = _row(det._engine, item["key"])
        assert row["occurrence_count"] == 12, (
            f"Expected 12 but got {row['occurrence_count']}. "
            "occurrence_count must increment by 1 per detection, not by item['count']."
        )
        assert row["window_count"] == 2


def test_window_count_always_increments_by_one():
    """window_count must increase by 1 on each conflict, matching occurrence_count's new behaviour."""
    with TemporaryDirectory() as tmp:
        det = PatternDetector(f"sqlite:///{Path(tmp) / 'p.db'}")
        now = time.time()
        item = {
            "key": "cafebabe" * 8,
            "actor": "u-test",
            "action": "kafka.CreateTopic",
            "resource_name": "events-topic",
            "count": 15,
            "ts": now,
        }

        for i in range(5):
            det._upsert_pattern({**item, "ts": now + i})

        row = _row(det._engine, item["key"])
        assert row["window_count"] == 5
        # INSERT sets occurrence_count=item["count"]=15; 4 updates add +1 each → 19
        assert row["occurrence_count"] == item["count"] + 4
