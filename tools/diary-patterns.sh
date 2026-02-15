#!/bin/bash
echo "📊 Pattern Analysis"
echo "════════════════════════════════════════"
if [ -d ".claude/diary/entries" ]; then
    echo ""
    echo "Most common words in entries:"
    cat .claude/diary/entries/*.md 2>/dev/null | \
        tr '[:upper:]' '[:lower:]' | \
        tr -cs '[:alpha:]' '\n' | \
        grep -v -E '^(the|a|an|is|are|was|were|be|been|being|to|of|and|in|that|it|for|on|with|as|at|by|from|or|this|which|but|not|have|has|had|do|does|did|will|would|could|should|may|might|must|can)$' | \
        sort | uniq -c | sort -rn | head -20
else
    echo "  No entries to analyze."
fi
