---
name: multi-tenant
description: "Multi-tenant architecture patterns with data isolation. Use when building SaaS applications."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Multi-Tenant Architecture

## Database Strategy Options
| Strategy | Isolation | Complexity | Cost |
|----------|-----------|------------|------|
| Shared DB, shared schema | Low | Low | Low |
| Shared DB, separate schema | Medium | Medium | Medium |
| Separate databases | High | High | High |

## Row-Level Security (Recommended)
```sql
-- Add tenant_id to all tables
ALTER TABLE documents ADD COLUMN tenant_id UUID NOT NULL;

-- Enable RLS
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;

-- Create policy
CREATE POLICY tenant_isolation ON documents
  USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

## Middleware Pattern
```typescript
async function tenantMiddleware(req, res, next) {
  const tenantId = req.headers['x-tenant-id'];
  
  if (!tenantId) {
    return res.status(400).json({ error: 'Tenant ID required' });
  }
  
  // Verify tenant exists and user has access
  const tenant = await getTenant(tenantId);
  if (!tenant || !userHasAccess(req.user, tenant)) {
    return res.status(403).json({ error: 'Access denied' });
  }
  
  req.tenant = tenant;
  next();
}
```

## Query Scoping
```typescript
class TenantScopedRepository<T> {
  constructor(private tenantId: string) {}
  
  async findAll(): Promise<T[]> {
    return db.query('SELECT * FROM ? WHERE tenant_id = ?', [
      this.table,
      this.tenantId
    ]);
  }
}
```

## Tenant Onboarding
1. Create tenant record
2. Create admin user
3. Initialize default settings
4. Send welcome email
