#!/usr/bin/env bash
# create_secrets.sh — push current .env / notifications.yml values to AWS
# Secrets Manager under the auditlens/{env}/* prefix.
#
# Reads values from .env (and notifications.yml for webhook URLs) at
# runtime — NO hardcoded credentials. The script is safe to commit.
#
# Idempotent: create-or-update pattern. First run uses create-secret;
# subsequent runs use put-secret-value to rotate the version.
#
# Usage:
#   bash scripts/secrets/create_secrets.sh                # apply
#   SECRET_DRY_RUN=true bash scripts/secrets/create_secrets.sh   # preview
#
# Env (optional):
#   AUDITLENS_ENV   {prod, staging, dev}   default: prod
#   AWS_PROFILE     AWS CLI profile         default: confluent
#   AWS_REGION      AWS region              default: ap-southeast-1
#
# All HIGH-sensitivity secrets from the Phase 0 inventory go to ASM.
# MEDIUM and LOW values stay in .env (they're not real credentials).

set -euo pipefail

# ---- config ---------------------------------------------------------
AUDITLENS_ENV="${AUDITLENS_ENV:-prod}"
AWS_PROFILE="${AWS_PROFILE:-confluent}"
AWS_REGION="${AWS_REGION:-ap-southeast-1}"
DRY_RUN="${SECRET_DRY_RUN:-false}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
NOTIFICATIONS_FILE="${REPO_ROOT}/notifications.yml"

