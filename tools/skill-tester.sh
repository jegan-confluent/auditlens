#!/bin/bash
echo "🧪 Skill Tester"
[ -z "$1" ] && echo "Usage: ./tools/skill-tester.sh \"prompt\"" && exit 0
command -v jq &>/dev/null || { echo "Install jq"; exit 1; }
echo "Testing: \"$1\""
jq -r --arg p "$1" '.rules[] | select(.keywords | any(. as $k | $p | test($k;"i"))) | "  ✓ \(.skill)"' .claude/skill-rules.json
