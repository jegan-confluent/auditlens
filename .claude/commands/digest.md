---
name: digest
description: Generate weekly summary of work and learnings
---

# /digest - Weekly Work Summary

## Purpose
Generate a weekly summary of all sessions, learnings, and progress.

## Process

1. Read all diary entries from the past 7 days
2. Aggregate by category:
   - Features implemented
   - Bugs fixed
   - Decisions made
   - Learnings captured
3. Generate summary report

## Output Format

```markdown
# Weekly Digest: {{WEEK_START}} - {{WEEK_END}}

## Accomplishments
- [List of completed work]

## Key Decisions
- [Decision]: [Rationale]

## Learnings
- [What was learned]

## Challenges Overcome
- [Challenge]: [Solution]

## Next Week Focus
- [Based on patterns and unfinished items]

## Stats
- Sessions: N
- Files modified: N
- New rules added: N
```

Save to: `.claude/diary/archive/digest-{{WEEK}}.md`
