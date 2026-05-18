# Contributing to AuditLens

## Development Environment

1. Clone and create a virtual environment:

```bash
git clone <repo-url>
cd AuditLens
python3.11 -m venv .venv
source .venv/bin/activate
```

2. Install runtime + dev dependencies:

```bash
make dev-setup
# equivalent to:
pip install -r requirements.txt -r requirements-dev.txt
```

3. Copy the config templates and fill in credentials:

```bash
cp .env.example .env
cp .secrets.example .secrets
```

You do not need real Kafka credentials for unit tests. The credential-unset wrapper (see below) prevents `.env` from leaking into the test run.

---

## Running Tests

Always use the credential-unset wrapper so `.env` values do not bleed into the test session:

```bash
CONFLUENT_CLOUD_API_KEY="" CONFLUENT_CLOUD_API_SECRET="" \
CONFLUENT_API_KEY="" CONFLUENT_API_SECRET="" \
.venv/bin/pytest -q
```

Or via make (uses the same wrapper):

```bash
make test
```

Run a single test file:

```bash
CONFLUENT_CLOUD_API_KEY="" CONFLUENT_CLOUD_API_SECRET="" \
CONFLUENT_API_KEY="" CONFLUENT_API_SECRET="" \
.venv/bin/pytest tests/test_classification.py -v
```

Backend API tests:

```bash
CONFLUENT_CLOUD_API_KEY="" CONFLUENT_CLOUD_API_SECRET="" \
.venv/bin/pytest backend/tests/ -v
```

The test pass count grows over time. Never submit a PR that reduces the passing count.

---

## Running the Frontend TypeScript Check

```bash
npm --prefix frontend run build
```

This compiles the Next.js app and reports TypeScript errors. Zero errors required before opening a PR. You can also run the type-checker alone without producing build output:

```bash
cd frontend && npx tsc --noEmit
```

---

## Running the Forwarder in Dev Mode

With a `.env` and `.secrets` file present:

```bash
make dev-run
# equivalent to:
source .env && source .secrets && python audit_forwarder.py
```

The forwarder connects to the audit-log topic specified in `AUDIT_BOOTSTRAP` + `AUDIT_TOPIC`, enriches events, and writes to the database configured in `DATABASE_URL`.

For local iteration without real Kafka, use SQLite demo mode:

```bash
scripts/run_sqlite_demo.sh
```

This seeds sample events and starts the API + frontend without any Kafka connection.

---

## Branch and Commit Style

**Branch naming:**

```
feature/<short-description>   # new capability
fix/<short-description>        # bug fix
docs/<short-description>       # documentation only
chore/<short-description>      # tooling, deps, CI
```

**Conventional commits:**

```
feat: add resource catalog tab to frontend
fix: guard upload-sarif step when SARIF file is absent
docs: add prerequisites and Confluent Cloud checklist to README
chore: bump docker/build-push-action to v6
refactor: extract signal classification into separate module
test: add coverage for denial pattern aggregation
```

Rules:
- One logical change per commit.
- Present tense, imperative mood ("add", not "added" or "adds").
- Keep the subject line under 72 characters.
- Add a body only when the "why" is not obvious from the subject.
- Never skip pre-commit hooks (`--no-verify`).

---

## How to Add a Classification Rule

AuditLens has two classification layers:

### Layer 1 — Criticality (CRITICAL / HIGH / MEDIUM / LOW)

File: `src/classification/methods.py`

Add the Confluent method name (e.g. `kafka.DeleteTopic/v1`) to the appropriate set:

```python
CRITICAL_METHODS: frozenset[str] = frozenset({
    ...
    "kafka.YourNewCriticalMethod/v1",
})
```

Sets defined in `methods.py`: `CRITICAL_METHODS`, `HIGH_METHODS`, `MEDIUM_METHODS`. Anything not listed defaults to LOW.

The criticality logic that consumes these sets lives in `src/classification/criticality.py`.

### Layer 2 — Signal type (action_required / attention / informational / noise)

File: `src/product/event_signals.py`

Signal type is derived in `_classify_signal_core()` and then post-processed by `classify_signal()`. To suppress a method as noise:

```python
# in src/product/event_normalization.py
BULK_NOISE_METHODS: frozenset[str] = frozenset({
    ...
    "kafka.YourRoutineMethod/v1",
})
```

To promote a specific method to `action_required` regardless of other signals, add an override block inside `_classify_signal_core()` following the existing pattern (see lines around the `action_required` assignments in `event_signals.py`).

### Test your rule

Add a test case in `tests/test_classification.py` (or `tests/test_signal_classification.py` if it exists) that asserts the expected `criticality` and `signal_type` for a synthetic event. Run the full suite before opening a PR.

---

## Architecture Overview

```
Confluent Cloud audit topic
        │
        ▼
audit_forwarder.py  — Main consumer loop. Reads the audit log topic,
│                     classifies events by criticality and signal type,
│                     enriches actor identities, writes to PostgreSQL.
│                     Also dispatches notifications (Slack/Teams/webhook).
│
├── src/classification/   — Criticality rules (CRITICAL/HIGH/MEDIUM/LOW)
├── src/product/          — Signal classification, actor enrichment,
│                           resource intelligence, DB writer, normalization
└── src/notifications/    — AuditLensNotifier: webhook destinations,
                            dedup, retry (reads notifications.yml)

backend/app/
├── main.py               — FastAPI app bootstrap, lifespan, middleware
├── api/routes/           — One file per route group: events, summary,
│                           filters, system, settings, admin, actors, etc.
└── services/             — Business logic behind routes (event_service,
                            backfill_service, system_service, etc.)

frontend/
├── app/                  — Next.js App Router pages:
│   ├── dashboard/        — At-a-glance signal summary and action feed
│   ├── events/           — Triage inbox, signal badges, detail drawer
│   ├── system/           — Pipeline health, VACUUM, container status
│   └── settings/         — Retention, cold storage, notifications,
│                           actor mappings, resource catalog, schema registry
└── components/           — Shared UI: SignalBadge, EventDetailDrawer,
                            AuditEventTable, NarrativeStrip, TopActors, etc.

docker-compose.yml — Local dev: auditlens-forwarder (8003), api (8080),
                     frontend (3000), postgres (5432), prometheus (9090),
                     grafana (3001). Ports bound to 127.0.0.1 only.
```

---

## Code Style

- Python: `black` for formatting, `flake8` + `pylint` for lint.
- TypeScript: strict mode, no `any`, explicit return types on exports.
- Run formatters before committing:

```bash
make format   # black
make lint     # flake8 + pylint + black --check
```

---

## Before Submitting a PR

```bash
make format
make lint
make test
scripts/security_scan.sh
```

All four must pass. The CI pipeline runs the same checks.
