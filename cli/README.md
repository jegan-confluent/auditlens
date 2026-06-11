# AuditLens CLI

A single-file Python CLI for browsing, exporting, and monitoring an
AuditLens deployment without leaving the terminal. No AuditLens
codebase import — just `click` + `httpx` + the Python standard library.

## Install

```bash
cd cli
pip install -r requirements.txt
# (or in a venv: python -m venv .venv && .venv/bin/pip install -r requirements.txt)
```

## Configure

The CLI reads, in order: command-line flags → environment variables →
`~/.auditlens.conf` → built-in defaults.

```bash
python auditlens.py config set --url http://98.95.144.160
python auditlens.py config set --token eyJhbGciOi...   # only if API_AUTH_ENABLED=true
python auditlens.py config show                        # prints resolved config (token masked)
```

| Env var | Conf key | Default | Meaning |
|---|---|---|---|
| `AUDITLENS_URL` | `url` | `http://localhost` | Base URL of the deployment (Caddy adds /api). |
| `AUDITLENS_TOKEN` | `token` | empty | Bearer token (only needed when API_AUTH_ENABLED=true). |
| `AUDITLENS_PG_HOST` | `pg_host` | empty | Reserved for direct Postgres queries. |
| `AUDITLENS_PG_USER` | `pg_user` | `auditlens` | Postgres user for `pipeline indexes`. |
| `AUDITLENS_PG_DB` | `pg_db` | `auditlens` | Postgres database for `pipeline indexes`. |
| — | `compose_file` | `~/AuditLens/docker-compose.prod.yml` | docker-compose file the `pipeline indexes` command shells into. |

`~/.auditlens.conf` is written with `chmod 600`.

## Commands

### events list

```bash
python auditlens.py events list                         # last 24h, 20 rows
python auditlens.py events list --signal action_required --since 7d
python auditlens.py events list --actor user@example.com --limit 100
python auditlens.py events list --json | jq            # raw JSON for further processing
```

Output (table form):

| Column | Source |
|---|---|
| Time | `timestamp` converted to local TZ, `Jun 03 11:44` |
| Actor | `actor_display_name` or fall-back `actor` |
| Action | `action` |
| Signal | `signal_type` with colour: red / yellow / green / dim |
| Reason | `decision_reason` |
| Risk | `risk_level` |

`--since` accepts the same `Nm`/`Nh`/`Nd` grammar as the web filter
(`7d` and `30d` are translated to hours client-side because the API
regex only allows `[1-9][0-9]*[mh]`).

### events get

```bash
python auditlens.py events get 77549
```

Prints every field of the event as `key: value`. Nested dicts/lists are
inlined as JSON for grep-ability.

### events export

```bash
python auditlens.py events export --since 7d --format csv --out events.csv
python auditlens.py events export --signal action_required --format json > alerts.json
```

Streams from `/api/events/export`. Hard cap is `EXPORT_MAX_ROWS` (50,000)
on the server; the CSV gets a `# Truncated to EXPORT_MAX_ROWS=50000…`
header comment if you hit the cap.

### stats compare

```bash
python auditlens.py stats compare --period-a 24h --period-b 7d
python auditlens.py stats compare --period-a 1h --period-b 24h
```

Hits `/api/events/compare` and renders a small side-by-side table:

```
Metric             Period A (24h)            Period B (7d)
-----------------  ------------------------  ------------------------
Total events       1759                      8625
Action required    120                       540
Attention          88                        310
Informational      201                       1208
Noise              1350                      6567
Top actor          user@x.com (94)           user@x.com (430)
Top action         org.DeleteEnvironment (4) org.DeleteEnvironment (12)
```

### pipeline status

```bash
python auditlens.py pipeline status
```

No SSH required. Calls `/health`, `/api/events/compare?period_a=5m&period_b=60m`,
and `/api/events?limit=1` to surface:

