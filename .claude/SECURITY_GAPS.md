# AuditLens Security Evaluation — Gap Analysis

**Date:** 2026-05-13
**Auditor:** Claude Code (automated)
**Version:** v3.1.0

---

## Self-Check Answers

**Q1. API_AUTH_ENABLED default?**
`false` — set as environment default in `docker-compose.yml:54` (`${API_AUTH_ENABLED:-false}`)
and checked in `backend/app/main.py:97` (`os.getenv("API_AUTH_ENABLED", "false")`).
Auth is **disabled by default** in every deployment.

**Q2. Routes without _require_viewer or _require_admin:**

| Route | File | Auth? | Notes |
|-------|------|-------|-------|
| GET /health | health.py:9 | None | Intentional — Docker healthcheck |
| GET /live | readiness.py:18 | None | Intentional — liveness probe |
| GET /ready | readiness.py:23 | None | Intentional — readiness probe |
| GET /pipeline/ready | readiness.py:52 | None | Intentional — probe |
| GET /ingestion/ready | readiness.py:53 | None | Intentional — probe |
| GET /events | events.py:57 | **NONE** | **Serves PII — principals, IPs, actions** |
| GET /events/{id} | events.py:197 | **NONE** | **Can expose raw_payload_json** |
| GET /patterns | patterns.py:78 | **NONE** | Exposes security pattern intel |
| GET /system/status | system.py:22 | **NONE** | Exposes DB sizes, pipeline lag |
| GET /system/forwarder-health | system.py:27 | **NONE** | Exposes forwarder internals |
| POST /system/vacuum | system.py:43 | **NONE** | **Privileged ops, no auth at all** |

