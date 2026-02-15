---
name: root-cause-tracing
description: "Trace errors deep in execution back to find the original trigger. Use when errors occur and you need to find the actual source, not just symptoms."
allowed-tools: "Read,Bash,Grep,Glob"
version: 1.0.0
---

# Root Cause Tracing

Systematically trace errors back to their original source.

## When to Use This Skill

- Error occurs deep in call stack
- Bug appears in one place but originates elsewhere
- User says "why is this happening?"
- Symptoms don't match obvious cause
- Fix attempts don't resolve issue

## Process

### Phase 1: Capture the Symptom
Document exactly what happened:
- Error message (full text)
- Stack trace
- When it occurs (always? sometimes?)
- What action triggers it

### Phase 2: Trace Backwards
Follow the execution path in reverse:

```
Error Location (where it crashed)
     ↑
Immediate Caller (what called that)
     ↑
Previous Caller (what called that)
     ↑
... continue up the stack ...
     ↑
Root Cause (where bad data/state originated)
```

### Phase 3: Five Whys Analysis
Ask "why" repeatedly:

1. Why did [error] happen?
   → Because [immediate cause]
   
2. Why did [immediate cause] happen?
   → Because [deeper cause]
   
3. Why did [deeper cause] happen?
   → Because [even deeper]
   
4. Why did [even deeper] happen?
   → Because [root cause emerging]
   
5. Why did [root cause] happen?
   → Because [actual root cause]

### Phase 4: Verify Root Cause
Confirm you found the right cause:
- Can you reproduce by triggering root cause?
- Does fixing root cause prevent symptom?
- Are there other paths to same error?

### Phase 5: Document Findings
Create trace report:
- Symptom description
- Root cause identified
- Full trace path
- Fix recommendation

## Techniques

### Stack Trace Analysis
```bash
# Search for error origin
grep -rn "ErrorName" src/

# Find all callers of problematic function
grep -rn "functionName(" src/

# Trace imports
grep -rn "import.*moduleName" src/
```

### State Inspection
Track data flow:
- Where was the bad value set?
- What function transformed it?
- What condition allowed it through?

### Timeline Reconstruction
For async/timing issues:
1. Add timestamps to logs
2. Map execution order
3. Identify race conditions

### Bisection Method
For "it used to work":
```bash
git bisect start
git bisect bad HEAD
git bisect good <last-known-good>
# Test each commit
```

## Common Root Cause Categories

| Symptom | Often Caused By |
|---------|-----------------|
| Null/undefined | Missing initialization |
| Type error | Wrong data shape passed |
| Race condition | Async timing assumption |
| Memory issue | Retained references |
| State bug | Mutation without update |

## Output Format

```markdown
## Root Cause Analysis: [Error Name]

### Symptom
[What error appears]

### Trace Path
1. [Error location] - [what happened]
2. [Caller 1] - [how it contributed]
3. [Caller 2] - [how it contributed]
4. **ROOT CAUSE**: [Origin point]

### Five Whys
1. Why: [error]? Because [x]
2. Why: [x]? Because [y]
3. Why: [y]? Because [z]
4. Why: [z]? Because [root]
5. Why: [root]? Because [actual cause]

### Root Cause
[Clear statement of actual cause]

### Fix Recommendation
[How to fix at the source, not symptom]

### Prevention
[How to prevent similar issues]
```

## Example

User: "TypeError: Cannot read property 'map' of undefined"

Analysis:
1. Error in `UserList.tsx` line 42
2. Called from `Dashboard.tsx` line 87
3. Data comes from `useUsers()` hook
4. Hook returns undefined before fetch completes
5. **Root cause**: No loading state check before render
6. **Fix**: Add `if (loading) return <Spinner />` guard
