---
name: systematic-debugging
description: Structured approach to debugging any issue
---
# Systematic Debugging

## When to Use
Before proposing fixes for any bug, test failure, or unexpected behavior.

## Debug Process
1. **Reproduce:** Confirm the issue exists
2. **Isolate:** Find minimal reproduction
3. **Hypothesize:** List possible causes
4. **Test:** Verify each hypothesis
5. **Fix:** Apply targeted solution
6. **Verify:** Confirm fix works
7. **Prevent:** Add test/guard

## Debug Checklist
```markdown
- [ ] Can I reproduce consistently?
- [ ] What changed recently?
- [ ] What are the error messages?
- [ ] What do the logs show?
- [ ] Is it environment-specific?
```

## Common Patterns
| Symptom | Check First |
|---------|-------------|
| Works locally, fails CI | Environment variables, dependencies |
| Intermittent failure | Race conditions, timing |
| Worked yesterday | Recent commits, dependency updates |
| Only in production | Config differences, data scale |
