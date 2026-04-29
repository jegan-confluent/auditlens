#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TODAY_DATE="$(date +%F)"

last_session_number() {
  if [[ ! -f CHANGELOG.md ]]; then
    echo 0
    return 0
  fi

  awk '
    /^## \[[0-9]{4}-[0-9]{2}-[0-9]{2}\] Session [0-9]+/ {
      if (match($0, /Session [0-9]+/)) {
        value=substr($0, RSTART + 8, RLENGTH - 8)
        print value
        exit
      }
    }
  ' CHANGELOG.md
}

join_paths() {
  local lines="$1"
  if [[ -z "$lines" ]]; then
    echo "none"
    return 0
  fi
  printf '%s\n' "$lines" | awk 'NF {printf("%s%s", sep, $0); sep=", "} END {if (NR) printf("\n")}'
}

NEXT_SESSION_NUMBER="$(( $(last_session_number) + 1 ))"

NAME_STATUS="$(git diff --name-status HEAD 2>/dev/null || true)"
UNTRACKED_FILES="$(git ls-files --others --exclude-standard 2>/dev/null || true)"
DIFF_STAT="$(git diff --stat HEAD 2>/dev/null || true)"
RECENT_LOG="$(git log -5 --oneline 2>/dev/null || true)"

MODIFIED_FILES="$(printf '%s\n' "$NAME_STATUS" | awk '$1 ~ /^(M|R|C)$/ {print $NF}')"
ADDED_TRACKED_FILES="$(printf '%s\n' "$NAME_STATUS" | awk '$1 == "A" {print $NF}')"
DELETED_FILES="$(printf '%s\n' "$NAME_STATUS" | awk '$1 == "D" {print $NF}')"

ALL_ADDED_FILES="$(printf '%s\n%s\n' "$ADDED_TRACKED_FILES" "$UNTRACKED_FILES" | awk 'NF' | sort -u)"

FIXED_PATHS="$(join_paths "$MODIFIED_FILES")"
ADDED_PATHS="$(join_paths "$ALL_ADDED_FILES")"
REMOVED_PATHS="$(join_paths "$DELETED_FILES")"

ALL_NAME_ONLY="$(printf '%s\n%s\n' "$(git diff --name-only HEAD 2>/dev/null || true)" "$UNTRACKED_FILES" | awk 'NF' | sort -u)"

cat <<EOF
## [${TODAY_DATE}] Session [${NEXT_SESSION_NUMBER}]

### Fixed
- Summarize behavior fixes from modified files before append.
  Why: Preserve the operational impact of the session instead of only listing diffs.
  Files: ${FIXED_PATHS}

### Added
- Summarize new capabilities or workflow assets added this session.
  Why: Capture new repo-local behaviors and where they live.
  Files: ${ADDED_PATHS}

### Removed
- Summarize anything intentionally deleted this session.
  Why: Explain why the removal was safe.
  Files: ${REMOVED_PATHS}

### Architecture Decisions
- Record the session-level decisions that future work must preserve.
  Why: Keep future sessions aligned without rereading every diff.
  Impact: Affects coding direction, testing expectations, and product boundaries.

### Known Issues / Not Done
- Record unfinished work, validation still needed, or deferred cleanup.
  Why deferred: Capture what the next session should pick up first.

---
Draft context

git diff --stat HEAD:
${DIFF_STAT:-no diff}

git diff --name-only HEAD:
${ALL_NAME_ONLY:-no changed files}

recent git log:
${RECENT_LOG:-no git history}
EOF
