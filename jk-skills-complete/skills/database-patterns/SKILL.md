---
name: database-patterns
description: "Database design, queries, indexing, and migrations. Use when designing schemas, writing queries, or optimizing database performance."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# Database Patterns

## Schema Design
```sql
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(255) UNIQUE NOT NULL,
  name VARCHAR(100) NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_users_email ON users(email);
```

## Query Patterns
```sql
-- Pagination
SELECT * FROM users ORDER BY created_at DESC LIMIT 20 OFFSET 40;

-- Search
SELECT * FROM users WHERE name ILIKE '%search%';

-- Join with aggregation
SELECT u.name, COUNT(o.id) as order_count
FROM users u LEFT JOIN orders o ON u.id = o.user_id
GROUP BY u.id;
```

## Indexing Strategy
- ✅ Index foreign keys
- ✅ Index columns in WHERE clauses
- ✅ Composite index for multi-column queries
- ❌ Don't over-index (slows writes)

## Transactions
```typescript
await db.transaction(async (tx) => {
  await tx.insert(orders).values(order);
  await tx.update(inventory).set({ quantity: sql`quantity - 1` });
});
```
