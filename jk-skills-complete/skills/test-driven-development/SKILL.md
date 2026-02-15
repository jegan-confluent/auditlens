---
name: test-driven-development
description: "Use when implementing any feature or bugfix. Write tests before implementation code. Red-Green-Refactor cycle for reliable, well-designed code."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# Test-Driven Development

Write tests first, then implementation. Red → Green → Refactor.

## When to Use This Skill

- Implementing new features
- Fixing bugs (write failing test first)
- User says "build this properly"
- Critical functionality needs reliability
- Refactoring existing code

## The TDD Cycle

### 🔴 RED: Write Failing Test
```typescript
// Write test for desired behavior
test('should calculate total with tax', () => {
  const cart = new Cart();
  cart.addItem({ price: 100 });
  
  expect(cart.getTotal(0.1)).toBe(110); // 10% tax
});
```
Run test → It fails (expected)

### 🟢 GREEN: Make It Pass
```typescript
// Write MINIMUM code to pass
class Cart {
  items: Item[] = [];
  
  addItem(item: Item) {
    this.items.push(item);
  }
  
  getTotal(taxRate: number) {
    const subtotal = this.items.reduce((sum, i) => sum + i.price, 0);
    return subtotal * (1 + taxRate);
  }
}
```
Run test → It passes

### 🔵 REFACTOR: Improve Code
```typescript
// Clean up without changing behavior
class Cart {
  private items: Item[] = [];
  
  addItem(item: Item): void {
    this.items.push(item);
  }
  
  private calculateSubtotal(): number {
    return this.items.reduce((sum, item) => sum + item.price, 0);
  }
  
  getTotal(taxRate: number): number {
    return this.calculateSubtotal() * (1 + taxRate);
  }
}
```
Run test → Still passes ✓

### Repeat cycle for next behavior

## Test Writing Guidelines

### Test Structure (AAA Pattern)
```typescript
test('descriptive name of behavior', () => {
  // Arrange - setup
  const user = createTestUser();
  
  // Act - execute
  const result = user.updateEmail('new@email.com');
  
  // Assert - verify
  expect(result.email).toBe('new@email.com');
});
```

### Good Test Names
```typescript
// ✅ Good - describes behavior
'should return empty array when no items match filter'
'should throw error when email is invalid'
'should update user profile and return updated data'

// ❌ Bad - vague or implementation-focused
'test filter'
'email test'
'updateProfile works'
```

### Edge Cases to Test
- Empty inputs
- Null/undefined values
- Boundary values (0, max, min)
- Invalid inputs
- Error conditions
- Async behavior

## Bug Fix Workflow

1. **Reproduce**: Understand the bug
2. **Write Failing Test**: Captures the bug
3. **Fix**: Make test pass
4. **Verify**: Run full test suite
5. **Commit**: Test + fix together

```typescript
// Bug: User can submit empty name
test('should reject empty name', () => {
  const result = validateUser({ name: '' });
  expect(result.valid).toBe(false);
  expect(result.errors).toContain('Name is required');
});
```

## Test File Organization

```
src/
├── components/
│   ├── Button.tsx
│   └── Button.test.tsx      # Co-located test
├── services/
│   ├── UserService.ts
│   └── UserService.test.ts  # Co-located test
└── utils/
    ├── formatters.ts
    └── formatters.test.ts   # Co-located test
```

## Commands

```bash
# Run all tests
npm test

# Run specific test file
npm test Button.test.tsx

# Run tests in watch mode
npm test -- --watch

# Run with coverage
npm test -- --coverage
```

## Anti-Patterns to Avoid

❌ Writing tests after code (misses design benefits)
❌ Testing implementation details
❌ Over-mocking (brittle tests)
❌ Skipping refactor step
❌ Large test-fix-test cycles (keep small)

## Example TDD Session

**Feature**: Calculate shipping cost based on weight

```typescript
// 1. RED - Write test
test('should calculate shipping at $5 per kg', () => {
  expect(calculateShipping(2)).toBe(10);
});
// Run → FAIL

// 2. GREEN - Minimal implementation
function calculateShipping(weightKg: number): number {
  return weightKg * 5;
}
// Run → PASS

// 3. RED - Add edge case
test('should have $10 minimum shipping', () => {
  expect(calculateShipping(1)).toBe(10);
});
// Run → FAIL

// 4. GREEN - Handle edge case
function calculateShipping(weightKg: number): number {
  return Math.max(weightKg * 5, 10);
}
// Run → PASS

// 5. REFACTOR - Extract constants
const RATE_PER_KG = 5;
const MINIMUM_SHIPPING = 10;

function calculateShipping(weightKg: number): number {
  const cost = weightKg * RATE_PER_KG;
  return Math.max(cost, MINIMUM_SHIPPING);
}
// Run → PASS
```
