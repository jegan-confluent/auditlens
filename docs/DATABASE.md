# Database schema management

AuditLens has two persistence modes:

| Mode      | DATABASE_URL prefix     | Used by                      | Schema management          |
|-----------|-------------------------|------------------------------|----------------------------|
| SQLite    | `sqlite:///...`         | demo / tests / single-host   | `init_db()` + `_ensure_audit_event_columns()` |
| Postgres  | `postgresql://...`      | production with `ENABLE_DB_WRITER=true` | **Alembic migrations** |

## Policy

**All schema changes must be made via Alembic revisions. Never write
`ALTER TABLE` directly in application code.**

The `_ensure_audit_event_columns()` helper in
`backend/app/db/database.py` and the analogous `DatabaseWriter._ensure_columns`
in `src/product/db_writer.py` exist solely to upgrade local SQLite databases
that were created before a column was added. New columns belong in an Alembic
revision *and* — only if SQLite demo databases must keep working through the
upgrade — also in those `_ensure_columns` dictionaries.

## Day-to-day workflow

### Apply migrations to Postgres

```bash
DATABASE_URL=postgresql://auditlens:auditlens@127.0.0.1:5432/auditlens make migrate
# or, equivalently:
cd backend && alembic upgrade head
```

### Generate a new revision

```bash
cd backend
alembic revision -m "describe change"
# edit alembic/versions/<rev>_describe_change.py
```

When the change can be expressed as `Base.metadata` deltas, you can
optionally use `--autogenerate` after pointing `DATABASE_URL` at the
*current* schema:

```bash
DATABASE_URL=postgresql://... alembic revision --autogenerate -m "describe change"
```

Always inspect the generated revision before committing — autogenerate misses
data migrations and dialect-specific constructs.

### Roll back

```bash
cd backend && alembic downgrade -1
```

The `0002_ensure_decision_columns` and `0003_triage_cascade_fk` downgrades are
intentionally lossless: dropping additive columns or the cascade FK could
discard data, so they no-op or are gated to Postgres only.

## Migration inventory

| Revision                       | Purpose |
|--------------------------------|---------|
| `0001_baseline`                | Codifies the schema as of the cutover (uses `Base.metadata.create_all`). Idempotent against an existing DB. |
| `0002_ensure_decision_columns` | Idempotent additive `ALTER TABLE` patches that bring a Postgres DB created before the decision/intelligence columns up to date. |
| `0003_triage_cascade_fk`       | Adds `ON DELETE CASCADE` between `audit_event_triage.event_fingerprint` and `audit_events.event_fingerprint` (Postgres only — SQLite keeps the FK at table-create time and falls back to an application-level cleanup). |

## Why two paths instead of "Alembic only"?

The SQLite path keeps `scripts/run_sqlite_demo.sh` zero-dependency for new
contributors who do not have Postgres or Alembic locally. The
`_ensure_audit_event_columns()` helper guarantees a stale demo DB on disk
still works after a `git pull`, without forcing every contributor to
install Alembic.

If you are running the production Postgres deployment, Alembic is the source
of truth — do not rely on `_ensure_columns` there.
