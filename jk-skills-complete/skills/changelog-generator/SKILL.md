---
name: changelog-generator
description: "Automatically create user-facing changelogs from git commits. Use when preparing releases, documenting changes, or generating release notes."
allowed-tools: "Bash(git:*),Read,Write"
version: 1.0.0
---

# Changelog Generator

Transform git commits into professional, user-friendly changelogs.

## When to Use This Skill

- Preparing a release
- User says "generate changelog"
- Need release notes
- Documenting version changes

## Process

### Step 1: Gather Commits
```bash
# Get commits since last tag
git log $(git describe --tags --abbrev=0)..HEAD --oneline

# Or between versions
git log v1.0.0..v1.1.0 --oneline

# With full messages
git log --pretty=format:"%h %s" v1.0.0..HEAD
```

### Step 2: Categorize by Type
Parse commit prefixes into sections:

| Prefix | Section |
|--------|---------|
| feat: | ✨ New Features |
| fix: | 🐛 Bug Fixes |
| perf: | ⚡ Performance |
| docs: | 📚 Documentation |
| refactor: | ♻️ Refactoring |
| test: | 🧪 Tests |
| chore: | 🔧 Maintenance |
| BREAKING: | ⚠️ Breaking Changes |

### Step 3: Transform to User Language
Convert technical commits to user-friendly descriptions:

```
# Technical commit
fix(auth): handle null user in getProfile middleware

# User-friendly
- Fixed an issue where profile pages could crash for logged-out users
```

### Step 4: Generate Changelog

## Output Format

```markdown
# Changelog

## [1.2.0] - 2025-01-15

### ✨ New Features
- Added dark mode support (#123)
- Users can now export data as CSV (#145)

### 🐛 Bug Fixes
- Fixed login redirect loop (#156)
- Resolved cart calculation errors (#158)

### ⚡ Performance
- Reduced page load time by 40%
- Optimized database queries

### ⚠️ Breaking Changes
- Removed deprecated `legacyAuth` option
- Changed API response format for `/users` endpoint

---

## [1.1.0] - 2024-12-01
[Previous release notes...]
```

## Changelog Entry Templates

### Feature
```markdown
- **[Feature Name]**: Brief description of what users can now do. (#PR)
```

### Bug Fix
```markdown
- Fixed issue where [problem description]. (#PR)
```

### Breaking Change
```markdown
- **BREAKING**: [Change description]. Migration: [steps to update].
```

## Automation Script

```bash
#!/bin/bash
# generate-changelog.sh

VERSION=$1
PREV_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
DATE=$(date +%Y-%m-%d)

echo "## [$VERSION] - $DATE"
echo ""

# Features
echo "### ✨ New Features"
git log $PREV_TAG..HEAD --oneline | grep "^[a-f0-9]* feat" | while read line; do
  echo "- ${line#* feat*: }"
done
echo ""

# Fixes
echo "### 🐛 Bug Fixes"
git log $PREV_TAG..HEAD --oneline | grep "^[a-f0-9]* fix" | while read line; do
  echo "- ${line#* fix*: }"
done
```

## Best Practices

- Write for end users, not developers
- Group related changes
- Highlight breaking changes prominently
- Include migration instructions
- Link to PRs/issues
- Keep entries concise but informative
