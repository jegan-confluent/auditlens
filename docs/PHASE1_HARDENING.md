## Files changed
- `.gitignore` - expanded secret and backup ignore patterns so local credentials and backups stay out of commits.
- `.env.example` - flipped `API_AUTH_ENABLED` to `true` and added the local-dev-only warning comment.
- `docs/SECURITY.md` - added the secret rotation warning block requested in the hardening pass.
- `backend/app/main.py` - restricted CORS headers, stripped query strings from slow-request logs, removed request paths from 500 responses, added security headers, and logged a startup warning when auth is enabled but tokens are missing.
- `backend/app/api/routes/events.py` - redacted `raw_payload_json` by default on detail fetches and returned the full payload only for authenticated admin callers.
- `backend/app/schemas/event.py` - made `raw_payload_json` optional so redacted detail responses serialize cleanly.
- `src/product/auth.py` - replaced token lookup with constant-time comparison and hardened malformed-token handling.
- `audit_forwarder.py` - bounded producer retries, added DLQ fallback on retry exhaustion, exposed `produce_retry_exhausted_total`, and kept DB write buffers intact until write success.
- `backend/tests/test_api.py` - added redaction, admin payload, and security-header coverage.
- `tests/test_productization.py` - added auth invalid-token tests plus forwarder retry/buffer regression tests.
- `.github/workflows/tests.yml` - added a PR/push test gate that runs compileall, pytest, and the frontend build.

## Security issues fixed
- **S-CRITICAL-1: Live Confluent API keys in working-tree `.env`** -> not auto-rotated, but `.env` remains ignored and the repo now has stronger ignore rules plus the secret-rotation warning document. Why: reduce accidental commit risk. Files: `.gitignore`, `docs/SECURITY.md`.
- **S-CRITICAL-2: API authentication disabled by default** -> `API_AUTH_ENABLED` now defaults to `true` in the example env, and startup warns if auth is enabled without valid tokens. Why: safer default posture. Files: `.env.example`, `backend/app/main.py`.
- **S-CRITICAL-3: Raw audit payloads returned unredacted** -> list responses still exclude the payload entirely, and detail responses now redact by default unless the caller is an authenticated admin. Why: remove unauthenticated payload disclosure. Files: `backend/app/api/routes/events.py`, `backend/app/schemas/event.py`, `backend/tests/test_api.py`.
- **S-CRITICAL-4: Offset committed even when DB write may have lost events** -> DB write buffers now stay intact until `write_batch()` succeeds, and there is a regression test for retryable failures. Why: preserve retryability and at-least-once semantics. Files: `audit_forwarder.py`, `tests/test_productization.py`.
- **S-CRITICAL-5: `safe_produce()` unbounded retry on `BufferError`** -> retries are capped at `MAX_PRODUCE_RETRIES=10`, exhausted retries increment a metric, and the event is routed to DLQ when available. Why: prevent infinite producer stalls. Files: `audit_forwarder.py`, `tests/test_productization.py`.
- **S-HIGH-5: CORS wildcard headers with credentials** -> CORS headers are now allowlisted to `Content-Type`, `Authorization`, and `X-Actor`. Why: narrow browser exposure. Files: `backend/app/main.py`.
- **S-HIGH-6: Token comparison not constant-time** -> token matching now uses `hmac.compare_digest` and rejects malformed token types without raising. Why: remove timing leakage and malformed-input crashes. Files: `src/product/auth.py`, `tests/test_productization.py`.
- **S-MEDIUM-12: Slow-query logger emitted query strings** -> slow-request logging now uses the path only. Why: keep query parameters like emails/IPs out of logs. Files: `backend/app/main.py`.
- **S-MEDIUM-19: Generic 500 handler echoed request path** -> 500 responses no longer include the path; the path is logged server-side only. Why: avoid returning internal route details to clients. Files: `backend/app/main.py`.
- **S-MEDIUM-25: No CSP / HSTS / X-Frame-Options on backend** -> added basic response hardening headers. Why: reduce browser-side abuse surface. Files: `backend/app/main.py`, `backend/tests/test_api.py`.
- **S-HIGH-14: No automated test execution in CI** -> added a CI test job that runs compileall, pytest, and the frontend build. Why: prevent regressions from merging untested. Files: `.github/workflows/tests.yml`.

