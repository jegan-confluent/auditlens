---
name: reflect
description: Analyze diary entries and propose CLAUDE.md updates
---

# /reflect - Memory Consolidation

## Purpose
Analyze diary entries to identify patterns and propose updates to CLAUDE.md.

## Process

### Step 1: Read Current State
1. Read `.claude/CLAUDE.md` (current rules)
2. Read all entries in `.claude/diary/entries/`
3. Read previous reflections in `.claude/diary/reflections/`

### Step 2: Analyze Patterns

Look for:

#### A. Rule Violations
Are there diary entries showing the same mistake repeated?
- If a rule exists but was violated → Strengthen the rule
- If no rule exists → Propose new rule

#### B. Recurring Patterns (3+ occurrences)
What appears across multiple diary entries?
- User preferences mentioned multiple times
- Effective approaches used repeatedly
- Common challenges with common solutions

#### C. Feedback Patterns
What corrections or preferences were expressed?
- Direct feedback ("don't do X")
- Implicit feedback (user rewrote something)
- Positive feedback (user praised approach)

#### D. Successful Strategies
What approaches consistently worked well?
- Code patterns that succeeded
- Communication styles that worked
- Problem-solving approaches

### Step 3: Generate Proposals

For each pattern found, create a proposed CLAUDE.md update:

```markdown
## Proposed CLAUDE.md Updates

### New Rules (High Confidence)
<!-- Patterns with 3+ supporting entries -->
- [RULE]: [One-line rule text]
  - Evidence: [Entry 1], [Entry 2], [Entry 3]

### New Rules (Medium Confidence)
<!-- Patterns with 2 supporting entries -->
- [RULE]: [One-line rule text]
  - Evidence: [Entry 1], [Entry 2]

### Strengthen Existing Rules
<!-- Rules that were violated -->
- [EXISTING RULE] → [STRENGTHENED VERSION]
  - Violation in: [Entry]

### Remove/Weaken Rules
<!-- Rules that seem counterproductive -->
- [RULE]: Consider removing because [reason]
```

### Step 4: Save Reflection

Save to: `.claude/diary/reflections/{{DATE}}-reflection.md`

### Step 5: Present to User

Show the proposals and ask:
1. Which rules should be added to CLAUDE.md?
2. Which rules should be strengthened?
3. Any rules to remove?

## Example Reflection Output

```markdown
# Reflection: 2025-12-07

## Analyzed
- 5 diary entries from past 2 weeks
- 12 patterns identified
- 3 rule violations found

## Proposed CLAUDE.md Updates

### New Rules (High Confidence)

1. **Always define TypeScript interfaces before implementation**
   - Evidence: 2025-12-01-auth, 2025-12-03-api, 2025-12-05-forms
   - User consistently asked for types first

2. **Use Zod for all API input validation**
   - Evidence: 2025-12-02-validation, 2025-12-04-endpoints, 2025-12-06-forms
   - Pattern: Every endpoint needed validation added

3. **Keep React components under 200 lines**
   - Evidence: 2025-12-01-auth, 2025-12-05-forms, 2025-12-07-dashboard
   - Direct feedback in 2 entries

### Strengthen Existing Rules

1. "Use structured logging" → "Use structured logging with pino. Never use console.log even for debugging."
   - Violation in: 2025-12-03-api (added console.log, user removed it)

### Observations

- User prefers concise responses (mentioned in 4/5 entries)
- User likes seeing tests alongside implementation
- Morning sessions tend to focus on new features
- Afternoon sessions tend to focus on bugs/refactoring
```

## Automation

This command can be:
1. Run manually: `/reflect`
2. Run weekly via cron/scheduled task
3. Triggered after N diary entries accumulate
