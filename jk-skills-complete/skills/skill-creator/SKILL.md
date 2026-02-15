---
name: skill-creator
description: "Guide for creating effective Claude skills. Use when user wants to create a new skill, update an existing skill, or extend Claude's capabilities with specialized knowledge, workflows, or tool integrations."
allowed-tools: "Read,Write,Bash,Glob,Grep"
version: 1.0.0
---

# Skill Creator

Create well-structured, reusable Claude skills that extend capabilities with specialized knowledge and workflows.

## When to Use This Skill

- User says "create a skill for..."
- User wants to package expertise into reusable format
- User needs to automate a specific workflow
- User says "make Claude better at..."

## Skill Structure

Every skill is a folder containing:

```
my-skill/
├── SKILL.md          # Required: Instructions and metadata
├── scripts/          # Optional: Python/Bash automation
├── references/       # Optional: Documentation to load
└── assets/           # Optional: Templates, images
```

## SKILL.md Template

```yaml
---
name: my-skill-name
description: "Clear description of what this skill does and when to use it. Include trigger phrases."
allowed-tools: "Read,Write,Bash"   # Only what's needed
version: 1.0.0
---

# Skill Title

## When to Use This Skill
- Trigger condition 1
- Trigger condition 2
- Trigger condition 3

## Prerequisites
- Required tools or files
- Environment setup

## Instructions

### Step 1: [First Action]
[Imperative instructions - "Analyze the...", not "You should..."]

### Step 2: [Next Action]
[Clear, actionable steps]

### Step 3: [Final Action]
[Completion criteria]

## Output Format
[How to structure results]

## Examples
[Concrete usage examples]

## Error Handling
[What to do when things fail]
```

## Best Practices

### DO:
- Keep SKILL.md under 5,000 words
- Use imperative language ("Analyze...", "Create...")
- Include concrete examples
- Reference external files with `{baseDir}/path`
- Define clear trigger phrases in description
- Specify minimum required tools

### DON'T:
- Use second person ("You should...")
- Hardcode absolute paths
- Include sensitive data
- List all available tools
- Make prompts too verbose

## Progressive Disclosure Pattern

1. **Frontmatter** → Minimal metadata (name, description)
2. **SKILL.md loaded** → Full instructions when skill activates
3. **References loaded** → Detailed docs only when needed

## Skill Installation

Skills go in `~/.claude/skills/` for global or `.claude/skills/` for project-specific.

```bash
# Install skill
cp -r my-skill ~/.claude/skills/

# Verify
ls ~/.claude/skills/my-skill/SKILL.md
```

## Testing Your Skill

1. Install in test project
2. Start Claude Code
3. Use trigger phrases from description
4. Verify skill activates correctly
5. Check workflow produces expected output
