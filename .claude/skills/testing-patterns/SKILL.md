---
name: testing-patterns
description: Jest, Vitest, Playwright testing
---
# Testing Patterns

## Unit Test
```typescript
describe('UserService', () => {
  it('should return user', async () => {
    const mockRepo = { findById: vi.fn().mockResolvedValue({ id: '1' }) };
    const service = new UserService(mockRepo);
    const result = await service.getUser('1');
    expect(result.id).toBe('1');
  });
});
```

## Component Test
```typescript
import { render, screen } from '@testing-library/react';
it('renders button', () => {
  render(<Button label="Click" onClick={() => {}} />);
  expect(screen.getByRole('button')).toHaveTextContent('Click');
});
```

## E2E (Playwright)
```typescript
test('login flow', async ({ page }) => {
  await page.goto('/login');
  await page.fill('[name="email"]', 'test@example.com');
  await page.click('button[type="submit"]');
  await expect(page).toHaveURL('/dashboard');
});
```

## Best Practices
- ✅ AAA pattern: Arrange, Act, Assert
- ✅ Test behavior, not implementation
- ❌ Don't share state between tests
