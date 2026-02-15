---
name: performance-patterns
description: Performance optimization
---
# Performance Patterns

## React Optimization
```typescript
const Heavy = lazy(() => import('./Heavy'));
<Suspense fallback={<Loading />}><Heavy /></Suspense>
```

## Caching
```typescript
const cache = new Map<string, { value: any; expiry: number }>();
function get(key: string) {
  const entry = cache.get(key);
  if (!entry || Date.now() > entry.expiry) return undefined;
  return entry.value;
}
```

## Database
```sql
EXPLAIN ANALYZE SELECT * FROM users WHERE email = $1;
CREATE INDEX CONCURRENTLY idx_email ON users(email);
```

## Best Practices
- ✅ Measure before optimizing
- ✅ Lazy load heavy components
- ✅ Use proper indexes
- ❌ Don't premature optimize
