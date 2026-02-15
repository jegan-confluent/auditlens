---
name: testing-patterns
description: "Testing patterns for Jest, Vitest, and Playwright. Use when writing unit tests, integration tests, or E2E tests."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# Testing Patterns

## When to Use
- Writing unit tests
- Integration testing
- E2E testing with Playwright
- Mocking dependencies

## Unit Test Structure (AAA)
```typescript
test('should calculate total with tax', () => {
  // Arrange
  const cart = new Cart();
  cart.addItem({ price: 100 });
  
  // Act
  const total = cart.getTotal(0.1);
  
  // Assert
  expect(total).toBe(110);
});
```

## Mocking
```typescript
// Mock function
const mockFn = jest.fn().mockReturnValue('result');

// Mock module
jest.mock('./api', () => ({
  fetchUser: jest.fn().mockResolvedValue({ name: 'Test' })
}));

// Spy on method
jest.spyOn(console, 'log').mockImplementation();
```

## React Testing
```typescript
import { render, screen, fireEvent } from '@testing-library/react';

test('button click triggers handler', () => {
  const handleClick = jest.fn();
  render(<Button onClick={handleClick}>Click me</Button>);
  
  fireEvent.click(screen.getByText('Click me'));
  
  expect(handleClick).toHaveBeenCalledTimes(1);
});
```

## Playwright E2E
```typescript
test('user can login', async ({ page }) => {
  await page.goto('/login');
  await page.fill('[data-testid="email"]', 'user@test.com');
  await page.fill('[data-testid="password"]', 'password');
  await page.click('button[type="submit"]');
  
  await expect(page).toHaveURL('/dashboard');
});
```

## Coverage Goals
- Statements: 80%+
- Branches: 70%+
- Functions: 80%+
- Lines: 80%+
