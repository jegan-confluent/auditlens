#!/bin/bash
#===============================================================================
#
#   CLAUDE DIARY ADDON v1.0
#   Self-Learning Memory System for Claude Code
#
#===============================================================================
#
# BASED ON: Lance Martin's Claude Diary (github.com/rlancemartin/claude-diary)
# RESEARCH: CoALA (Sumers 2023), Generative Agents (Park 2023), Zhang 2025
#
# WHAT THIS ADDS:
#   ├── /diary command - Capture session learnings
#   ├── /reflect command - Analyze patterns → update CLAUDE.md
#   ├── diary-writer hook - Auto-capture on PreCompact
#   ├── diary-analyzer skill - Pattern recognition
#   └── Diary storage system
#
# USAGE:
#   ./claude-code-addon-diary.sh
#
# REQUIRES: claude-code-master-setup.sh (base framework)
#
#===============================================================================

set -e

VERSION="1.0.0"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${PURPLE}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║     CLAUDE DIARY ADDON v${VERSION}                                ║"
echo "║     Self-Learning Memory System                               ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Pre-flight check
if [ ! -d ".claude" ]; then
    echo -e "${RED}ERROR: Base setup not found!${NC}"
    echo "Run claude-code-master-setup.sh first."
    exit 1
fi

echo -e "${CYAN}Based on: Lance Martin's Claude Diary${NC}"
echo -e "${CYAN}Research: CoALA, Generative Agents, Zhang 2025${NC}"
echo ""
echo -e "${YELLOW}This addon adds:${NC}"
echo "  • /diary command - Capture session learnings"
echo "  • /reflect command - Analyze patterns → update CLAUDE.md"
echo "  • diary-writer hook - Auto-capture on long sessions"
echo "  • diary-analyzer skill - Pattern recognition"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo
[[ ! $REPLY =~ ^[Yy]$ ]] && exit 1

#===============================================================================
# CREATE DIARY DIRECTORY STRUCTURE
#===============================================================================

echo ""
echo -e "${GREEN}━━━ Creating Diary Structure ━━━${NC}"

mkdir -p .claude/diary/{entries,reflections,archive}
mkdir -p .claude/diary/templates

echo -e "${GREEN}✓${NC} .claude/diary/{entries,reflections,archive,templates}"

#===============================================================================
# DIARY ENTRY TEMPLATE
#===============================================================================

cat > .claude/diary/templates/entry-template.md << 'EOF'
# Diary Entry: {{DATE}}

## Session Summary
<!-- What was accomplished this session? -->

## Key Decisions
<!-- Important decisions made and their rationale -->
- 

## Challenges Faced
<!-- Problems encountered and how they were resolved -->
- 

## Patterns Noticed
<!-- Recurring themes, user preferences, effective approaches -->
- 

## User Preferences Learned
<!-- Communication style, formatting, tool preferences -->
- 

## Code Patterns Used
<!-- Effective code patterns worth remembering -->
- 

## PR/Review Feedback
<!-- Feedback received that should inform future work -->
- 

## Rules to Consider
<!-- Potential CLAUDE.md rules based on this session -->
- 

## Questions for Next Session
<!-- Unresolved items or follow-ups needed -->
- 

---
Session Duration: {{DURATION}}
Files Modified: {{FILES}}
EOF

echo -e "${GREEN}✓${NC} entry-template.md"

#===============================================================================
# /DIARY COMMAND
#===============================================================================

echo ""
echo -e "${GREEN}━━━ Creating /diary Command ━━━${NC}"

cat > .claude/commands/diary.md << 'EOF'
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
EOF

echo -e "${GREEN}✓${NC} /diary command"

#===============================================================================
# /REFLECT COMMAND
#===============================================================================

echo ""
echo -e "${GREEN}━━━ Creating /reflect Command ━━━${NC}"

cat > .claude/commands/reflect.md << 'EOF'
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
EOF

echo -e "${GREEN}✓${NC} /reflect command"

#===============================================================================
# /DIGEST COMMAND (Weekly Summary)
#===============================================================================

cat > .claude/commands/digest.md << 'EOF'
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
EOF

echo -e "${GREEN}✓${NC} /digest command"

#===============================================================================
# DIARY-WRITER HOOK (PreCompact Auto-Capture)
#===============================================================================

echo ""
echo -e "${GREEN}━━━ Creating diary-writer Hook ━━━${NC}"

cat > .claude/hooks/diary-writer.sh << 'EOF'
#!/bin/bash
#===============================================================================
# DIARY WRITER - Auto-captures session learnings on PreCompact
# Triggers when context window is about to compact (long sessions)
#===============================================================================

