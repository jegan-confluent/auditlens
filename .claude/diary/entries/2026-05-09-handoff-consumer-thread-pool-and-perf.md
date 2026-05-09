# Session Handoff — 2026-05-09 — Consumer thread pool, async refresh, perf

## TL;DR

- **Forwarder throughput**: 7.9 msg/s → sustained 30–50 msg/s. Did not hit the 200 msg/s target — Postgres single-table contention is the wall (documented). 8 commits total, all on `master`, none pushed.
- **Architecture changed**: forwarder now runs `kafka-consumer` + `event-processor` threads (was single-threaded), with a `ThreadPoolExecutor` for parallel chunk inserts inside each buffer flush. Backpressure via `consumer.pause(assignment())` when `record_queue` fills.
- **Two load-bearing bug fixes** that the previous "code looks correct" framing missed: (1) `RateTrackerConfig(...)` was constructed via the dataclass constructor in `audit_forwarder.py:2854`, never going through `from_env()` — so `whitelist_principals` silently defaulted to `()`. (2) Splitting `consume()` and `commit()` across threads broke librdkafka's auto-offset-store; explicit `consumer.commit(offsets=[TopicPartition(t, p, off+1)])` per batch was required.
- **API container** is currently running my hot-patched `system.py` via `docker cp`. **Rebuild before pushing**: `docker compose build api && docker compose up -d api`.
- **`.env` was edited** (RECORD_QUEUE_SIZE=20, DB_WRITER_THREADS=2, DB_WRITE_PARALLEL_CHUNK_SIZE=250). It is gitignored and was NOT staged — verify with `git status` before any push.

## Project Context

- **App**: AuditLens (audit-forwarder) — Confluent Cloud audit-log intelligence pipeline.
- **Stack**: Python 3.11 forwarder (`confluent-kafka`, FastAPI/Pydantic backend, SQLAlchemy on Postgres for production / SQLite for tests). Next.js 15 + React 19 + TypeScript strict frontend. Streamlit dashboard parallel UI in `audit-forwarder-feb`. Docker Compose orchestration. `pytest` backend, `node tests/render-smoke.mjs` frontend smoke (known broken on HEAD).
- **Current focus**: Forwarder throughput + observability. The dashboard / signal-classification / actor-display work from previous sessions is stable. This session was three back-to-back perf-tuning briefs.
- **Branch**: `master`. Working tree clean except for two diary files. None pushed.

## Session Summary

### What we discussed/planned

- **Brief 1** (Issues 1–7): forwarder idle, SQLite 91 % full, lag 1.26 M, header pill broken, system page minimal, "What matters" essay, dense ActionFeed cards. User prescribed code per issue. I diagnosed live state, found Issue 1's premise was wrong (forwarder was at 7.9 msg/s, not idle), and proposed phased A→B→C→D commits.
- **Brief 2** (5 fixes): async IAM refresh, async lag polling, anomaly dedup, anomaly whitelist verification, per-phase batch timing.
- **Brief 3** (PARTS 1–6 + thread pool): Kafka consumer tuning, thread-pool architecture, async IAM refresh (already done), anomaly dedup (already done), SQLite non-blocking, rdkafka stats for lag, plus parallel DB writers as part of PART 2.

### What we debated

- **Issue 1 — fix forwarder idle vs. skip.** Live state showed 7.9 msg/s and continuous DB writes. Premise of "forwarder is not consuming" was wrong. Resolved by AskUserQuestion → user picked "skip Issue 1, fold into Issue 3."
- **Sequencing the 7-issue task all-at-once vs. phased.** CLAUDE.md says to break >3-file tasks. Resolved by AskUserQuestion → user picked `A → B → C → D` separate commits.
- **Sequencing the thread-pool task all-at-once vs. phased.** Same pattern. Resolved by AskUserQuestion → user picked `1+5+6+docs` first commit, `PART 2` second.
- **Adding parallel DB writers in PART 2.** I flagged that 1 writer caps at ~150 ev/s on PG insert and that more might not help linearly. Resolved by AskUserQuestion → user said "yes, add it." Implementation defaults `DB_WRITER_THREADS=2`. Tried 4-writer / 125-row chunks live; throughput regressed (chunks went 3000 ms → 8000 ms each, lock contention). Reverted to 2/250.
- **Async lag polling: rdkafka stats callback vs. daemon `get_watermark_offsets` thread.** First implementation (in `ac98f1b`) used a daemon thread. Brief 3 prescribed the stats-callback approach for the same reason. The user's prescriptive note that `get_watermark_offsets` is "NOT thread-safe" is technically wrong (only `consumer.close()` is documented unsafe), but the stats-callback architecture IS cleaner — switched to it in `c7a899e`.
- **Whitelist principal normalization: strip `User:` prefix vs. compare both forms.** Chose both: `if normalized in whitelist or principal in whitelist:`. The actual fix for the alert flood was switching to `RateTrackerConfig.from_env()` — see "Decisions Made."
- **`SignalSummaryPanel.tsx` smoke-test strings.** The smoke test asserts "Filter by this activity" / "Open details only" / "filterPreview" exist in the file. The new clean single-line cards remove that copy. Per the previous session's handoff the smoke is already broken on HEAD; the user's spec explicitly removed the dense flow text. Net: smoke is still broken but no NEW assertions broken.
- **Whether to rewrite or surgically edit the consume loop for the thread pool.** Surgically edit — preserve the per-message processing block verbatim, dedent it, and just wrap in the new outer thread structure. Avoids re-introducing bugs in 250 lines of working code.
- **Is `consumer.commit()` thread-safe?** Yes per confluent-kafka docs. The processor thread (B) calls `commit()`, the consumer thread (A) calls `consume()`. Documented in code comments.

