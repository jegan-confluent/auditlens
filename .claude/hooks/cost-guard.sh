#!/bin/bash
BUDGET=${CLAUDE_DAILY_BUDGET:-50.00}
TODAY=$(date +%Y-%m-%d)
LOG_FILE="logs/tokens-$TODAY.jsonl"
mkdir -p logs
if [ -f "$LOG_FILE" ] && command -v jq &>/dev/null && command -v bc &>/dev/null; then
    TODAY_COST=$(jq -s 'map(.cost // 0) | add // 0' "$LOG_FILE" 2>/dev/null || echo "0")
    if (( $(echo "$TODAY_COST > $BUDGET" | bc -l 2>/dev/null || echo "0") )); then
        echo "🚨 Budget exceeded: \$$TODAY_COST / \$$BUDGET" >&2
        exit 2
    fi
    WARN=$(echo "$BUDGET * 0.8" | bc -l)
    (( $(echo "$TODAY_COST > $WARN" | bc -l 2>/dev/null || echo "0") )) && echo "⚠️ Budget: \$$TODAY_COST / \$$BUDGET" >&2
fi
exit 0
