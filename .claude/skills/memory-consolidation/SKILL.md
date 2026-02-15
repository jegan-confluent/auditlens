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
