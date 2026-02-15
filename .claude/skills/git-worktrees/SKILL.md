---
name: git-worktrees
description: Manage isolated git worktrees for parallel development
---
# Git Worktrees

## Overview
Creates isolated git worktrees for parallel development on multiple branches.

## Commands
```bash
# Create worktree
git worktree add ../feature-x feature-x

# List worktrees
git worktree list

# Remove worktree
git worktree remove ../feature-x
```

## Use Cases
- Work on multiple features simultaneously
- Test changes without stashing
- Review PRs while coding
- Parallel Claude Code sessions

## Structure
```
project/
├── main/           # Main worktree
├── feature-a/      # Feature A worktree
└── feature-b/      # Feature B worktree
```

## Best Practices
- ✅ Use descriptive directory names
- ✅ Clean up after merging
- ✅ Each worktree = separate terminal
