---
name: diary-analyzer
description: Analyze diary entries to extract patterns and propose rule updates
---

# Diary Analyzer

## Overview
Analyzes diary entries to identify patterns, extract learnings, and propose CLAUDE.md updates.

## Pattern Recognition

### Frequency Analysis
```
Pattern appears in N entries → Confidence level
- 1 entry: Low (observe)
- 2 entries: Medium (consider rule)
- 3+ entries: High (add rule)
```

### Pattern Types

#### 1. User Preferences
```markdown
Look for:
- "User prefers..."
- "User asked for..."
- "User corrected..."
- Direct quotes from feedback
```

#### 2. Effective Approaches
```markdown
Look for:
- "This worked well..."
- "Successful because..."
- "User approved..."
```

#### 3. Anti-Patterns
```markdown
Look for:
- "User rejected..."
- "Had to redo..."
- "Mistake was..."
- "Should have..."
```

#### 4. Domain Knowledge
```markdown
Look for:
- Technical constraints learned
- Business rules discovered
- Integration quirks found
```

## Rule Generation

### Format
Rules should be:
- One line
- Actionable
- Specific
- Testable

### Examples
```markdown
Bad: "Write good code"
Good: "Keep functions under 50 lines with single responsibility"

Bad: "Be helpful"
Good: "When user asks for help with X, first check if they have Y configured"

Bad: "Use TypeScript"
Good: "Define TypeScript interfaces before implementing functions"
```

## Reflection Template

```markdown
# Reflection: {{DATE}}

## Sources Analyzed
- Entry count: N
- Date range: X to Y
- Total patterns: N

## High-Confidence Rules (3+ occurrences)
1. [Rule text]
   - Evidence: [entry1], [entry2], [entry3]
   - Category: [preference|approach|anti-pattern|domain]

## Medium-Confidence Rules (2 occurrences)
1. [Rule text]
   - Evidence: [entry1], [entry2]

## Observations (1 occurrence)
- [Observation to watch for]

## Rule Strengthening
- [Existing rule] → [Stronger version]
  - Reason: [violation found in entry]

## Proposed CLAUDE.md Additions
```
[Ready-to-copy bullet points]
```
```

## Automation Levels

### Manual
User runs `/diary` after sessions, `/reflect` weekly

### Semi-Auto
- `/diary` prompted by PreCompact hook
- `/reflect` run manually

### Full Auto (Advanced)
- PostToolUse hook triggers micro-diary entries
- Weekly cron runs /reflect
- Auto-applies high-confidence rules
