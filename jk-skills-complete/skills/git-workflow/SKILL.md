---
name: git-workflow
description: "Git best practices including commit messages, branching, and PR workflows. Use when working with git."
allowed-tools: "Bash,Read,Write"
version: 1.0.0
---

# Git Workflow

## Commit Message Format
```
<type>(<scope>): <subject>

[optional body]

[optional footer]
```

Types: feat, fix, docs, style, refactor, test, chore

Example: `feat(auth): add OAuth2 login support`

## Branching Strategy
- main: Production-ready code
- feature/xxx: New features
- fix/xxx: Bug fixes
- hotfix/xxx: Urgent production fixes

## Daily Workflow
```bash
git fetch origin
git rebase origin/main
# Make changes
git add -p  # Stage interactively
git commit -m "feat: add feature"
git push origin feature/my-feature
```

## PR Checklist
- [ ] Tests pass
- [ ] No console.logs
- [ ] Types are correct
- [ ] Documentation updated

## Rescue Commands
```bash
# Undo last commit (keep changes)
git reset --soft HEAD~1

# Recover deleted branch
git reflog
git checkout -b branch-name HEAD@{n}

# Stash changes
git stash push -m "WIP: feature"
git stash pop
```
