---
name: refactoring-patterns
description: "Code refactoring techniques and patterns. Use when improving existing code structure."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Refactoring Patterns

## Extract Function
```typescript
// Before
function processOrder(order) {
  // 50 lines of validation
  // 30 lines of calculation
  // 20 lines of saving
}

// After
function processOrder(order) {
  validateOrder(order);
  const total = calculateTotal(order);
  saveOrder(order, total);
}
```

## Replace Conditionals with Polymorphism
```typescript
// Before
function getPrice(type) {
  if (type === 'basic') return 10;
  if (type === 'premium') return 20;
}

// After
const pricing = { basic: 10, premium: 20 };
const getPrice = (type) => pricing[type];
```

## Introduce Parameter Object
```typescript
// Before
function search(query, page, limit, sortBy, order) {}

// After
interface SearchOptions {
  query: string;
  page?: number;
  limit?: number;
  sort?: { by: string; order: 'asc' | 'desc' };
}
function search(options: SearchOptions) {}
```

## Code Smells to Fix
- Long methods (>20 lines)
- Deep nesting (>3 levels)
- Duplicate code
- Large classes
- Long parameter lists
- Feature envy
