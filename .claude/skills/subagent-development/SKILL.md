---
name: subagent-development
description: Dispatch independent subagents for parallel development
---
# Subagent Driven Development

## Overview
Dispatch independent subagents for individual tasks with code review checkpoints.

## When to Use
- Multiple independent features
- Large refactoring tasks
- Parallel workstreams

## Pattern
```
Main Agent
├── Subagent 1: Feature A
│   └── Checkpoint: Review
├── Subagent 2: Feature B
│   └── Checkpoint: Review
└── Integration: Merge all
```

## Implementation
```typescript
// Dispatch pattern
const tasks = [
  { name: "auth", prompt: "Implement auth module" },
  { name: "api", prompt: "Build API endpoints" },
  { name: "ui", prompt: "Create UI components" }
];

// Each runs independently, checkpoints for review
```

## Best Practices
- ✅ Clear task boundaries
- ✅ Review checkpoints between iterations
- ✅ Integration tests after merge
