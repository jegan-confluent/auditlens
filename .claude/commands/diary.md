---
name: diary
description: Capture learnings from the current session for future reference
---

# /diary - Session Learning Capture

## Purpose
Transform this session's actions and decisions into persistent memory that improves future sessions.

## What to Capture

Analyze our conversation and extract:

### 1. Session Summary
What did we accomplish? List the main outcomes.

### 2. Key Decisions
What important decisions were made? Include:
- The decision itself
- Why it was made (rationale)
- Alternatives considered

### 3. Challenges & Solutions
What problems came up? How were they solved?
- Problem description
- Solution approach
- What worked / didn't work

### 4. Patterns Noticed
What recurring themes or approaches emerged?
- Effective strategies
- User's preferred approaches
- Domain-specific patterns

### 5. User Preferences Learned
What did I learn about how this user likes to work?
- Communication style (concise vs detailed)
- Code style preferences
- Tool preferences
- Formatting preferences

### 6. Code Patterns Worth Remembering
Any code patterns that were particularly effective?
- Reusable snippets
- Architecture decisions
- Testing approaches

### 7. Feedback Received
Any corrections, preferences expressed, or guidance given?
- What was wrong
- What was preferred
- How to do it better

### 8. Potential CLAUDE.md Rules
Based on this session, what rules should be added to CLAUDE.md?
Format as one-line bullets that can be directly added.

## Output Format

Save the diary entry to: `.claude/diary/entries/{{DATE}}-{{SLUG}}.md`

Where:
- DATE = YYYY-MM-DD
- SLUG = 2-3 word description (e.g., "auth-refactor", "api-testing")

## Example Entry

```markdown
# Diary Entry: 2025-12-07

## Session Summary
Implemented user authentication with Supabase, including email verification and password reset flows.

## Key Decisions
- Used Supabase Auth instead of custom JWT (faster, more secure)
- Chose email verification over phone (cost, user preference)

## Challenges & Solutions
- **Problem:** Token refresh race condition
- **Solution:** Added mutex lock pattern from supabase-patterns skill

## Patterns Noticed
- User prefers seeing the full implementation before refactoring
- User values explicit error messages over generic ones

## User Preferences Learned
- Prefers concise responses without excessive explanation
- Likes seeing TypeScript types defined first
- Wants tests written alongside implementation

## Code Patterns Worth Remembering
- Supabase auth hook with automatic token refresh
- Zod schema validation before database operations

## Feedback Received
- "Don't add console.log statements" - use proper logging
- "Keep components under 200 lines"

## Potential CLAUDE.md Rules
- Always use structured logging, never console.log
- Keep React components under 200 lines
- Define TypeScript types before implementation
- Write tests alongside new features, not after
```

## After Running /diary

The entry is saved. Run `/reflect` periodically to analyze entries and update CLAUDE.md.
