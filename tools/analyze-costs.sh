#!/bin/bash
echo "📊 Claude Code Cost Analysis"
echo "════════════════════════════"
TODAY=$(date +%Y-%m-%d)
if [ -f "logs/tokens-$TODAY.jsonl" ] && command -v jq &>/dev/null; then
    echo "Today:"
    cat "logs/tokens-$TODAY.jsonl" | jq -s '{requests: length, cost: (map(.cost) | add)}'
fi
echo ""
echo "This Week:"
cat logs/tokens-*.jsonl 2>/dev/null | jq -s 'group_by(.ts[:10]) | map({date: .[0].ts[:10], cost: (map(.cost)|add)}) | sort_by(.date) | reverse | .[:7]' 2>/dev/null || echo "No data"
