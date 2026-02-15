---
name: code-review
description: "Code review guidelines and checklist. Use when reviewing PRs or preparing code for review."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Code Review

## Review Checklist
- [ ] Code works as intended
- [ ] No security vulnerabilities
- [ ] Error handling is appropriate
- [ ] Tests cover new functionality
- [ ] No hardcoded values
- [ ] Performance is acceptable
- [ ] Code is readable

## What to Look For
### Logic
- Edge cases handled?
- Race conditions?
- Null/undefined checks?

### Security
- Input validated?
- SQL injection safe?
- Secrets exposed?

### Performance
- N+1 queries?
- Unnecessary re-renders?
- Memory leaks?

## Giving Feedback
```markdown
# Good
"Consider using `useMemo` here to avoid recalculating on every render"

# Avoid
"This is wrong"
```

## Prefixes
- `nit:` - Minor suggestion
- `question:` - Need clarification
- `suggestion:` - Optional improvement
- `issue:` - Must fix before merge
