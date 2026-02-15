#!/bin/bash
#===============================================================================
# DIARY WRITER - Auto-captures session learnings on PreCompact
# Triggers when context window is about to compact (long sessions)
#===============================================================================

DIARY_DIR=".claude/diary/entries"
mkdir -p "$DIARY_DIR"

TODAY=$(date +%Y-%m-%d)
TIME=$(date +%H%M)
ENTRY_FILE="$DIARY_DIR/${TODAY}-session-${TIME}.md"

# Only run on PreCompact (long sessions worth capturing)
HOOK_TYPE="${HOOK_TYPE:-}"
if [ "$HOOK_TYPE" != "PreCompact" ]; then
    exit 0
fi

# Check if we already have an entry for this session
if ls "$DIARY_DIR"/${TODAY}-session-*.md 1>/dev/null 2>&1; then
    # Already have entry today, skip
    exit 0
fi

# Signal to Claude that diary should be written
echo "" >&2
echo "📔 Long session detected - consider running /diary to capture learnings" >&2
echo "─────────────────────────────────────────────────────────────────────" >&2

exit 0
