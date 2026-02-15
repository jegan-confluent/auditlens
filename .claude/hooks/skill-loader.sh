#!/bin/bash
command -v jq &>/dev/null || exit 0
MSG=$(echo "$HOOK_INPUT" | jq -r '.message // .content // ""' 2>/dev/null | head -c 500)
[ -z "$MSG" ] && exit 0
[ ! -f ".claude/skill-rules.json" ] && exit 0
SKILLS=$(jq -r --arg m "$MSG" '.rules[] | select(.keywords | any(. as $k | $m | test($k; "i"))) | .skill' .claude/skill-rules.json 2>/dev/null | head -3)
if [ -n "$SKILLS" ]; then
    echo "" >&2
    echo "🎯 Auto-loading: $SKILLS" >&2
    for s in $SKILLS; do
        [ -f ".claude/skills/$s/SKILL.md" ] && head -80 ".claude/skills/$s/SKILL.md"
    done
fi
exit 0