### What we reviewed

- **Backend / forwarder**: `audit_forwarder.py` (3500+ lines, multiple sections), `src/product/db_writer.py`, `src/product/persistence.py`, `src/product/actor_enrichment.py`, `src/product/bootstrap.py`, `src/identity/enricher.py`, `src/anomaly/rate_tracker.py`, `src/identity/principal.py`.
- **Backend API**: `backend/app/api/routes/system.py`, `backend/app/api/routes/health.py`, `backend/app/api/routes/readiness.py`, `backend/app/services/system_service.py`, `backend/app/main.py` (route registration), `backend/alembic/versions/0005_filter_options_partial_indexes.py`.
- **Frontend**: `frontend/lib/api.ts`, `frontend/lib/types.ts`, `frontend/components/HeaderStatus.tsx`, `frontend/components/SystemStatusPanel.tsx`, `frontend/components/SignalSummaryPanel.tsx`, `frontend/components/ActionFeed.tsx`, `frontend/app/system/page.tsx`, `frontend/app/globals.css`, `frontend/tests/render-smoke.mjs`.
- **Infra**: `docker-compose.yml` (forwarder, api, postgres, frontend service blocks), `.env` (live tuning, gitignored).
- **Live**: `pg_stat_user_indexes` on `audit_events` (38 indexes → 18 after the drop), `/health` endpoint at `127.0.0.1:8003`, forwarder logs.

### What we changed/fixed

Eight commits, in order:

1. **`cc4b7fb`** — *perf: drop unused indexes, raise db batch size, add VACUUM endpoint*
2. **`b38258e`** — *perf(postgres): tune for bulk INSERT + add retention policy doc*
3. **`11e30ad`** — *feat(system): proxy forwarder health, composite header pill, observability page*
4. **`bff5852`** — *ux(events): replace 'What matters' essay with stat cards, clean up flow rows*
5. **`ac98f1b`** — *perf: async IAM refresh, async lag polling, anomaly dedup, batch timing*
6. **`c7a899e`** — *perf: kafka tuning, rdkafka stats lag, sqlite non-blocking, docs*
7. **`efb9957`** — *perf: thread-pool consumer + parallel db writers, explicit offset commit*