## Tests added
- `backend/tests/test_api.py::test_event_detail_redacts_raw_payload_json_for_non_admin` - verifies unauthenticated detail responses return a redacted payload.
- `backend/tests/test_api.py::test_event_detail_includes_raw_payload_json_for_admin` - verifies an admin token gets the full payload.
- `backend/tests/test_api.py::test_health_returns_ok` - extended to assert the security headers are present.
- `tests/test_productization.py::test_authenticator_handles_invalid_token_without_error` - verifies an invalid token returns 401 cleanly.
- `tests/test_productization.py::test_authenticator_handles_malformed_token_type_without_error` - verifies malformed token types do not raise.
- `tests/test_productization.py::test_safe_produce_exhausts_retries_and_records_metric` - verifies bounded retries, metric increment, and DLQ routing.
- `tests/test_productization.py::test_flush_db_writer_buffer_retains_payloads_on_failure` - verifies the DB write buffer stays intact after a failed batch write and retries cleanly.

## Validation results
`python3 -m compileall backend/app src/product scripts`
```text
Listing 'backend/app'...
Listing 'backend/app/api'...
Listing 'backend/app/api/routes'...
Listing 'backend/app/core'...
Listing 'backend/app/db'...
Listing 'backend/app/db/migrations'...
Listing 'backend/app/schemas'...
Listing 'backend/app/services'...
Listing 'src/product'...
Compiling 'src/product/auth.py'...
Listing 'scripts'...
Listing 'scripts/deprecated'...
```

`pytest -q --tb=short`
```text
468 passed, 5 skipped in 44.18s
```

`git diff --check`
```text
```

`npm --prefix frontend run build`
```text
⚠ Warning: Next.js inferred your workspace root, but it may not be correct.
Detected additional lockfiles:
  * /Users/jegan/playground/AuditLens/frontend/package-lock.json
  * /Users/jegan/package-lock.json
✓ Compiled successfully in 1730ms
✓ Generating static pages (8/8)
Route (app)                                 Size  First Load JS
┌ ○ /                                      124 B         102 kB
├ ○ /_not-found                            998 B         103 kB
├ ○ /dashboard                           1.67 kB         107 kB
├ ○ /events                              4.32 kB         109 kB
├ ○ /layout-lab                            124 B         102 kB
└ ○ /system                              1.46 kB         104 kB
○  (Static)  prerendered as static content
```

## Remaining P0/P1 risks
- **S-CRITICAL-1: Live Confluent API keys in working-tree `.env`** - not rotated here because that requires operator action in Confluent Cloud and coordination with deployment environments.
- **S-HIGH-4: Streamlit dashboards have no authentication** - left untouched because this pass was limited to security hardening, not product cleanup.
- **S-HIGH-6: `Dockerfile.alpine` placeholder digest pin** - deferred because it is a container build hardening task, not an API/runtime fix.
- **S-HIGH-7: Default Grafana admin password** - deferred because it lives in deployment config and needs an operator-managed secret.
- **S-HIGH-8: ALB HTTPS listener is commented out** - deferred because it requires infrastructure changes and certificates.
- **S-HIGH-11: No statement timeout on the API DB session** - deferred because it is a performance hardening change and needs deployment tuning.
- **S-HIGH-13: Unmasked delivery error logging** - deferred because it is part of forwarder logging hygiene and would need a separate review of the delivery error path.
- **S-HIGH-15: Outdated dependencies** - deferred because it is a wider dependency upgrade pass, not a surgical security change.
- **S-HIGH-16: Frontend race condition on filter changes** - deferred because it is a UX/data-consistency fix rather than a direct security issue.
