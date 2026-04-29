#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PROJECT_NAME="$(basename "$ROOT_DIR")"
TODAY_DATE="$(date +%F)"
BRANCH_NAME="$(git branch --show-current 2>/dev/null || true)"
if [[ -z "$BRANCH_NAME" ]]; then
  BRANCH_NAME="detached-or-unknown"
fi

extract_last_session_entry() {
  if [[ ! -f CHANGELOG.md ]]; then
    return 0
  fi

  awk '
    /^## \[[0-9]{4}-[0-9]{2}-[0-9]{2}\] Session [0-9]+/ {
      if (capturing) exit
      capturing=1
    }
    capturing { print }
  ' CHANGELOG.md
}

extract_first_bullet() {
  local section_name="$1"
  local entry_text="$2"

  printf '%s\n' "$entry_text" | awk -v section="### ${section_name}" '
    $0 == section { in_section=1; next }
    /^### / && in_section { exit }
    in_section && /^- / {
      sub(/^- /, "", $0)
      print
      exit
    }
  '
}

extract_heading_value() {
  local entry_text="$1"
  printf '%s\n' "$entry_text" | awk '
    /^## \[[0-9]{4}-[0-9]{2}-[0-9]{2}\] Session [0-9]+/ {
      print
      exit
    }
  '
}

LAST_SESSION_ENTRY="$(extract_last_session_entry || true)"
LAST_SESSION_HEADING="$(extract_heading_value "$LAST_SESSION_ENTRY")"

LAST_SESSION_DATE="none"
LAST_SESSION_NUMBER="none"
if [[ -n "$LAST_SESSION_HEADING" ]]; then
  LAST_SESSION_DATE="$(printf '%s\n' "$LAST_SESSION_HEADING" | sed -E 's/^## \[([0-9-]+)\] Session [0-9]+$/\1/')"
  LAST_SESSION_NUMBER="$(printf '%s\n' "$LAST_SESSION_HEADING" | sed -E 's/^## \[[0-9-]+\] Session ([0-9]+)$/\1/')"
fi

LAST_FIXED="$(extract_first_bullet "Fixed" "$LAST_SESSION_ENTRY")"
LAST_ADDED="$(extract_first_bullet "Added" "$LAST_SESSION_ENTRY")"
CARRIED_FORWARD="$(extract_first_bullet "Known Issues / Not Done" "$LAST_SESSION_ENTRY")"

if [[ -z "$LAST_FIXED" ]]; then
  LAST_FIXED="none recorded"
fi
if [[ -z "$LAST_ADDED" ]]; then
  LAST_ADDED="none recorded"
fi
if [[ -z "$CARRIED_FORWARD" ]]; then
  CARRIED_FORWARD="none recorded"
fi

GIT_STATUS="$(git status --short || true)"
if [[ -z "$GIT_STATUS" ]]; then
  GIT_STATUS_SUMMARY="clean working tree"
else
  GIT_STATUS_SUMMARY="dirty working tree"
fi

RECENT_LOG="$(git log -5 --oneline 2>/dev/null || true)"
if [[ -z "$RECENT_LOG" ]]; then
  RECENT_LOG="no git history available"
fi

BUILD_TEST_STATUS="not checked"
if command -v python3 >/dev/null 2>&1 && [[ -f audit_forwarder.py ]]; then
  CHECK_FILES=()
  [[ -f audit_forwarder.py ]] && CHECK_FILES+=("audit_forwarder.py")
  [[ -f src/product/auth.py ]] && CHECK_FILES+=("src/product/auth.py")
  [[ -f src/product/persistence.py ]] && CHECK_FILES+=("src/product/persistence.py")
  if [[ "${#CHECK_FILES[@]}" -gt 0 ]]; then
    if python3 -m py_compile "${CHECK_FILES[@]}" >/dev/null 2>&1; then
      BUILD_TEST_STATUS="python compile check passed"
    else
      BUILD_TEST_STATUS="python compile check failed"
    fi
  fi
fi

cat <<EOF
## Session Start - ${PROJECT_NAME} - ${TODAY_DATE}
Last session: Session ${LAST_SESSION_NUMBER} on ${LAST_SESSION_DATE}
Last fixed: ${LAST_FIXED}
Last added: ${LAST_ADDED}
Carried forward: ${CARRIED_FORWARD}
Build/test status: ${BUILD_TEST_STATUS}
Current branch: ${BRANCH_NAME}
Repo state: ${GIT_STATUS_SUMMARY}

Recent git log:
${RECENT_LOG}

Current git status:
${GIT_STATUS:-clean}

Stop here and ask the user what to work on next before editing.
EOF