DIARY_DIR=".claude/diary/entries"
mkdir -p "$DIARY_DIR"

TODAY=$(date +%Y-%m-%d)
TIME=$(date +%H%M)
ENTRY_FILE="$DIARY_DIR/${TODAY}-session-${TIME}.md"

# Only run on PreCompact (long sessions worth capturing)
HOOK_TYPE="${HOOK_TYPE:-}"
if [ "$HOOK_TYPE" != "PreCompact" ]; then
    exit 0
fi

# Check if we already have an entry for this session
if ls "$DIARY_DIR"/${TODAY}-session-*.md 1>/dev/null 2>&1; then
    # Already have entry today, skip
    exit 0
fi

# Signal to Claude that diary should be written
echo "" >&2
echo "📔 Long session detected - consider running /diary to capture learnings" >&2
echo "─────────────────────────────────────────────────────────────────────" >&2

exit 0
EOF

chmod +x .claude/hooks/diary-writer.sh
echo -e "${GREEN}✓${NC} diary-writer.sh"

#===============================================================================
# UPDATE HOOKS.JSON
#===============================================================================

echo ""
echo -e "${GREEN}━━━ Updating hooks.json ━━━${NC}"

if [ -f ".claude/hooks.json" ] && command -v jq &>/dev/null; then
    # Check if PreCompact hook section exists
    if jq -e '.hooks.PreCompact' .claude/hooks.json >/dev/null 2>&1; then
        # Add to existing PreCompact
        jq '.hooks.PreCompact += [{"hooks": [{"type": "command", "command": ".claude/hooks/diary-writer.sh"}]}]' \
            .claude/hooks.json > .claude/hooks.json.tmp && mv .claude/hooks.json.tmp .claude/hooks.json
    else
        # Create PreCompact section
        jq '.hooks.PreCompact = [{"hooks": [{"type": "command", "command": ".claude/hooks/diary-writer.sh"}]}]' \
            .claude/hooks.json > .claude/hooks.json.tmp && mv .claude/hooks.json.tmp .claude/hooks.json
    fi
    echo -e "${GREEN}✓${NC} Added PreCompact hook"
else
    echo -e "${YELLOW}⚠${NC} hooks.json not found or jq not installed - add manually"
fi

#===============================================================================
# DIARY-ANALYZER SKILL
#===============================================================================

echo ""
echo -e "${GREEN}━━━ Creating diary-analyzer Skill ━━━${NC}"

mkdir -p .claude/skills/diary-analyzer
cat > .claude/skills/diary-analyzer/SKILL.md << 'EOF'
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
EOF

echo -e "${GREEN}✓${NC} diary-analyzer skill"

#===============================================================================
# MEMORY CONSOLIDATION SKILL
#===============================================================================

mkdir -p .claude/skills/memory-consolidation
cat > .claude/skills/memory-consolidation/SKILL.md << 'EOF'
---
name: memory-consolidation
description: Theory and patterns for agent memory systems
---

# Memory Consolidation

## Research Background

### CoALA Framework (Sumers 2023)
Agent memory types:
- **Procedural Memory:** Instructions (CLAUDE.md)
- **Episodic Memory:** Past actions (diary entries)
- **Semantic Memory:** Facts and relationships

### Generative Agents (Park 2023)
Key insight: Agents should reflect on past actions to synthesize general rules.

```
Raw Experience → Reflection → General Rules → Better Decisions
```

### Zhang 2025 "Grow and Refine"
Three-component system:
1. **Generator:** Produces reasoning trajectories
2. **Reflector:** Extracts lessons from successes/failures
3. **Curator:** Integrates lessons into instructions

## Memory Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Session   │ ──▶ │   /diary    │ ──▶ │   Entry     │
│   Actions   │     │   Command   │     │   .md file  │
└─────────────┘     └─────────────┘     └─────────────┘
                                               │
                                               ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  CLAUDE.md  │ ◀── │  /reflect   │ ◀── │  Multiple   │