(POST /events/{id}/triage, POST /patterns/*/suppress, /settings/*, /admin/* are correctly guarded)

**Q3. Streamlit dashboards auth?**
No authentication in `dashboard/app.py`, `dashboard/app_clean.py`, or
`dashboard/app_legacy_full.py`. Anyone who can reach port 8503 gets full access to
all audit data and the Confluent connection config.
Port: 8503 (bound to 127.0.0.1 in docker-compose).
The `dashboard` service has `profiles: ["streamlit", "dev"]` so it does NOT start
with plain `docker compose up`. However, there is no auth gate inside the app itself —
if someone enables the streamlit profile, the dashboard is fully open.

**Q4. Grafana admin password?**
- `docker-compose.yml:350`: `${GF_SECURITY_ADMIN_PASSWORD:-admin}` — **still defaults to `admin`**
- `deploy/docker/docker-compose.yml:116`: `${GRAFANA_ADMIN_PASSWORD:-changeme}` — fixed in prior session
- Root compose uses a DIFFERENT env var name (`GF_SECURITY_ADMIN_PASSWORD`) from the
  deploy compose (`GRAFANA_ADMIN_PASSWORD`), and the root still defaults to `admin`.

**Q5. Forwarder outbound HTTP beyond Confluent Cloud?**
Two outbound HTTP paths exist:
1. `src/alerting/webhook_sender.py:251` — `requests.post(url, ...)` where `url` comes
   from user-configured `notifications.yml`. Expected and documented.
2. `src/confluent_api/admin_client.py:140` / `src/identity/enricher.py:124` — httpx calls
   to `api.confluent.cloud`. Expected and documented.
No phone-home, telemetry, or third-party analytics calls found.

**Q6. Secrets in git history?**
No hardcoded credentials found in git history. `git log --all -p` grep on
`(api_key|secret|password)\s*=` returned only test fixtures with sentinel values
and patterns like `sasl.password=****`. Clean.

**Q7. Docker image pinning?**
All third-party images are tagged but NOT digest-pinned:
- `postgres:16-alpine` (no digest)
- `prom/prometheus:v2.54.1` (no digest)
- `grafana/grafana:11.3.1` (no digest)
- `prometheuscommunity/postgres-exporter:v0.15.0` (no digest)
- `grafana/loki:3.2.1` (no digest)
- `grafana/promtail:3.2.1` (no digest)
- `python:3.11-slim` (no digest — landing page)
A `docker compose pull` can silently update any of these.

**Q8. Containers running as root?**
| Service | User field | Runs as |
|---------|-----------|---------|
| auditlens-forwarder | absent | **root** |
| dashboard (streamlit) | absent | **root** |
| auditlens-api | absent | **root** (has CHOWN/SETGID/SETUID caps) |
| auditlens-frontend | absent | **root** |
| auditlens-postgres | absent | root (managed internally by postgres image) |
| prometheus | `65534:65534` | nobody ✓ |
| grafana | `472:472` | grafana ✓ |
| loki | `10001:10001` | loki ✓ |
| promtail | `10001:10001` | loki ✓ |

**Q9. Ports bound to 0.0.0.0?**
All main service ports are correctly bound to `127.0.0.1`. One exception:
- `mcp-server` (profile: "future"): `"${MCP_PORT:-8080}:${MCP_PORT:-8080}"` at line 528 —
  **no 127.0.0.1 prefix**, so it would bind to 0.0.0.0 if the "future" profile is enabled.
  Additionally `MCP_HOST=0.0.0.0` is set in the environment.
  This is in a disabled profile but is a latent risk for any operator who enables it.

**Q10. README.md security section?**
README has "## Security Check" (line 250) and "## Local Security Posture" (line 258).
Missing:
- No explicit "no telemetry / no phone-home" statement
- No default-credentials table listing what must be changed
- No step-by-step auth setup instructions
- No reverse proxy / TLS guidance
- No link to a SECURITY.md (which doesn't exist yet)

---

## RAG Summary

| Dimension | Rating | One-line reason |
|-----------|--------|-----------------|
| Authentication | 🔴 RED | Auth off by default; /events and /system routes fully open even when auth is enabled |
| Authorization | 🟡 AMBER | Admin/settings routes are guarded; /events, /patterns, /system/vacuum are not |
| Secrets management | 🟢 GREEN | No hardcoded secrets; AES-256-GCM for DB secrets; env vars correctly used |
| Network exposure | 🟢 GREEN | All ports 127.0.0.1-bound except MCP (disabled future profile) |
| Data privacy / PII | 🟡 AMBER | No telemetry, but /events serves raw PII with no auth gate |
| Dependency security | 🟡 AMBER | No known CVEs found, but safety scan unavailable; httpx 0.26.0 is behind current |
| Container hardening | 🟡 AMBER | cap_drop ALL + read_only on forwarder; api/frontend/dashboard run as root |
| Documentation | 🔴 RED | No SECURITY.md; README security section missing telemetry statement, auth how-to |

---

## Findings (sorted by severity)

---

### [HIGH] — /events and /events/{id} have no auth guard

- **File:** `backend/app/api/routes/events.py:57` (GET /events), `:197` (GET /events/{id})
- **What:** Both endpoints return audit log data including actor principals, source IPs, resource names,
  and raw_payload_json. Neither has `Depends(_require_viewer)`. An unauthenticated caller on
  localhost can enumerate every audit event including who did what, from which IP, on which resource.
- **Risk:** PII exfiltration (principal IDs, IPs). In a shared-host or compromised-adjacent-container
  scenario, all audit data is readable without any token.
- **Fix:** Add `_auth: None = Depends(_require_viewer)` to both route functions, following the
  pattern already applied to /failures and /deletions.

---

### [HIGH] — POST /system/vacuum has no auth guard

- **File:** `backend/app/api/routes/system.py:43`
- **What:** `POST /system/vacuum` triggers an HTTP POST to the forwarder's `/admin/vacuum` endpoint,
  which runs SQLite VACUUM on the forwarder's database. No authentication check at all — any
  process on localhost can trigger this. VACUUM locks the database during execution.
- **Risk:** Denial-of-service against the forwarder by repeatedly triggering expensive VACUUM
  operations. Also exposes the forwarder's admin interface indirectly.
- **Fix:** Add `_: None = Depends(require_admin)` (same pattern as other admin routes in admin.py).

---

### [HIGH] — GET /system/status and /system/forwarder-health expose infra details without auth

- **File:** `backend/app/api/routes/system.py:22` (status), `:27` (forwarder-health)
- **What:** Returns pipeline lag, DB sizes, consumer states, error counts, and forwarder health JSON —
  all without authentication.
- **Risk:** Attacker learns exactly what version, what consumer group state, how many events are
  buffered, and what errors exist. This is reconnaissance data for a targeted attack.
- **Fix:** Add `_auth: None = Depends(_require_viewer)` to both endpoints.

---

### [HIGH] — GET /patterns exposes security intelligence without auth

- **File:** `backend/app/api/routes/patterns.py:78`
- **What:** Returns the list of recurring patterns (actor + action + resource combinations) that have
  been detected. No authentication. An attacker can learn which actions are considered "expected"
  and which actors are being watched, then tune their attack to stay under the radar.
- **Risk:** Security-relevant intelligence leakage to unauthenticated callers.
- **Fix:** Add `_auth: None = Depends(_require_viewer)` to `GET /patterns`.

---

### [MEDIUM] — Root docker-compose.yml Grafana password still defaults to "admin"

- **File:** `docker-compose.yml:350`
- **What:** `GF_SECURITY_ADMIN_PASSWORD=${GF_SECURITY_ADMIN_PASSWORD:-admin}` — the default is
  `admin`. The prior fix applied to `deploy/docker/docker-compose.yml` (different var name,
  different default `changeme`), but the ROOT compose file was not updated.
  Any operator who runs `docker compose up` from the repo root gets Grafana with password `admin`.
- **Risk:** Grafana admin access lets an attacker modify dashboards, add data sources, and
  potentially reach the Prometheus/Postgres back-end via Grafana's proxy.
- **Fix:** Change line 350 to `${GF_SECURITY_ADMIN_PASSWORD:-changeme}` and add
  `GF_SECURITY_ADMIN_PASSWORD=changeme  # Change before any network exposure` to `.env.example`.

---

### [MEDIUM] — Docker images not pinned to digests

- **File:** `docker-compose.yml:250,297,337,421,455,387,606`
- **What:** All third-party images (postgres, prometheus, grafana, loki, promtail,
  postgres-exporter, python:3.11-slim) are referenced by tag only, no SHA256 digest.
- **Risk:** A `docker compose pull` on the customer's machine resolves the tag at pull time.
  If the upstream image maintainer pushes a compromised layer under the same tag (tag mutable),
  the customer pulls the compromised image. Supply chain attack vector.
- **Fix:** Pin each image to its current digest, e.g.
  `postgres:16-alpine@sha256:4e6e670b...`.

---

### [MEDIUM] — Streamlit dashboard has no authentication inside the app

- **File:** `dashboard/app.py:1-end`, `dashboard/app_clean.py:1-end`
- **What:** Neither dashboard file checks for credentials. The docker-compose service is
  behind `profiles: ["streamlit", "dev"]` (so it won't start by default), but there
  is no in-app password gate. Any operator who starts the streamlit profile for evaluation
  gets full, open access to all audit data.
- **Risk:** Data exfiltration if an operator uses the `dev` or `streamlit` profile in
  any shared or semi-public environment (e.g. a shared evaluation VM).
- **Fix:** See FIX 1 below.

---

### [MEDIUM] — MCP server (future profile) binds to 0.0.0.0 without 127.0.0.1 prefix

- **File:** `docker-compose.yml:528`
- **What:** Port mapping `"${MCP_PORT:-8080}:${MCP_PORT:-8080}"` has no `127.0.0.1:` prefix.
  `MCP_HOST=0.0.0.0` is also set as an environment variable.
  The profile is `["future"]` so it's disabled now, but this is a latent trap.
- **Risk:** Any operator who enables the "future" profile will expose the MCP server to all
  network interfaces, not just localhost. MCP_AUTH_TOKEN defaults to empty string.
- **Fix:** Change port to `"127.0.0.1:${MCP_PORT:-8080}:${MCP_PORT:-8080}"`.

---

### [LOW] — No SECURITY.md at repo root

- **File:** (missing)
- **What:** No SECURITY.md file exists. GitHub and enterprise security teams expect this for
  vulnerability disclosure and security model documentation.
- **Risk:** Security researchers don't know how to report vulnerabilities responsibly.
  Enterprise evaluators have no reference for the threat model.
- **Fix:** See FIX 2 below.

---

### [LOW] — README security section is incomplete for OSS publication

- **File:** `README.md:250-267`
- **What:** Has a brief "Local Security Posture" section but lacks:
  - No-telemetry assertion
  - Default credentials table
  - Step-by-step auth setup
  - Mac evaluation caveats
- **Fix:** See FIX 3 below.

---

### [LOW] — No startup log confirming no-telemetry

- **File:** `backend/app/main.py`, `audit_forwarder.py`
- **What:** No startup log line explicitly states that AuditLens does not phone home
  or send telemetry. Enterprise security teams often require this as a verifiable
  log assertion during security review.
- **Fix:** See FIX 5 below.

---

### [INFO] — Dynamic ALTER TABLE SQL uses hardcoded column names (not injection risk)

- **File:** `backend/app/db/database.py:151`
- **What:** `f"ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS {name} {type_sql}"` uses
  f-string interpolation, but `name` and `type_sql` come from a hardcoded dict in the
  same function (lines 112-144). Not user-controlled. Not a SQL injection risk.
- **Risk:** None. Flagged for completeness.

---

## Dependency Notes

`safety` was not available for automated CVE scan. Manual review of `requirements.txt`:
- `httpx==0.26.0` — current is 0.27.x+; no known critical CVEs in 0.26.0
- `requests==2.32.3` — current, no known CVEs
- `pydantic==2.9.2` — recent; no known CVEs
- `confluent-kafka==2.6.0` — current as of scan date
- No packages with known critical CVEs identified from version review.

`trivy` not available. Docker image layer scan was skipped.
