---
name: performance-patterns
description: "Performance optimization for web apps including caching, lazy loading, and profiling. Use when optimizing application performance."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# Performance Patterns

## Caching
```typescript
// Redis caching
const cached = await redis.get(key);
if (cached) return JSON.parse(cached);

const data = await fetchData();
await redis.set(key, JSON.stringify(data), 'EX', 3600);
return data;
```

## Lazy Loading
```typescript
// React lazy loading
const Dashboard = React.lazy(() => import('./Dashboard'));

<Suspense fallback={<Spinner />}>
  <Dashboard />
</Suspense>
```

## Database Optimization
```sql
-- Use EXPLAIN ANALYZE
EXPLAIN ANALYZE SELECT * FROM users WHERE email = 'test@example.com';

-- Add missing indexes
CREATE INDEX CONCURRENTLY idx_users_email ON users(email);
```

## Bundle Optimization
```javascript
// Dynamic imports
const module = await import('./heavy-module');

// Tree shaking - use named imports
import { specificFunction } from 'large-library';
```

## Metrics to Track
- Time to First Byte (TTFB): < 200ms
- First Contentful Paint (FCP): < 1.8s
- Largest Contentful Paint (LCP): < 2.5s
- Cumulative Layout Shift (CLS): < 0.1

## Quick Wins
- ✅ Enable gzip/brotli compression
- ✅ Use CDN for static assets
- ✅ Optimize images (WebP)
- ✅ Implement pagination
- ✅ Use connection pooling
