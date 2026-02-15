---
name: test-driven-development
description: Write tests before implementation
---
# Test Driven Development

## When to Use
Before writing implementation code for any feature or bugfix.

## TDD Cycle
```
RED → GREEN → REFACTOR
```

1. **RED:** Write failing test
2. **GREEN:** Minimal code to pass
3. **REFACTOR:** Clean up, keep tests green

## Example Flow
```typescript
// 1. RED - Write test first
it('should calculate total with tax', () => {
  expect(calculateTotal(100, 0.1)).toBe(110);
});

// 2. GREEN - Make it pass
function calculateTotal(amount: number, taxRate: number): number {
  return amount * (1 + taxRate);
}

// 3. REFACTOR - Improve if needed
```

## Best Practices
- ✅ One assertion per test
- ✅ Descriptive test names
- ✅ Test edge cases
- ❌ Don't test implementation details
