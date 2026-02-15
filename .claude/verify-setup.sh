#!/bin/bash
echo "🔍 Verifying Claude Code Setup..."
echo ""
PASS=0; FAIL=0
check() { [ "$1" = "true" ] && echo -e "  \033[32m✓\033[0m $2" && ((PASS++)) || { echo -e "  \033[31m✗\033[0m $2"; ((FAIL++)); } }

echo "📁 Directories:"
check "$([ -d .claude ] && echo true)" ".claude/"
check "$([ -d .claude/hooks ] && echo true)" ".claude/hooks/"
check "$([ -d .claude/skills ] && echo true)" ".claude/skills/"
check "$([ -d .dev-docs ] && echo true)" ".dev-docs/"

echo ""
echo "📄 Config:"
check "$([ -f .claude/CLAUDE.md ] && echo true)" "CLAUDE.md"
check "$([ -f .claude/hooks.json ] && echo true)" "hooks.json"
check "$([ -f .claude/skill-rules.json ] && echo true)" "skill-rules.json"

echo ""
echo "🪝 Hooks (6):"
for h in cost-guard token-tracker skill-loader build-checker security-guard audit-logger; do
    check "$([ -f .claude/hooks/${h}.sh ] && [ -x .claude/hooks/${h}.sh ] && echo true)" "$h"
done

echo ""
echo "🎓 Skills (9):"
for s in typescript-patterns react-patterns testing-patterns api-patterns database-patterns supabase-patterns security-first deployment-patterns performance-patterns; do
    check "$([ -f .claude/skills/$s/SKILL.md ] && echo true)" "$s"
done

echo ""
echo "⚡ Commands (6):"
for c in deploy security-audit cost-report test document optimize; do
    check "$([ -f .claude/commands/$c.md ] && echo true)" "/$c"
done

echo ""
echo "════════════════════════════════════════"
echo "Results: $PASS passed, $FAIL failed"
[ $FAIL -eq 0 ] && echo -e "\033[32m✅ Setup complete!\033[0m" || echo -e "\033[31m⚠️ Issues found\033[0m"
