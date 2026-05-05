## [2026-04-29] Session [Fresh Runability]

### Fixed
- Cleaned fresh-machine runability by ignoring local bundles, archives, env files, frontend build output, Python caches, data directories, and SQLite database files.
  Why: A fresh clone should not pick up local runtime artifacts or package backup files.
  Files: .gitignore, .dockerignore

- Made Docker Compose modes clearer: default product mode is forwarder/API/frontend, Postgres profile adds Postgres, observability profile adds only monitoring services, and Streamlit remains available behind the `streamlit` profile.
  Why: The production path should start cleanly without optional observability or legacy UI services unless explicitly requested.
  Files: docker-compose.yml

- Sanitized install templates and documentation token examples.
  Why: Safe templates must not contain real-looking credentials or copy-pasteable secret values.
  Files: install.template.yaml, docs/MCP_INTEGRATION_GUIDE.md

### Added
- Added a safe `.env.example` for SQLite demo, Postgres product mode, forwarder DB writer settings, and frontend API URL configuration.
  Why: A fresh user needs a known-good local template without real secrets.
  Files: .env.example

- Added operational scripts for SQLite demo startup, Postgres product startup, stop, health checks, and security scanning.
  Why: A fresh user should be able to copy `.env.example`, run one script, and verify API/UI health.
  Files: scripts/run_sqlite_demo.sh, scripts/run_postgres_product.sh, scripts/stop_all.sh, scripts/health_check.sh, scripts/security_scan.sh

- Rewrote README quickstart for SQLite demo, Postgres product mode, optional observability, health checks, stopping, troubleshooting, and security hygiene.
  Why: Fresh-machine setup should be command-driven and easy to validate.
  Files: README.md

### Removed
- Removed checked-in Terraform provider cache binaries from `deploy/terraform/aws/.terraform`.
  Why: Provider caches are local machine artifacts, are very large, and should be restored by Terraform rather than committed.
  Files: deploy/terraform/aws/.terraform/providers/registry.terraform.io/hashicorp/aws/5.100.0/darwin_arm64/LICENSE.txt, deploy/terraform/aws/.terraform/providers/registry.terraform.io/hashicorp/aws/5.100.0/darwin_arm64/terraform-provider-aws_v5.100.0_x5, deploy/terraform/aws/.terraform/providers/registry.terraform.io/hashicorp/random/3.7.2/darwin_arm64/LICENSE.txt, deploy/terraform/aws/.terraform/providers/registry.terraform.io/hashicorp/random/3.7.2/darwin_arm64/terraform-provider-random_v3.7.2_x5

### Architecture Decisions
- Keep Streamlit present but outside the default product startup path.
  Why: Streamlit is preserved for compatibility while the production path remains FastAPI + Next.js.
  Impact: Use `docker compose --profile streamlit up -d dashboard` when the legacy dashboard is needed.

### Known Issues / Not Done
- Postgres product mode was not started with real Kafka credentials in this pass.
  Why deferred: Local `.env` was intentionally removed for security hygiene; the script was validated to fail clearly when credentials are missing.
