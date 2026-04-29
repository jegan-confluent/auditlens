# Security Audit Checklist

Use this checklist before calling an AuditLens deployment safe for anything beyond local or tightly controlled foundation testing.

## 1. Secrets and Credentials

Checklist:

- [ ] No Kafka, API, Schema Registry, Grafana, or token secrets are committed to Git.
- [ ] Generated `install.local.yaml`, `.env`, `.secrets`, and token files are gitignored or otherwise excluded from source control.
- [ ] Setup output is reviewed to confirm secrets are masked.
- [ ] No operator workflow uses `docker compose config` without the `--quiet` form in a shared terminal session.
- [ ] Local secret files have restrictive permissions.

What the repo currently supports:

- Bootstrap masking exists in `src/product/bootstrap.py`.
- Forwarder startup config logging masks secret-bearing keys.
- This is not the same as end-to-end secret hygiene. Shell history, copied files, and dashboard docs can still leak operational secrets.

Safe validation commands:

```bash
grep -R "password\|secret\|api_key\|token" . --exclude-dir=.git
docker compose config --quiet
ls -l .env .secrets secrets 2>/dev/null
```

## 2. Network Exposure

Checklist:

- [ ] Landing page is localhost-only.
- [ ] Forwarder/API/metrics is localhost-only or behind protected ingress.
- [ ] Dashboard is localhost-only or otherwise access-controlled.
- [ ] Grafana is localhost-only or otherwise access-controlled.
- [ ] Prometheus is not exposed outside localhost, and admin API remains disabled unless explicitly re-enabled for troubleshooting.
- [ ] Storage pressure warnings are reviewed before operators assume persistence is safe.
- [ ] Loki is not exposed unless intentionally required.

Current repo reality:

- Landing binds to `127.0.0.1`.
- Forwarder/API/metrics, dashboard, Grafana, Prometheus, and Loki now bind to `127.0.0.1` in the default local Compose file.
- Prometheus admin API is disabled by default.
- Landing and dashboard now surface SQLite storage pressure, but that visibility does not replace disk-level monitoring.

Safe validation commands:

```bash
docker compose ps
rg -n "ports:|127.0.0.1|enable-admin-api" docker-compose.yml
curl http://localhost:8088/status
curl http://localhost:8003/health
```

## 3. Authentication and Authorization

Checklist:

- [ ] `API_AUTH_ENABLED=true` when API is exposed beyond a single developer machine.
- [ ] Token file exists and contains scoped roles for intended operators.
- [ ] RBAC scope filtering is tested for organization, environment, and cluster boundaries.
- [ ] Export requires exporter/admin role.
- [ ] Dashboard access is separately protected, because it does not inherit API auth.
- [ ] Grafana default password is changed.

Current repo reality:

- Forwarder API auth and RBAC exist in `src/product/auth.py` and request handling.
- Dashboard auth does not exist.
- Grafana startup now refuses an unset or `admin` password, and the installer generates `GF_SECURITY_ADMIN_PASSWORD`.

Safe validation commands:

```bash
rg -n "API_AUTH_ENABLED|require_view|require_export|scope_allows" audit_forwarder.py src/product/auth.py
rg -n "GF_SECURITY_ADMIN_PASSWORD|GF_ADMIN_PASSWORD" docker-compose.yml
```

## 4. Data Protection

Checklist:

- [ ] Operators recognize that audit records include sensitive metadata: principals, emails, IPs, API key identifiers, resource names, RBAC/ACL details.
- [ ] Export controls are enabled and tested through the API path.
- [ ] Sensitive data displayed in logs or dashboards is reviewed for least exposure.
- [ ] Kafka uses TLS/SASL.
- [ ] Encryption at rest for SQLite volume is provided by host or platform controls.

Current repo reality:

- Encryption in transit for Kafka is part of the current connection model.
- Encryption at rest is not provided by AuditLens itself.
- Audit-of-audit visibility is incomplete because dashboard direct Kafka reads bypass API audit logging.

## 5. Logging and Observability

Checklist:

- [ ] Logs are checked for obvious secrets or tokens.
- [ ] Logs are reviewed for principal/IP overexposure.
- [ ] API audit log table is populated when API search/export is used.
- [ ] Operators understand that dashboard access is not captured as product access logging.

Current repo reality:

- Secret masking exists for startup/config logging.
- Full log redaction for principals, IPs, and other sensitive metadata is not fully implemented.
- API audit log storage exists in SQLite.
- Dashboard direct Kafka reads are outside the audit-of-audit control path.

Safe validation commands:

```bash
docker compose logs --tail=200 auditlens-forwarder | grep -Ei "password|secret|token|api[_-]?key"
docker compose logs --tail=200 dashboard | grep -Ei "password|secret|token|api[_-]?key"
```

## 6. Compliance Readiness

Current assessment:

- Suitable for local development and controlled foundation testing on a single instance.
- Not suitable for shared production use without additional hardening.
- Not suitable for customer-facing shared deployment while the dashboard reads Kafka directly and bypasses product auth and audit logging.

Missing controls before stronger deployment claims:

- Complete auth boundary for all user-facing surfaces.
- Enforced localhost-only or protected ingress defaults for operational services in every deployment mode.
- Continued validation that Prometheus admin API remains disabled by default.
- Enforced audit-of-audit access for all read paths.
- Stronger persistent storage and retention controls.
- Clear encryption-at-rest posture for persisted audit data.
- Formal security review of dashboard IAM API lookups and exposed local files such as email caches.

## 7. Security Validation Commands

Use these commands carefully. They are intended to check exposure and hygiene without printing raw secrets.

```bash
grep -R "password|secret|api_key|token" . --exclude-dir=.git

docker compose ps

docker compose config --quiet

curl http://localhost:8003/health
curl http://localhost:8088/status

docker compose logs --tail=100 auditlens-forwarder
docker compose logs --tail=100 dashboard
```

Review guidance:

- Do not paste full `.env`, `.secrets`, or token-file contents into tickets or chat.
- Do not run plain `docker compose config` in a shared terminal if `.secrets` contains live credentials.
- Treat any occurrence of live-looking API keys, passwords, or tokens in logs as a security defect, not as expected debug output.
