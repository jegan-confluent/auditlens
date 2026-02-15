#!/bin/bash
command -v jq &>/dev/null || exit 0
CONTENT=$(echo "$HOOK_INPUT" | jq -r '.tool_input.content // .tool_input.file_text // .tool_input.new_str // ""' 2>/dev/null)
[ -z "$CONTENT" ] && exit 0
VIOLATIONS=()
echo "$CONTENT" | grep -iE '(password|api[_-]?key|secret)\s*[:=]\s*["\047][^"\047]{8,}' >/dev/null && VIOLATIONS+=("Hardcoded credential")
echo "$CONTENT" | grep -E 'AKIA[0-9A-Z]{16}' >/dev/null && VIOLATIONS+=("AWS key")
echo "$CONTENT" | grep -E '-----BEGIN.*PRIVATE KEY-----' >/dev/null && VIOLATIONS+=("Private key")
if [ ${#VIOLATIONS[@]} -gt 0 ]; then
    echo "🔒 SECURITY: ${VIOLATIONS[*]}" >&2
    exit 1
fi
exit 0
