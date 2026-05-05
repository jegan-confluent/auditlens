#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

tmp_file="$(mktemp)"
trap 'rm -f "$tmp_file"' EXIT

grep -RInE \
  --exclude='.env.example' \
  --exclude='*.pyc' \
  --exclude='*.bundle' \
  --exclude='*.zip' \
  --exclude-dir='.git' \
  --exclude-dir='node_modules' \
  --exclude-dir='.next' \
  --exclude-dir='data' \
  --exclude-dir='backups' \
  --exclude-dir='__pycache__' \
  --exclude-dir='.pytest_cache' \
  --exclude-dir='.terraform' \
  '(BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY|cflt[A-Za-z0-9+/=]{20,}|api[_-]?key[[:space:]]*[:=][[:space:]]*["'\'']?[A-Z0-9]{12,}["'\'']?|api[_-]?secret[[:space:]]*[:=][[:space:]]*["'\'']?[A-Za-z0-9+/=]{20,}["'\'']?|password[[:space:]]*[:=][[:space:]]*["'\'']?[^[:space:]#"'\'']{16,}["'\'']?|token[[:space:]]*[:=][[:space:]]*["'\'']?[^[:space:]#"'\'']{24,}["'\'']?)' \
  . >"$tmp_file" || true

findings=0
while IFS= read -r line; do
  lower="$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')"
  case "$lower" in
    *'placeholder'*|*'replace_me'*|*'example'*|*'your-'*|*'${'*|*'var.'*|*'os.getenv'*|*'mask_secret'*|*'_extract_token'*|*'$audit_api_secret'*|*'test-'*|*'test_secret'*|*'test-secret'*|*'api_secret: ""'*|*'api_key: ""'*|*'password='|*'token=')
      continue
      ;;
  esac
  if [ "$findings" -eq 0 ]; then
    echo "Potential secret findings:"
  fi
  echo "$line"
  findings=$((findings + 1))
done <"$tmp_file"

if [ "$findings" -eq 0 ]; then
  echo "PASS: no high-confidence leaked secrets found"
  exit 0
fi

echo "FAIL: $findings potential secret finding(s)"
exit 1
