---
name: hybrid-intelligence
description: "Combine rules-based logic with LLM intelligence. Use when building systems that need both predictable rules and AI flexibility."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Hybrid Intelligence

## When to Use Rules vs LLM

| Use Rules | Use LLM |
|-----------|---------|
| Validation (NPI, email) | Natural language understanding |
| Math calculations | Ambiguous categorization |
| Compliance checks | Content generation |
| Exact matching | Fuzzy matching |

## Architecture Pattern
```typescript
async function processData(input: string) {
  // Step 1: Rules-based validation
  const validation = validateWithRules(input);
  if (!validation.valid) {
    return { error: validation.errors };
  }
  
  // Step 2: Rules-based extraction (fast, cheap)
  const extracted = extractWithRegex(input);
  
  // Step 3: LLM for ambiguous cases only
  if (extracted.confidence < 0.8) {
    const llmResult = await classifyWithLLM(input);
    return merge(extracted, llmResult);
  }
  
  return extracted;
}
```

## Cost Optimization
```typescript
// Cache LLM results
const cacheKey = hashInput(input);
const cached = await cache.get(cacheKey);
if (cached) return cached;

const result = await llm.complete(prompt);
await cache.set(cacheKey, result, TTL);
```

## Confidence Scoring
```typescript
interface Result {
  value: string;
  confidence: number;  // 0-1
  source: 'rules' | 'llm' | 'hybrid';
}
```

## Fallback Strategy
1. Try rules first (fast, free)
2. Try pattern matching (fast, free)
3. Fall back to LLM (slow, costly)
4. Human review for low confidence