# ---- helpers --------------------------------------------------------
log()  { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { log "ERROR: $*"; exit 1; }

require() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

# Read a key from .env. Strips inline comments and surrounding whitespace.
# Returns empty string if unset/missing/blank.
env_value() {
  local key="$1"
  [ -f "${ENV_FILE}" ] || return 0
  # Match "KEY=value" at line start, capture value up to first '#' or EOL.
  grep -E "^${key}=" "${ENV_FILE}" 2>/dev/null \
    | tail -n 1 \
    | sed -E "s/^${key}=//; s/[[:space:]]*#.*$//; s/^['\"]//; s/['\"]$//" \
    | awk '{$1=$1};1'
}

# Read first webhook_url under a destination named like "$1" from
# notifications.yml. Best-effort yq-free parser using awk; tolerates
# either single-quoted, double-quoted, or unquoted webhook URLs.
notifications_webhook() {
  local name_pattern="$1"
  [ -f "${NOTIFICATIONS_FILE}" ] || return 0
  awk -v pat="${name_pattern}" '
    /^\s*-\s*name:/ { current_name = $0; matched = 0; gsub(/^[^:]*:\s*/, "", current_name); }
    /webhook_url:/ {
      if (current_name ~ pat) {
        line = $0
        sub(/^[^:]*:\s*/, "", line)
        gsub(/^["'\''"]/, "", line); gsub(/["'\''"]$/, "", line)
        print line
        exit
      }
    }
  ' "${NOTIFICATIONS_FILE}"
}

# Build a JSON object from KEY=VALUE pairs passed as arguments. Skips
# pairs whose value is empty so ASM doesn't end up storing "".
json_object() {
  python3 -c '
import json, sys
out = {}
for arg in sys.argv[1:]:
    if "=" not in arg:
        continue
    k, v = arg.split("=", 1)
    if v == "":
        continue
    out[k] = v
print(json.dumps(out))
' "$@"
}

# Create-or-update a secret. $1 = secret name, $2 = JSON payload, $3 = description.
upsert_secret() {
  local name="$1"
  local payload="$2"
  local description="${3:-AuditLens managed secret}"

  if [ "${payload}" = "{}" ]; then
    log "skip ${name} — no non-empty values to push"
    return 0
  fi

  if [ "${DRY_RUN}" = "true" ]; then
    log "DRY-RUN would upsert ${name} (keys: $(printf '%s' "${payload}" | python3 -c 'import json,sys; print(",".join(json.load(sys.stdin).keys()))'))"
    return 0
  fi

  # Try create first; fall through to put-secret-value if it already exists.
  if aws secretsmanager create-secret \
      --name "${name}" \
      --description "${description}" \
      --secret-string "${payload}" \
      --profile "${AWS_PROFILE}" \
      --region "${AWS_REGION}" \
      >/tmp/secret_create.json 2>/tmp/secret_create.err; then
    local arn
    arn=$(python3 -c 'import json,sys; print(json.load(open("/tmp/secret_create.json")).get("ARN",""))')
    log "created ${name}  arn=${arn}"
  else
    if grep -q "ResourceExistsException" /tmp/secret_create.err 2>/dev/null; then
      aws secretsmanager put-secret-value \
        --secret-id "${name}" \
        --secret-string "${payload}" \
        --profile "${AWS_PROFILE}" \
        --region "${AWS_REGION}" \
        >/dev/null
      log "updated ${name}  (new version)"
    else
      cat /tmp/secret_create.err
      fail "aws secretsmanager call failed for ${name}"
    fi
  fi
}

# ---- preflight ------------------------------------------------------
require aws
require python3
[ -f "${ENV_FILE}" ] || log "warning: ${ENV_FILE} not found — only notifications.yml secrets will be pushed"

log "env=${AUDITLENS_ENV}  profile=${AWS_PROFILE}  region=${AWS_REGION}  dry_run=${DRY_RUN}"

# ---- groups (mirrors Phase 1 naming convention) ---------------------
PREFIX="auditlens/${AUDITLENS_ENV}"

# Confluent audit-source + destination clusters
confluent_payload=$(json_object \
  "audit_bootstrap=$(env_value AUDIT_BOOTSTRAP)" \
  "audit_api_key=$(env_value AUDIT_API_KEY)" \
  "audit_api_secret=$(env_value AUDIT_API_SECRET)" \
  "dest_bootstrap=$(env_value DEST_BOOTSTRAP)" \
  "dest_api_key=$(env_value DEST_API_KEY)" \
  "dest_api_secret=$(env_value DEST_API_SECRET)" \
  "cloud_api_key=$(env_value CONFLUENT_CLOUD_API_KEY)" \
  "cloud_api_secret=$(env_value CONFLUENT_CLOUD_API_SECRET)" \
  "api_key=$(env_value CONFLUENT_API_KEY)" \
  "api_secret=$(env_value CONFLUENT_API_SECRET)")
upsert_secret "${PREFIX}/confluent" "${confluent_payload}" "Confluent audit-source + destination + cloud API keys"

# Postgres password (consumed by docker compose + DATABASE_URL interpolation)
postgres_payload=$(json_object \
  "password=$(env_value POSTGRES_PASSWORD)")
upsert_secret "${PREFIX}/postgres" "${postgres_payload}" "AuditLens Postgres password"

# Schema Registry
sr_payload=$(json_object \
  "url=$(env_value SCHEMA_REGISTRY_URL)" \
  "api_key=$(env_value SCHEMA_REGISTRY_API_KEY)" \
  "api_secret=$(env_value SCHEMA_REGISTRY_API_SECRET)")
upsert_secret "${PREFIX}/sr" "${sr_payload}" "Confluent Schema Registry credentials"

# Notifications: best-effort grep for the three most common destination names.
# notifications.yml lives next to .env so it's read identically.
notifications_payload=$(json_object \
  "slack_webhook=$(notifications_webhook 'slack|Slack|primary|prod')" \
  "teams_webhook=$(notifications_webhook 'teams|Teams')" \
  "pagerduty_routing_key=$(env_value PAGERDUTY_ROUTING_KEY)" \
  "legacy_slack_webhook=$(env_value SLACK_WEBHOOK)")
upsert_secret "${PREFIX}/notifications" "${notifications_payload}" "Slack/Teams/PagerDuty webhook URLs"

# Tableflow API credentials (currently reuses CONFLUENT_CLOUD_API_*, so this is
# a forward-compat placeholder — left empty unless dedicated keys are set).
tableflow_payload=$(json_object \
  "api_key=$(env_value TABLEFLOW_API_KEY)" \
  "api_secret=$(env_value TABLEFLOW_API_SECRET)")
upsert_secret "${PREFIX}/tableflow" "${tableflow_payload}" "Tableflow-scoped API key (optional override)"

# Misc HIGH secrets that don't fit the above buckets: app_settings encryption,
# MCP token, Grafana admin password, AWS keys for cold storage.
misc_payload=$(json_object \
  "settings_encryption_key=$(env_value SETTINGS_ENCRYPTION_KEY)" \
  "mcp_auth_token=$(env_value MCP_AUTH_TOKEN)" \
  "grafana_admin_password=$(env_value GRAFANA_ADMIN_PASSWORD)" \
  "streamlit_password=$(env_value STREAMLIT_PASSWORD)" \
  "aws_access_key_id=$(env_value AWS_ACCESS_KEY_ID)" \
  "aws_secret_access_key=$(env_value AWS_SECRET_ACCESS_KEY)")
upsert_secret "${PREFIX}/misc" "${misc_payload}" "AuditLens misc HIGH-sensitivity secrets"

log "done."
