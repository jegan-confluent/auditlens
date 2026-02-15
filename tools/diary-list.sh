#!/bin/bash
echo "📔 Diary Entries"
echo "════════════════════════════════════════"
if [ -d ".claude/diary/entries" ]; then
    ls -la .claude/diary/entries/*.md 2>/dev/null | while read line; do
        echo "  $line"
    done
    echo ""
    echo "Total: $(ls .claude/diary/entries/*.md 2>/dev/null | wc -l) entries"
else
    echo "  No entries yet. Run /diary to create one."
fi
