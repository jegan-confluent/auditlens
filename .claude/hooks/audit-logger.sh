#!/bin/bash
mkdir -p logs
AUDIT="logs/audit-$(date +%Y-%m).jsonl"
command -v jq &>/dev/null || exit 0
TOOL=$(echo "$HOOK_INPUT" | jq -r '.tool_name // "unknown"' 2>/dev/null)
[[ "$TOOL" == "View" ]] || [[ "$TOOL" == "Read" ]] && exit 0
FILE=$(echo "$HOOK_INPUT" | jq -r '.tool_input.path // "N/A"' 2>/dev/null)
echo "{\"ts\":\"$(date -Iseconds)\",\"tool\":\"$TOOL\",\"file\":\"$FILE\"}" >> "$AUDIT"
exit 0