│   Updated   │     │   Command   │     │   Entries   │
└─────────────┘     └─────────────┘     └─────────────┘
```

## Best Practices

### Diary Entries
- Write immediately after significant sessions
- Be specific about what worked/didn't
- Include direct quotes when relevant
- Note the "why" behind decisions

### Reflection
- Run weekly minimum
- Look for 3+ occurrence patterns
- Strengthen violated rules
- Remove counterproductive rules

### Rule Quality
- Specific > General
- Actionable > Descriptive
- One rule per behavior
- Include context when needed

## Anti-Patterns

❌ **Vague rules:** "Be better at coding"
❌ **Too many rules:** More than ~20 active rules
❌ **Conflicting rules:** Rules that contradict each other
❌ **Stale rules:** Rules from outdated contexts
❌ **Over-automation:** Auto-applying without review
EOF

echo -e "${GREEN}✓${NC} memory-consolidation skill"

#===============================================================================
# UPDATE SKILL RULES
#===============================================================================

echo ""
echo -e "${GREEN}━━━ Updating Skill Rules ━━━${NC}"

if [ -f ".claude/skill-rules.json" ] && command -v jq &>/dev/null; then
    jq '.rules += [
        {"skill": "diary-analyzer", "keywords": ["diary", "reflect", "memory", "learnings", "patterns", "rules"]},
        {"skill": "memory-consolidation", "keywords": ["memory", "consolidation", "episodic", "procedural", "CoALA"]}
    ]' .claude/skill-rules.json > .claude/skill-rules.json.tmp && mv .claude/skill-rules.json.tmp .claude/skill-rules.json
    echo -e "${GREEN}✓${NC} Added skill rules"
fi

#===============================================================================
# HELPER SCRIPTS
#===============================================================================

echo ""
echo -e "${GREEN}━━━ Creating Helper Scripts ━━━${NC}"

# Ensure tools directory exists
mkdir -p tools

# List diary entries
cat > tools/diary-list.sh << 'EOF'
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
EOF
chmod +x tools/diary-list.sh
echo -e "${GREEN}✓${NC} diary-list.sh"

# View recent entries
cat > tools/diary-recent.sh << 'EOF'
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
EOF
chmod +x tools/diary-recent.sh
echo -e "${GREEN}✓${NC} diary-recent.sh"

# Count patterns
cat > tools/diary-patterns.sh << 'EOF'
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
EOF
chmod +x tools/diary-patterns.sh
echo -e "${GREEN}✓${NC} diary-patterns.sh"

#===============================================================================
# UPDATE CLAUDE.md
#===============================================================================

echo ""
echo -e "${GREEN}━━━ Updating CLAUDE.md ━━━${NC}"

if [ -f ".claude/CLAUDE.md" ]; then
    cat >> .claude/CLAUDE.md << 'EOF'

---

## Claude Diary System

### Memory Commands
- `/diary` - Capture session learnings after significant work
- `/reflect` - Analyze diary entries, propose CLAUDE.md updates
- `/digest` - Generate weekly work summary

### Memory Flow
```
Session → /diary → Entry → /reflect → CLAUDE.md Update
```

### Diary Location
- Entries: `.claude/diary/entries/`
- Reflections: `.claude/diary/reflections/`
- Archive: `.claude/diary/archive/`

### When to Use /diary
- After implementing significant features
- After solving complex bugs
- After receiving user feedback
- When PreCompact triggers (long sessions)

### When to Use /reflect
- Weekly (recommended)
- After 5+ diary entries accumulate
- Before starting new project phase
EOF
    echo -e "${GREEN}✓${NC} Updated CLAUDE.md"
fi

#===============================================================================
# SUMMARY
#===============================================================================

echo ""
echo -e "${PURPLE}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${PURPLE}║     ✅ CLAUDE DIARY ADDON COMPLETE!                           ║${NC}"
echo -e "${PURPLE}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}📊 Added:${NC}"
echo ""
echo "  Commands (3):"
echo "    /diary    - Capture session learnings"
echo "    /reflect  - Analyze patterns → update CLAUDE.md"
echo "    /digest   - Weekly work summary"
echo ""
echo "  Hooks (1):"
echo "    diary-writer.sh - Auto-prompt on long sessions"
echo ""
echo "  Skills (2):"
echo "    diary-analyzer       - Pattern recognition"
echo "    memory-consolidation - Memory theory"
echo ""
echo "  Tools (3):"
echo "    diary-list.sh     - List all entries"
echo "    diary-recent.sh   - View recent entries"
echo "    diary-patterns.sh - Analyze common patterns"
echo ""
echo -e "${YELLOW}📁 Diary Storage:${NC}"
echo "    .claude/diary/entries/      - Session entries"
echo "    .claude/diary/reflections/  - Analysis results"
echo "    .claude/diary/archive/      - Weekly digests"
echo ""
echo -e "${GREEN}🚀 Usage:${NC}"
echo "    1. After significant work: /diary"
echo "    2. Weekly: /reflect"
echo "    3. Check entries: ./tools/diary-list.sh"
echo ""
echo -e "${CYAN}📚 Based on:${NC}"
echo "    • Lance Martin's Claude Diary"
echo "    • CoALA Framework (Sumers 2023)"
echo "    • Generative Agents (Park 2023)"
echo "    • Zhang 2025 'Grow and Refine'"
echo ""
