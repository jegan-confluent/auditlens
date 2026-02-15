---
name: meeting-insights
description: "Extract insights and action items from meeting transcripts. Use for meeting summaries."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Meeting Insights Analyzer

## Output Format
```markdown
# Meeting Summary

**Date:** [date]
**Attendees:** [list]
**Duration:** [time]

## Key Decisions
1. [Decision with context]
2. [Decision with context]

## Action Items
| Owner | Task | Due Date |
|-------|------|----------|
| @person | Task description | Date |

## Discussion Points
- Topic 1: [summary]
- Topic 2: [summary]

## Open Questions
- [ ] Question needing resolution

## Next Steps
- Follow-up meeting: [date/topic]
```

## Extraction Patterns
```typescript
const patterns = {
  decisions: /decided|agreed|approved|will proceed/gi,
  actions: /will|should|need to|action item|todo/gi,
  questions: /\?|unclear|need to clarify/gi,
  owners: /@\w+|assigned to \w+/gi,
  dates: /by \w+day|next week|EOD|before \d+/gi
};
```

## Sentiment Indicators
- Positive: "excited", "great progress", "on track"
- Concerns: "worried", "risk", "blocker"
- Neutral: "discussed", "reviewed"