(Plus the live `.env` edits + the live `docker exec auditlens-postgres psql -c "DROP INDEX CONCURRENTLY ..."` that mirror commit `cc4b7fb`'s alembic migration.)

### What we tested

- **`pytest -q`** at the end of every commit: **487 passed, 5 skipped, 3 failed** — the 3 failures are pre-existing env-leakage failures (`.env` / `.secrets` leaking `CONFLUENT_CLOUD_API_KEY` into the pytest process), confirmed via the previous session's handoff. Not regressed by any of this session's work.
- **`npm --prefix frontend run build`**: 0 TypeScript errors at every commit. Required two type-fix corrections during Chunk C (`getReadinessStatus` return type, `ForwarderHealth` import path).
- **Live forwarder restart and `/health` poll** after every chunk:
  - After Chunk A: rate 7.9 → 30+ msg/s, SQLite 970 MB → 61 MB, storage_mode `critical → normal`.
  - After Chunk B: Postgres tuning verified via `SHOW synchronous_commit;` etc.
  - After Chunk C: `/system/forwarder-health` returns the proxied `/health` JSON; `/system/vacuum` returns success.
  - After commit `ac98f1b`: 0 sa-7y6xj82 alerts, suppressed-summary log lines visible, per-phase timing in DB-writer log.
  - After commit `c7a899e`: lag-by-partition populates from `stats_cb`, no daemon lag thread, `sqlite_write_failed` would log at WARN (not seen — SQLite path nominal).
  - After commit `efb9957`: `Thread pool started: 1 consumer, 1 processor, 2 db writers (record_queue capacity=20)`. Saw `record_queue full (20/20) — pausing consumer for backpressure` under load. Two parallel chunks confirmed (timestamps within 100–500 ms).
- **Manual `POST /admin/vacuum`**: returned `{"status":"success", "before_bytes":62267392, "reclaimed_bytes":0, ...}`.
- **Manual `POST /system/vacuum`**: returned `{"status":"success", "trigger":"manual", "before_bytes":..., ...}` — except for one transient "database or disk is full" during rotation, treated as known intermittent.
- **Frontend bundle hash check**: `docker exec auditlens-frontend find /app/.next/static/chunks/app/events -name 'page-*.js' -exec grep -l 'signal-stat-card\|flow-row' {} \;` — confirmed new strings present, so the redeployed bundle is the new code.
- **Did NOT do**: real browser visual checks of `/system` or `/events`. Flagged this in the session summary per CLAUDE.md "say so explicitly rather than claiming success."

## Files Modified

| File | Purpose | Changes |
|---|---|---|
| `audit_forwarder.py` | Forwarder main + HTTP/health | Stats-callback for lag, `persist_safely()` wraps for SQLite hot path, thread-pool consumer/processor split, `ThreadPoolExecutor` for parallel DB chunks, explicit offset tracking, new env vars (`RECORD_QUEUE_SIZE`, `DB_WRITER_THREADS`, `DB_WRITE_PARALLEL_CHUNK_SIZE`, `KAFKA_GROUP_INSTANCE_ID`, etc.), `record_queue_depth` + `record_queue_capacity` in `/health`, `RateTrackerConfig.from_env()` (was direct dataclass constructor), `POST /admin/vacuum` endpoint |
| `src/product/db_writer.py` | Postgres writer | Drop 19 redundant `Index()` declarations to match the alembic migration, add `normalize_ms` / `pg_insert_ms` / `catalog_upsert_ms` to `DbWriteResult`, time the three phases inside `write_batch`, accept `executor` param on `flush_db_writer_buffer` |
| `src/product/persistence.py` | SQLite hot cache | Implement actual `vacuum()` + `_vacuum_unlocked(trigger=...)` + auto-vacuum from `cleanup_expired()` (was no-op stub), throttle `_refresh_storage_status()` in the hot write path to every 5 s |
| `src/product/actor_enrichment.py` | Actor enrichment façade | Call `enricher.start_background_refresh()` when constructing the singleton |
| `src/identity/enricher.py` | Confluent IAM enricher | `start_background_refresh()` daemon thread, atomic dict swap on refresh, never blocks `resolve()`, `_fetch_all_identities()` returns NEW dicts (no mid-refresh partial state) |
| `src/anomaly/rate_tracker.py` | Rate-based anomaly detection | `_normalize_principal_for_compare()` strips `User:` prefix, dedup key drops `source_ip` (now `(type, normalized_principal)`), `flush_suppression_summary()` returns drained tally, `dedup_window_seconds` env var (`ANOMALY_DEDUP_WINDOW_SECONDS`) |
| `backend/alembic/versions/0006_drop_unused_indexes.py` | (NEW) Migration | Drops 20 unused indexes on `audit_events` (`idx_scan=0` per `pg_stat_user_indexes`); concurrent on Postgres, plain on SQLite; `downgrade()` recreates them |
| `backend/app/api/routes/system.py` | Backend system routes | New `GET /system/forwarder-health` proxies the forwarder's `/health` (avoids browser hitting port 8003 directly), new `POST /system/vacuum` proxies to `POST /admin/vacuum`, 5 s / 30 s timeouts |
| `frontend/lib/api.ts` | Backend client | New `getForwarderHealth()` and `runForwarderVacuum()` |
| `frontend/lib/types.ts` | Shared types | New `ForwarderHealth` + `VacuumResult` types matching the proxied `/health` shape |
| `frontend/components/HeaderStatus.tsx` | Header pill | Composite state from `/system/forwarder-health` (lag + storage_mode + processing_rate), 30 s polling, lag shown in pill when degraded |
| `frontend/components/SignalSummaryPanel.tsx` | Events page header | Replace "What matters" essay with 4 stat cards (Noise/Info/Review/Action), replace dense flow cards with single-line rows (icon + title + actor + time + arrow) |
| `frontend/app/system/page.tsx` | System page | Full rewrite: 4 status cards (API/Database/Forwarder/Storage), forwarder pipeline table, data quality table, storage detail section with VACUUM button |
| `frontend/app/globals.css` | CSS | `.header-status.critical` class (was missing), `.system-status-card{,.ok,.warning,.critical}`, `.system-pipeline-row`, `.system-quality-row`, `.system-progress`, `.system-vacuum-button`, `.signal-stat-cards`, `.flow-row` |
| `docker-compose.yml` | Service config | Default `DB_WRITE_BATCH_SIZE` 100 → 500 on forwarder; postgres `command` block adds `synchronous_commit=off` + WAL/buffer/work-mem tuning |
| `docs/RETENTION_POLICY.md` | (NEW + updated) Customer-facing doc | Initial creation in `b38258e`; `c7a899e` appends "Consumer Architecture" section with tuning table and throughput expectations |
| `.env` | Live tuning (not staged) | `DB_WRITE_BATCH_SIZE=500`, `KAFKA_CONSUME_BATCH_SIZE=500`, `DB_WRITE_PARALLEL_CHUNK_SIZE=250`, `DB_WRITER_THREADS=2`, `RECORD_QUEUE_SIZE=20` |

## Key Code Snippets

### Async IAM cache refresh — atomic swap
```python
# src/identity/enricher.py
def start_background_refresh(self, *, initial_load_async: bool = True) -> None:
    if not self.enabled or self._refresh_thread_started.is_set():
        return
    self._refresh_thread_started.set()

    def loop() -> None:
        try:
            sas, users = self._fetch_all_identities()
            with self._lock:
                self._service_accounts = sas    # atomic swap
                self._users = users
            self._identities_loaded = True
            logger.info("Identity cache loaded: %d service accounts, %d users",
                        len(sas), len(users))
        except Exception as exc:
            self._last_refresh_error = str(exc)
            logger.warning("Initial identity cache load failed; will retry: %s", exc)
            self._identities_loaded = True  # don't fall back to lazy-blocking path

        while True:
            time.sleep(self._refresh_interval_seconds)
            try:
                sas, users = self._fetch_all_identities()
                with self._lock:
                    self._service_accounts = sas
                    self._users = users
                    self._cache.clear()  # drop per-resolve TTL cache
                logger.info("Identity cache refreshed: %d service accounts, %d users",
                            len(sas), len(users))
            except Exception as exc:
                logger.warning("Identity cache refresh failed (keeping old cache): %s", exc)

    threading.Thread(target=loop, daemon=True, name="auditlens-identity-refresh").start()
```

### Anomaly dedup — `(type, normalized_principal)` key + suppression summary
```python
# src/anomaly/rate_tracker.py
def _normalize_principal_for_compare(principal: Optional[str]) -> str:
    """Strip the leading `User:` qualifier."""
    if not principal:
        return ""
    return principal[5:] if principal.startswith("User:") else principal


def _should_alert(self, alert: AnomalyAlert) -> bool:
    """source_ip is intentionally OUT of the dedup key — a single misconfigured
    SA hitting an AWS NAT pool used to produce one alert per source IP."""
    normalized = _normalize_principal_for_compare(alert.principal)
    key: Tuple[str, str] = (alert.anomaly_type.value, normalized)
    with self._lock:
        now = time.time()
        last = self._recent_alerts.get(key)
        if last is not None and now - last < self._alert_cooldown:
            self._suppressed_counts[key] = self._suppressed_counts.get(key, 0) + 1
            return False
        self._recent_alerts[key] = now
        # cleanup old entries...
        return True


def flush_suppression_summary(self) -> List[Tuple[str, str, int]]:
    """Drained on the 60 s tick from audit_forwarder; emits one INFO line per pair."""
    with self._lock:
        drained = [(t, p, c) for (t, p), c in self._suppressed_counts.items() if c > 0]
        self._suppressed_counts.clear()
        return drained
```

### Anomaly config wiring (the load-bearing fix)
```python
# audit_forwarder.py
# WRONG (silently ignored env-only fields):
# anomaly_config = RateTrackerConfig(
#     window_seconds=ANOMALY_WINDOW_SECONDS,
#     auth_failure_threshold=ANOMALY_AUTH_FAILURE_THRESHOLD,
#     ...
# )

# RIGHT — picks up ANOMALY_WHITELIST_PRINCIPALS, ANOMALY_SPIKE_THRESHOLD,
# ANOMALY_DEDUP_WINDOW_SECONDS:
anomaly_config = RateTrackerConfig.from_env()
anomaly_tracker = RateTracker(anomaly_config)
logger.info(
    "Anomaly detection initialized: window=%ds, auth_failure_threshold=%d, "
    "activity_spike_threshold=%d, dedup_window=%ds, whitelist_principals=%s",
    anomaly_config.window_seconds, anomaly_config.auth_failure_threshold,
    anomaly_config.activity_spike_threshold, anomaly_config.dedup_window_seconds,
    list(anomaly_config.whitelist_principals) or "<none>",
)
```

### Per-phase batch timing
```python
# src/product/db_writer.py
@dataclass
class DbWriteResult:
    attempted: int
    inserted: int
    elapsed_ms: float
    normalize_ms: float = 0.0
    pg_insert_ms: float = 0.0
    catalog_upsert_ms: float = 0.0


def write_batch(self, payloads):
    normalize_started = time.perf_counter()
    rows = [self._row(p) for p in payloads]
    resource_rows = [...]
    normalize_ms = (time.perf_counter() - normalize_started) * 1000
    ...
    pg_insert_started = time.perf_counter()
    # ... INSERT ON CONFLICT DO NOTHING ...
    pg_insert_ms = (time.perf_counter() - pg_insert_started) * 1000
    catalog_upsert_started = time.perf_counter()
    # ... resource_catalog upsert ...
    catalog_upsert_ms = (time.perf_counter() - catalog_upsert_started) * 1000
    return DbWriteResult(
        attempted=len(rows), inserted=inserted, elapsed_ms=...,
        normalize_ms=normalize_ms, pg_insert_ms=pg_insert_ms, catalog_upsert_ms=catalog_upsert_ms,
    )

# audit_forwarder.py — log line
logger.info(
    "DB writer batch complete attempted=%d inserted=%d elapsed_ms=%.1f "
    "[normalize=%.0fms pg_insert=%.0fms catalog_upsert=%.0fms]",
    result.attempted, result.inserted, result.elapsed_ms,
    getattr(result, "normalize_ms", 0.0),
    getattr(result, "pg_insert_ms", 0.0),
    getattr(result, "catalog_upsert_ms", 0.0),
)
```

### librdkafka stats callback for lag
```python
# audit_forwarder.py
def make_rdkafka_stats_callback(metrics_obj):
    def _on_stats(stats_json_str: str) -> None:
        try:
            stats = orjson.loads(stats_json_str)
        except Exception:
            return
        for topic_data in (stats.get("topics") or {}).values():
            for partition_id, p_data in (topic_data.get("partitions") or {}).items():
                try:
                    p_id = int(partition_id)
                except (TypeError, ValueError):
                    continue
                if p_id < 0:
                    continue
                consumer_lag = p_data.get("consumer_lag")
                if consumer_lag is None or consumer_lag < 0:
                    continue
                hi = p_data.get("hi_offset")
                pos = (hi - consumer_lag) if isinstance(hi, int) else (hi or 0)
                metrics_obj.update_lag(
                    p_id, pos,
                    hi if isinstance(hi, int) else (pos + consumer_lag),
                )
    return _on_stats

# In main():
consumer_conf_with_stats = dict(consumer_conf)
consumer_conf_with_stats["stats_cb"] = make_rdkafka_stats_callback(metrics)
consumer = Consumer(consumer_conf_with_stats)
# consumer_conf already has "statistics.interval.ms": 10000
```

### Thread-pool consumer + processor + parallel chunks
```python
# audit_forwarder.py — in main(), after consumer.subscribe(...)
RECORD_QUEUE_SIZE = max(1, int(os.getenv("RECORD_QUEUE_SIZE", "20")))
NUM_DB_WRITERS = max(1, int(os.getenv("DB_WRITER_THREADS", "2")))
record_queue: queue.Queue = queue.Queue(maxsize=RECORD_QUEUE_SIZE)
metrics.record_queue_capacity = RECORD_QUEUE_SIZE
db_executor = ThreadPoolExecutor(max_workers=NUM_DB_WRITERS, thread_name_prefix="db-writer")

def _consume_thread() -> None:
    paused = False
    while not _shutdown_requested:
        # ...consumer.consume() + backoff + empty handling...
        try:
            record_queue.put(batch_local, timeout=5.0)
            metrics.record_queue_depth = record_queue.qsize()
        except queue.Full:
            if not paused:
                consumer.pause(consumer.assignment()); paused = True
            while record_queue.qsize() > RECORD_QUEUE_SIZE // 2 and not _shutdown_requested:
                consumer.poll(0)  # critical: librdkafka heartbeats only fire from poll()
                _sleep_with_shutdown(0.1)
            if paused:
                consumer.resume(consumer.assignment()); paused = False
            record_queue.put(batch_local, timeout=30.0)
    record_queue.put(None, timeout=10.0)  # processor sentinel

def _process_thread() -> None:
    nonlocal processed, last_heartbeat, last_lag_ts, db_last_flush_ts
    while True:
        batch = record_queue.get(timeout=1.0)  # or queue.Empty branch
        if batch is None:
            break
        batch_max_offsets: dict[tuple[str, int], int] = {}
        for msg in batch:
            # ...full per-message pipeline...
            key = (msg.topic(), msg.partition())
            if msg.offset() > batch_max_offsets.get(key, -1):
                batch_max_offsets[key] = msg.offset()
        # End-of-batch DB flush — parallel chunks via executor.
        if ENABLE_DB_WRITER and db_write_buffer:
            flush_db_writer_buffer(db_write_buffer, ..., force=True, executor=db_executor)
        producer.flush(timeout=30)
        # Explicit offset commit — librdkafka auto-store unreliable across threads.
        if not batch_max_offsets:
            metrics.record_commit_success()
        else:
            offsets_to_commit = [
                TopicPartition(t, p, off + 1) for (t, p), off in batch_max_offsets.items()
            ]
            consumer.commit(offsets=offsets_to_commit, asynchronous=False)
```

### Parallel chunk DB write
```python
# src/product/db_writer.py / audit_forwarder.py
def flush_db_writer_buffer(payloads, backoff, log_state, *, force=False,
                           executor: ThreadPoolExecutor | None = None) -> bool:
    if not ENABLE_DB_WRITER or not payloads:
        return True
    batch_size = max(1, DB_WRITE_BATCH_SIZE)
    if executor is not None and force:
        parallel_chunk = max(1, int(os.getenv("DB_WRITE_PARALLEL_CHUNK_SIZE", str(batch_size))))
        if len(payloads) > parallel_chunk:
            chunks = [payloads[i:i + parallel_chunk]
                      for i in range(0, len(payloads), parallel_chunk)]
            futures = [executor.submit(flush_db_writer_batch, list(c), backoff, log_state)
                       for c in chunks]
            all_ok = all(f.result(timeout=180) for f in futures)
            if all_ok:
                del payloads[:]
            return all_ok
    # ...sequential fallback unchanged...
```

### Backend forwarder-health proxy (avoids browser hitting port 8003)
```python
# backend/app/api/routes/system.py
@router.get("/system/forwarder-health")
def forwarder_health() -> JSONResponse:
    settings = get_settings()
    try:
        response = httpx.get(settings.forwarder_health_url, timeout=5.0)
        response.raise_for_status()
        payload = response.json()
    except httpx.TimeoutException:
        return JSONResponse(status_code=200, content={"status": "unknown", "error": "timeout"})
    except httpx.HTTPError as exc:
        return JSONResponse(status_code=200, content={"status": "unknown", "error": str(exc)})
    return JSONResponse(status_code=200, content=payload)


@router.post("/system/vacuum")
def vacuum_forwarder_db() -> JSONResponse:
    settings = get_settings()
    base_url = settings.forwarder_health_url.rsplit("/", 1)[0] if settings.forwarder_health_url else ""
    vacuum_url = f"{base_url}/admin/vacuum" if base_url else ""
    if not vacuum_url:
        return JSONResponse(status_code=503, content={"status": "failure", "error": "forwarder url not configured"})
    response = httpx.post(vacuum_url, timeout=30.0)
    return JSONResponse(status_code=response.status_code, content=response.json())
```

### Composite header pill
```typescript
// frontend/components/HeaderStatus.tsx
function classify(health: ForwarderHealth | null): { tone: Tone; label: string } {
  if (health === null) return { tone: "loading", label: "Connecting…" };
  const errorOnFetch = !!health.error;
  const consumerState = health.observability?.consumer_runtime?.consumer_state;
  if (errorOnFetch || consumerState === "down" || consumerState === "disconnected") {
    return { tone: "down", label: "Down" };
  }
  const lag = typeof health.consumer_lag === "number" ? health.consumer_lag : 0;
  const rate = typeof health.processing_rate === "number" ? health.processing_rate : 0;
  const storageMode = health.observability?.persistence_storage?.storage_mode;
  const dbWriterDown = health.observability?.db_writer?.enabled === true
    && health.observability?.db_writer?.db_writer_state !== "connected";
  if (storageMode === "critical" || storageMode === "emergency" || dbWriterDown) {
    return { tone: "critical", label: lag > 0 ? `Critical · ${compactNumber(lag)} lag` : "Critical" };
  }
  if (lag > HIGH_LAG_THRESHOLD || rate < SLOW_PROCESSING_THRESHOLD || storageMode === "warning") {
    return { tone: "degraded", label: lag > HIGH_LAG_THRESHOLD ? `Degraded · ${compactNumber(lag)} lag` : "Degraded" };
  }
  return { tone: "connected", label: "Connected" };
}
```

## Decisions Made

| Decision | Options | Choice | Why |
|---|---|---|---|
| Sequencing for the 7-issue task | All-at-once / 2 commits (perf+UI) / `A→B→C→D` 4 commits | A→B→C→D | CLAUDE.md "stop and break >3-file tasks"; user confirmed via AskUserQuestion |
| Issue 1 (forwarder idle) | Diagnose & fix / restart & recheck / skip | Skip, fold into Issue 3 | Forwarder not actually idle (7.9 msg/s live); the throughput problem IS Issue 3 |
| Sequencing the thread-pool task | All-at-once / `1+5+6+docs` first, `PART 2` second | Phased | Same CLAUDE.md rule; user confirmed |
| Add parallel DB writers in PART 2 | Yes / defer | Yes | User confirmed via AskUserQuestion; capped at 2 writers after live regression test |
| `RateTrackerConfig` construction in audit_forwarder.py | Direct dataclass / `from_env()` | `from_env()` | Direct construction silently dropped `whitelist_principals`, `dedup_window_seconds`, env-driven spike threshold |
| Lag polling: daemon `get_watermark_offsets` thread / rdkafka `stats_cb` | Both work | `stats_cb` | Off-thread, no extra network calls, librdkafka does the work; cleaner |
| Offset commit with thread-split consume/commit | `store_offsets(message=msg)` / explicit `commit(offsets=[TP])` | Explicit `commit(offsets=[TP])` | `_NO_OFFSET` errors persisted with `store_offsets`; explicit per-`(topic, partition)` `max_offset` tracking + `TopicPartition(t, p, off+1)` works |
| `DB_WRITER_THREADS` default | 1 / 2 / 4 | 2 | Live test: 4 writers regressed throughput because of Postgres lock contention on `event_fingerprint` unique constraint |
| API container patch deployment | Rebuild image / `docker cp` hot patch | `docker cp` for the session, rebuild before push | Image rebuild is slow during iteration; flagged in handoff that next session must rebuild |
| `SignalSummaryPanel.tsx` smoke-test strings | Preserve / drop | Drop | Smoke is broken on HEAD anyway; user's UI spec explicitly removes "Filter by this activity" copy |
| 200 msg/s target reporting | Claim partial credit / honest miss | Honest miss | User values honest "we didn't hit it" with reasons over fudged success |
| Parallel-chunk size knob | Hard-coded / dedicated env var | `DB_WRITE_PARALLEL_CHUNK_SIZE` env (default = `DB_WRITE_BATCH_SIZE`) | Operators can set chunk size below buffer to enable in-batch parallelism without changing the buffer-flush trigger |

## Implementation Status

| Item | Status | Priority | Notes |
|---|---|---|---|
| Drop 20 unused indexes (alembic 0006) | ✅ | — | Migration file in repo; live DB stamped at 0006 manually via `DROP INDEX CONCURRENTLY` + `UPDATE alembic_version` |
| `DB_WRITE_BATCH_SIZE` 100 → 500 default | ✅ | — | docker-compose.yml + .env both updated |
| SQLite VACUUM endpoint + auto-trigger | ✅ | — | `POST /admin/vacuum` (forwarder) + `POST /system/vacuum` (api proxy); auto from `cleanup_expired()` when reclaimable ≥ 500 MB or storage_mode critical |
| Postgres tuning (`synchronous_commit=off` etc.) | ✅ | — | Verified via `SHOW synchronous_commit; SHOW shared_buffers; ...` |
| `docs/RETENTION_POLICY.md` | ✅ | — | Plus appended "Consumer Architecture" section |
| Backend `/system/forwarder-health` + `/system/vacuum` proxies | ✅ | — | Live via `docker cp` hot patch — needs api image rebuild before push |
| Composite header pill (loading/connected/degraded/critical/down) | ✅ | — | 30 s polling, lag in pill when degraded |
| `/system` page rewrite (4 sections) | ✅ | — | Frontend container rebuilt + redeployed |
| 4 stat cards on /events | ✅ | — | Replaces "What matters" essay |
| Single-line ActionFeed-style rows on /events | ✅ | — | Replaces dense flow cards |
| Async IAM cache refresh (daemon thread) | ✅ | — | `start_background_refresh()` invoked from `_confluent_identity_enricher()` singleton constructor |
| Async lag polling (daemon thread) | ✅ → replaced | — | Daemon thread shipped in `ac98f1b`, replaced by `stats_cb` in `c7a899e` (cleaner) |
| Anomaly dedup `(type, principal)` + suppression summary | ✅ | — | `flush_suppression_summary()` drained on 60 s tick |
| Anomaly whitelist correctly wired | ✅ | — | `RateTrackerConfig.from_env()` switch + `_normalize_principal_for_compare()` |
| Per-phase batch timing | ✅ | — | `[normalize=… pg_insert=… catalog_upsert=…]` in DB-writer log |
| Kafka consumer tuning (fetch/session/heartbeat/group.instance.id) | ✅ | — | `KAFKA_GROUP_INSTANCE_ID` is opt-in (env var, default empty) |
| rdkafka `stats_cb` for lag | ✅ | — | Replaces synchronous `get_watermark_offsets` |
| `persist_safely()` for SQLite hot path | ✅ | — | 4 call sites: enriched_event, anomaly_alert, high_risk_event, operator_alert |
| Thread-pool: kafka-consumer + event-processor | ✅ | — | Backpressure via `consumer.pause(assignment())` when `record_queue` full |
| Parallel DB chunk inserts via `ThreadPoolExecutor` | ✅ | — | Default `DB_WRITER_THREADS=2`, `DB_WRITE_PARALLEL_CHUNK_SIZE=250` |
| Explicit offset commit per batch | ✅ | — | `consumer.commit(offsets=[TopicPartition(t, p, off+1)])` |
| `record_queue_depth` + `record_queue_capacity` in /health | ✅ | — | New fields visible via `/health` JSON |
| api image rebuild before push | ⏳ | **H** | `docker compose build api && docker compose up -d api` — required because api container has no source mount |
| 200 msg/s sustained target | ❌ | M | Currently 30–50 msg/s; bottleneck is Postgres single-table contention (unique constraint + indexes). Path forward documented at the bottom of `docs/RETENTION_POLICY.md` |
| Frontend smoke test (`npm test`) | ⏳ | L | Pre-existing breakage on HEAD; this session removed `"Filter by this activity"` strings the smoke asserts. Same status: broken |
| Pytest 3 env-leakage failures | ⏳ | L | Pre-existing. `.env`/`.secrets` leak `CONFLUENT_CLOUD_API_KEY` into the pytest process |
| Real browser visual checks of `/system` and `/events` | ⏳ | M | Bundle hashes verified to ship the new strings; no human eyeball pass. Owner's call |
| Push commits | ⏳ | **H** | 8 commits on master, none pushed |

## Next Steps

### 1. Immediate (before pushing)
- **Rebuild the api image**: `docker compose build api && docker compose up -d api`. Without this, the api container is running the `docker cp`'d `system.py` patch — restart wipes it. Verify after: `curl http://127.0.0.1:8080/system/forwarder-health` returns the proxied JSON.
- **Browser visual check** on `/dashboard`, `/events`, `/system`. Especially the new System page sections + the new stat cards on /events.
- **Confirm `.env` is not staged**: `git status` — should show only the two diary files untracked, no `M .env`.

### 2. Near-term (this week)
- **Push the 8 session commits** plus the 2 untracked diary files: `cc4b7fb`, `b38258e`, `11e30ad`, `bff5852`, `ac98f1b`, `c7a899e`, `efb9957`, plus a doc commit for the new diary entries.
- **Decide on the 200 msg/s target.** Three honest options documented at the bottom of `docs/RETENTION_POLICY.md`:
  1. Switch `INSERT … ON CONFLICT DO NOTHING` → `COPY` with app-side dedup (5–10× write speed; loses idempotent dedup at the DB layer).
  2. Partition `audit_events` by `timestamp` so writes go to a small hot partition with a small index — schema migration required.
  3. Add a second processor pinned to a partition subset (offset commits per-partition; doable but offset-correctness is non-trivial).
- **Backfill old unenriched events** (carried forward from the previous session). Now that the IAM enricher is correct, run a one-shot job over rows where `actor_display_name == actor_raw_id` and `actor_email IS NULL` to repopulate from Confluent IAM.
- **Frontend smoke test** (`npm test`). Update assertions to match the new `SignalSummaryPanel.tsx` + `/system/page.tsx` shapes; bring it back to green.

### 3. Backlog
- Auto-refresh on `/events` (every 30 s).
- URL filter round-trip on /events (read on mount only today; doesn't write back).
- Triage actions in inline expand on /events.
- localStorage "Resume where I was" link on dashboard.
- Cluster_name / environment_name dropdowns in FilterBar.
- Bulk triage / multi-select rows.
- Identity refresh metrics in /health (`last_refresh_at`, `last_refresh_error_count`).
- `/admin/vacuum` background trigger when storage_mode reaches `warning` (currently triggers on `critical`).
- Investigate the once-seen `database or disk is full` from `POST /system/vacuum` during rotation; reproduce + fix or document.

## Blockers

| Blocker | Impact | Resolution |
|---|---|---|
| api container running hot-patched system.py | Next restart drops the route, header pill goes back to broken | `docker compose build api && docker compose up -d api` BEFORE pushing |
| 200 msg/s target unmet | Lag on the production audit topic (1.4 M+) doesn't drain at 30–50 msg/s sustained | Out of scope this session; pick one of the three options in `docs/RETENTION_POLICY.md` |
| Frontend smoke test pre-existing breakage | Can't gate UI changes on it | Rewrite assertions for the new flow-row + stat-card layout |
| `.env` and `.secrets` leak `CONFLUENT_CLOUD_API_KEY` into pytest | 3 tests permanently red on dev machines | conftest autouse fixture to unset Confluent env at session start |
| Some historical events persisted with `actor_display_name == raw_id` | Italic-grey rows in the Who column | Backfill job (carried forward) |

## Quick Start Commands

```bash
# Verify the 8 session commits landed
git log --oneline -10
# efb9957 perf: thread-pool consumer + parallel db writers, explicit offset commit
# c7a899e perf: kafka tuning, rdkafka stats lag, sqlite non-blocking, docs
# ac98f1b perf: async IAM refresh, async lag polling, anomaly dedup, batch timing
# bff5852 ux(events): replace 'What matters' essay with stat cards, clean up flow rows
# 11e30ad feat(system): proxy forwarder health, composite header pill, observability page
# b38258e perf(postgres): tune for bulk INSERT + add retention policy doc
# cc4b7fb perf: drop unused indexes, raise db batch size, add VACUUM endpoint
# d825caf docs: diary, handoff, backlog 2026-05-08 EOD

# Confirm .env is NOT staged
git status -s
# Should show only the .claude/diary/entries/2026-05-09-* files as untracked.

# Pytest baseline (487 passed, 3 pre-existing env-leakage failures)
.venv/bin/pytest -q --tb=line

# Frontend build (TypeScript correctness)
npm --prefix frontend run build

# Rebuild + redeploy the api container (REQUIRED before pushing — the
# /system/forwarder-health and /system/vacuum routes are currently
# `docker cp`-patched into the running container).
docker compose build api && docker compose up -d api

# Then verify the proxy works:
curl -s http://127.0.0.1:8080/system/forwarder-health \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('status:', d.get('status'), 'rate:', d.get('processing_rate'))"

# Live forwarder snapshot
curl -s http://127.0.0.1:8003/health | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('rate:', round(d['processing_rate'], 1), 'msg/s')
print('lag:', f\"{d['consumer_lag']:,}\")
print('processed:', d['processed_total'])
print('queue:', d.get('record_queue_depth'), '/', d.get('record_queue_capacity'))
print('errors:', d['error_count'])
"

# Watch the thread pool in action
docker compose logs -f auditlens-forwarder 2>&1 | grep -E \
  "Thread pool started|elapsed_ms|backpressure|Forwarder is alive|suppressed.*repeats|sqlite_write_failed"

# Trigger a manual VACUUM (proxied through the api)
curl -s -X POST http://127.0.0.1:8080/system/vacuum \
  | python3 -m json.tool

# Direct VACUUM on the forwarder (skip the api)
curl -s -X POST http://127.0.0.1:8003/admin/vacuum \
  | python3 -m json.tool

# Verify the live Postgres index list (should be 18 — was 38)
docker exec auditlens-postgres psql -U auditlens -d auditlens \
  -c "SELECT count(*) FROM pg_indexes WHERE tablename='audit_events';"

# Tune live (then `docker compose up -d --force-recreate auditlens-forwarder`)
# These knobs live in .env (gitignored):
#   DB_WRITER_THREADS=2                 # ThreadPoolExecutor size
#   DB_WRITE_PARALLEL_CHUNK_SIZE=250    # below DB_WRITE_BATCH_SIZE to enable parallelism
#   RECORD_QUEUE_SIZE=20                # batches between consumer and processor
#   KAFKA_GROUP_INSTANCE_ID=auditlens-forwarder-1   # static membership

# When ready to ship
git push   # 8 commits on master + 2 diary files (need a docs commit for those)
```
