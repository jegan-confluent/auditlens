#!/bin/bash
command -v jq &>/dev/null || exit 0
FILE=$(echo "$HOOK_INPUT" | jq -r '.tool_input.path // ""' 2>/dev/null)
[[ ! "$FILE" =~ \.(ts|tsx|js|jsx)$ ]] && exit 0
if [ -f "package.json" ] && [ -f "tsconfig.json" ]; then
    if command -v npx &>/dev/null; then
        echo "🔨 Type checking..." >&2
        npx tsc --noEmit 2>&1 | tail -3 >&2 || echo "⚠️ TS errors" >&2
    fi
fi
exit 0
