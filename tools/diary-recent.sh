#!/bin/bash
echo "📔 Recent Diary Entries"
echo "════════════════════════════════════════"
if [ -d ".claude/diary/entries" ]; then
    for f in $(ls -t .claude/diary/entries/*.md 2>/dev/null | head -3); do
        echo ""
        echo "── $(basename $f) ──"
        head -30 "$f"
        echo "..."
    done
else
    echo "  No entries yet."
fi
