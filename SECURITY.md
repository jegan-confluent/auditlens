# Security Policy — AuditLens

## Reporting vulnerabilities

If you discover a security vulnerability in AuditLens, please report it responsibly:

- **GitHub private advisory:** Open a [Security Advisory](https://github.com/your-org/auditlens/security/advisories/new) (preferred — keeps it private until patched)
- **Email:** security@your-org.example — replace with your real address before publishing

Please include: a description of the issue, reproduction steps, and the potential impact.
We aim to acknowledge reports within 48 hours and provide a fix timeline within 7 days.

Do **not** open a public GitHub issue for security vulnerabilities.

---

## Security model

AuditLens is a **self-hosted** tool. This means:

- **No data leaves your deployment.** Audit events are consumed from your Confluent Cloud
  account and stored in your own database (SQLite or Postgres). Nothing is forwarded to
  any external party.
- **No telemetry.** AuditLens does not collect usage metrics, error reports, or any other
  telemetry. There is no phone-home mechanism.
- **No external analytics.** No third-party analytics scripts, beacons, or tracking pixels.

The only outbound network connections AuditLens makes are:

| Destination | Purpose | When |
|-------------|---------|------|
| `api.confluent.cloud` | Confluent Cloud Admin API (IAM enrichment) | Only when `IAM_ENRICHMENT_ENABLED=true` |
| `pkc-*.region.provider.confluent.cloud` | Your Kafka bootstrap endpoint | Always (audit event ingestion) |
| User-configured webhook URLs | Slack / Teams / custom alerts | Only when `notifications.yml` is configured |

You can verify these claims by inspecting `audit_forwarder.py` and `src/` — there are no
other outbound HTTP calls.

---

## Default security posture (read before deploying)

| Setting | Default | Production recommendation |
|---------|---------|--------------------------|
| `API_AUTH_ENABLED` | `false` | **Must set to `true`** |
| `GRAFANA_ADMIN_PASSWORD` | `changeme` | **Must change before network exposure** |
| `GF_SECURITY_ADMIN_PASSWORD` | `admin` (root compose) / `changeme` (deploy compose) | **Must change** |
| `POSTGRES_PASSWORD` | `auditlens` | Change for any shared environment |
| Streamlit dashboards | Disabled (profile gate) | Keep disabled; set `STREAMLIT_PASSWORD` if needed |
| API port (8080) | `127.0.0.1` only | Put behind reverse proxy with TLS for remote access |
| Frontend port (3000) | `127.0.0.1` only | Put behind reverse proxy with TLS for remote access |
| Grafana port (3001) | `127.0.0.1` only | Keep localhost only or add reverse proxy |
| Prometheus port (9090) | `127.0.0.1` only | Keep localhost only |
| Postgres port (5432) | `127.0.0.1` only | Keep localhost only |

**The most critical action before any external exposure:** set `API_AUTH_ENABLED=true`.

---

## Enabling authentication

1. In `.env`, set:
   ```
   API_AUTH_ENABLED=true
   ```

2. Generate a token file. Each token has a role (`viewer`, `responder`, or `admin`):
   ```json
   [
     {"token": "your-viewer-token-here",    "role": "viewer",    "actor_id": "readonly-user"},
     {"token": "your-responder-token-here", "role": "responder", "actor_id": "ops-team"},
     {"token": "your-admin-token-here",     "role": "admin",     "actor_id": "admin-user"}
   ]
   ```

3. Save the file (e.g. `./secrets/api-tokens.json`) and set:
   ```
   API_AUTH_TOKEN_FILE=/run/secrets/auditlens-api-tokens.json
   ```
   Or use the inline env var:
   ```
   API_AUTH_TOKENS_JSON=[{"token":"...","role":"admin","actor_id":"admin"}]
   ```

4. Restart the API: `docker compose up -d --force-recreate api`

5. Verify with:
   ```bash
   curl -s http://127.0.0.1:8080/events \
     -H "Authorization: Bearer your-viewer-token-here" | jq '.total'
   ```

### Role permissions

| Role | Can read events/summary/filters | Can triage/suppress | Can access /admin |
|------|--------------------------------|---------------------|-------------------|
| viewer | ✓ | ✗ | ✗ |
| responder | ✓ | ✓ | ✗ |
| admin | ✓ | ✓ | ✓ |

---

## Network hardening

### Reverse proxy with HTTPS (recommended for remote access)

AuditLens is designed to sit behind a reverse proxy. Example nginx snippet:

```nginx
server {
    listen 443 ssl;
    server_name auditlens.your-domain.example;

    ssl_certificate     /etc/ssl/certs/auditlens.crt;
    ssl_certificate_key /etc/ssl/private/auditlens.key;

    location /api/ {
        proxy_pass http://127.0.0.1:8080/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        proxy_pass http://127.0.0.1:3000/;
        proxy_set_header Host $host;
    }
}
```

Keep Prometheus (9090), Grafana (3001), Postgres (5432), and the forwarder metrics
(8003) at localhost only. They do not need to be externally accessible.

### Firewall rules

If deploying on a cloud VM, ensure these ports are NOT open to the internet:
- 5432 (Postgres)
- 9090 (Prometheus)
- 8003 (Forwarder metrics)
- 3001 (Grafana) — unless you explicitly want remote Grafana access

Ports that may be proxied (with TLS and auth in front):
- 8080 (API) → proxy as `/api/`
- 3000 (Frontend) → proxy as `/`

---

## Secrets management

AuditLens supports a two-tier secrets model so the same image runs on any platform.

### Default — environment variables (platform-agnostic)

All secrets are read from `.env` (non-sensitive) and `.secrets` (sensitive) on the host. This is the default and works on AWS, GCP, Azure, bare metal, or any Docker host. See `.env.example` for the full list of required values.

Never commit `.env` or `.secrets` — both are gitignored. Use Docker Secrets or your orchestrator's secret injection (Kubernetes Secrets, ECS Task env, etc.) to deliver them to the container.

### Optional hardening — AWS Secrets Manager (AWS EC2 only)

If you are running on AWS EC2, you can store secrets in AWS Secrets Manager instead of `.env`:

1. Run `make secrets-create` to push `.env` values to ASM
2. Set `AWS_SECRETS_MANAGER_ENABLED=true` in `.env`
3. Set `AWS_REGION` to your EC2 region
4. Attach an IAM role to your EC2 instance with `secretsmanager:GetSecretValue` on `auditlens/*` (see `infra/aws/setup_secrets_manager_role.sh`)

Secrets are cached in memory for 15 minutes and auto-refreshed. No restart is needed after rotation — run `make secrets-rotate`.

> GCP Secret Manager and Azure Key Vault are not yet supported. Contributions welcome.

---

## Container security notes

- The forwarder runs with `read_only: true` and `cap_drop: ALL` with only `NET_BIND_SERVICE` added back.
- Prometheus, Grafana, Loki, and Promtail run as non-root users.
- The API and frontend containers currently run as root. For production hardening, add
  `user: "1000:1000"` to these services after ensuring the application can start as non-root.
