---
name: webapp-testing
description: "Test web applications using Playwright for browser automation. Use when verifying frontend functionality, debugging UI behavior, or capturing screenshots."
allowed-tools: "Bash,Read,Write"
version: 1.0.0
---

# Webapp Testing

Automated browser testing with Playwright for web applications.

## When to Use This Skill

- Testing web UI functionality
- Capturing screenshots
- User says "test this page"
- Debugging frontend issues
- E2E testing workflows

## Quick Start

### Install Playwright
```bash
npm init playwright@latest
# or
npx playwright install
```

### Basic Test Structure
```typescript
import { test, expect } from '@playwright/test';

test('homepage loads correctly', async ({ page }) => {
  await page.goto('http://localhost:3000');
  
  // Check title
  await expect(page).toHaveTitle(/My App/);
  
  // Check element exists
  await expect(page.locator('h1')).toContainText('Welcome');
  
  // Take screenshot
  await page.screenshot({ path: 'homepage.png' });
});
```

## Common Testing Patterns

### Navigation & Clicks
```typescript
// Click button
await page.click('button[type="submit"]');

// Click by text
await page.click('text=Sign In');

// Navigate
await page.goto('/dashboard');

// Wait for navigation
await Promise.all([
  page.waitForNavigation(),
  page.click('a[href="/profile"]'),
]);
```

### Form Interactions
```typescript
// Fill input
await page.fill('input[name="email"]', 'test@example.com');

// Select dropdown
await page.selectOption('select#country', 'US');

// Check checkbox
await page.check('input[type="checkbox"]');

// Submit form
await page.click('button[type="submit"]');
```

### Assertions
```typescript
// Element visible
await expect(page.locator('.success-message')).toBeVisible();

// Element text
await expect(page.locator('.title')).toHaveText('Dashboard');

// Element count
await expect(page.locator('.list-item')).toHaveCount(5);

// URL check
await expect(page).toHaveURL(/.*dashboard/);
```

### Waiting
```typescript
// Wait for element
await page.waitForSelector('.loaded');

// Wait for network
await page.waitForResponse('**/api/users');

// Wait for load state
await page.waitForLoadState('networkidle');

// Custom timeout
await page.waitForSelector('.slow-element', { timeout: 10000 });
```

## Screenshots & Debugging

### Capture Screenshots
```typescript
// Full page
await page.screenshot({ path: 'full.png', fullPage: true });

// Element only
await page.locator('.chart').screenshot({ path: 'chart.png' });

// On failure
test.afterEach(async ({ page }, testInfo) => {
  if (testInfo.status !== 'passed') {
    await page.screenshot({ path: `failed-${testInfo.title}.png` });
  }
});
```

### Debug Mode
```bash
# Run with headed browser
npx playwright test --headed

# Debug step by step
npx playwright test --debug

# Record video
npx playwright test --video=on
```

## Test Configuration

### playwright.config.ts
```typescript
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 30000,
  retries: 2,
  use: {
    baseURL: 'http://localhost:3000',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
    { name: 'firefox', use: { browserName: 'firefox' } },
    { name: 'webkit', use: { browserName: 'webkit' } },
  ],
});
```

## E2E Test Example

```typescript
test.describe('User Authentication', () => {
  test('should login successfully', async ({ page }) => {
    await page.goto('/login');
    
    await page.fill('[data-testid="email"]', 'user@example.com');
    await page.fill('[data-testid="password"]', 'password123');
    await page.click('button[type="submit"]');
    
    await expect(page).toHaveURL('/dashboard');
    await expect(page.locator('.welcome')).toContainText('Welcome back');
  });

  test('should show error for invalid credentials', async ({ page }) => {
    await page.goto('/login');
    
    await page.fill('[data-testid="email"]', 'wrong@example.com');
    await page.fill('[data-testid="password"]', 'wrongpassword');
    await page.click('button[type="submit"]');
    
    await expect(page.locator('.error')).toContainText('Invalid credentials');
    await expect(page).toHaveURL('/login');
  });
});
```

## Running Tests

```bash
# All tests
npx playwright test

# Specific file
npx playwright test tests/login.spec.ts

# Specific test
npx playwright test -g "should login"

# Show report
npx playwright show-report
```

## Best Practices

- Use `data-testid` attributes for reliable selectors
- Keep tests independent (no shared state)
- Use page objects for reusable components
- Run tests in CI/CD pipeline
- Use `test.describe` for grouping