- API HTTP status
- Last-event local timestamp + minutes-ago
- Events seen in the last 5 minutes and 60 minutes
- A red `WARNING` line if the last event is older than 30 minutes (the
  same threshold the forwarder watchdog uses).

### pipeline indexes

```bash
python auditlens.py pipeline indexes
```

Runs `docker compose -f $compose_file exec -T postgres psql -U $pg_user
-d $pg_db -c '\di audit_events*'`, parses the output, and prints a
clean table of index name / type / table. Must run from the deploy host
(needs `docker` on PATH).

### alerts test

```bash
python auditlens.py alerts test
```

POSTs to `/api/settings/notifications/test` — the same wire as the
Settings UI's "Send test notification" button. Every enabled Slack/Teams
destination in `notifications.yml` gets a real message; per-destination
pass/fail comes back as a summary table. Requires the `admin` role when
auth is enabled.

### doctor

```bash
python auditlens.py doctor      # or: make doctor
```

End-to-end deployment health check, designed to be the first thing you
run when something looks off. Seven independent checks run sequentially;
one failing check never aborts the others, and a summary table prints
at the end with the worst severity driving the exit code.

| Section | What it does |
|---|---|
| Docker services | `docker compose ps`; flags any container that is not `running` (critical), `unhealthy` (critical), `starting` (warn), or missing a healthcheck (warn). Tails the last 5 log lines on critical failures. |
| Forwarder connectivity | `GET http://<host>:8003/health`; reports HTTP status + `last_event` freshness; warns if last event > 30 min. |
| API health | `GET <AUDITLENS_URL>/health` (warns over 2 s) + `/api/events?limit=1` smoke test. |
| Postgres connectivity | `docker compose exec -T postgres psql` for signal-row, noise-row, and last-hour counts; warns when zero events in the last hour. |
| Dead-tuple bloat | `SELECT relname, n_dead_tup, n_live_tup FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 5`; warns when any table > 100 000 dead tuples. |
| Config sanity | Parses `.env` next to the compose file; verifies `AUDIT_BOOTSTRAP`, `AUDIT_TOPIC`, `DEST_BOOTSTRAP`, `DATABASE_URL`, `CORS_ORIGINS`, `NEXT_PUBLIC_API_BASE_URL` are non-empty; warns if `CORS_ORIGINS` omits the live domain or `NEXT_PUBLIC_API_BASE_URL` doesn't end with `/api`. Values are never printed — only ✅ set / ❌ missing. |
| Domain reachability | `GET https://auditlens.aws.cse.confluent.io/health` with a 5 s timeout. Reported as `skipped` (not critical) if the host has no internet. |

Sample summary (live deploy):

```
Component                     Status        Detail
─────────────────────────────────────────────────────────────────
Docker: mcp-server            ❌ critical  state=restarting
Docker: auditlens-forwarder   ✅ ok        healthy
Docker: api                   ✅ ok        healthy
Docker: postgres              ✅ ok        healthy
Forwarder connectivity        ✅ ok        healthy
API health                    ✅ ok        18ms
Postgres rows                 ✅ ok        19,718 signal + 3,451,365 noise
Pipeline freshness            ✅ ok        73 events in last hour
Dead-tuple bloat              ✅ ok        no tables over threshold
Config vars                   ✅ ok        all required vars set
Domain reachability           ✅ ok        HTTP 200 (27ms)
```

`Makefile` exposes `make doctor` and `make cli-status` (compact pipeline
freshness) so cron / CI can wire up health gates without touching Python
directly.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success (all green; skipped checks don't fail) |
| `1` | `doctor`: any warning. Other commands: HTTP or auth error |
| `2` | `doctor`: any critical failure. `alerts test`: endpoint missing |

## Notes & limitations

- The CLI is a wire-protocol client only. It does not import any AuditLens
  Python modules and works against any deployment that exposes the same
  endpoints.
- `pipeline indexes` shells out to `docker`; the other commands are
  pure HTTPS and work from anywhere with network access.
- Colour is auto-disabled if stdout is not a TTY (click default).
