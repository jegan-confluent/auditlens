---
name: database-patterns
description: Database design and queries
---
# Database Patterns

## Schema
```sql
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(255) UNIQUE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_users_email ON users(email);
```

## Queries
```typescript
// Parameterized (safe)
const user = await db.query('SELECT * FROM users WHERE email = $1', [email]);

// Pagination
const getUsers = (page: number, limit: number) =>
  db.query('SELECT * FROM users ORDER BY created_at DESC LIMIT $1 OFFSET $2',
    [limit, (page - 1) * limit]);
```

## Best Practices
- ✅ Use UUIDs for PKs
- ✅ Add indexes
- ✅ Use parameterized queries
- ❌ Never SELECT *
