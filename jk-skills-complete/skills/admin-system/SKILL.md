---
name: admin-system
description: "Admin dashboard patterns including RBAC, audit logs, and management interfaces. Use when building admin features."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Admin System

## Role-Based Access Control
```typescript
enum Role {
  ADMIN = 'admin',
  MANAGER = 'manager',
  STAFF = 'staff',
  VIEWER = 'viewer'
}

const permissions = {
  'users:read': [Role.ADMIN, Role.MANAGER, Role.STAFF],
  'users:write': [Role.ADMIN, Role.MANAGER],
  'users:delete': [Role.ADMIN],
  'settings:read': [Role.ADMIN, Role.MANAGER],
  'settings:write': [Role.ADMIN]
};

function hasPermission(role: Role, permission: string): boolean {
  return permissions[permission]?.includes(role) ?? false;
}
```

## Audit Logging
```typescript
interface AuditLog {
  id: string;
  userId: string;
  action: string;
  resource: string;
  resourceId: string;
  changes: Record<string, { old: any; new: any }>;
  ipAddress: string;
  timestamp: Date;
}

async function logAction(log: Omit<AuditLog, 'id' | 'timestamp'>) {
  await db.insert(auditLogs).values({
    ...log,
    id: crypto.randomUUID(),
    timestamp: new Date()
  });
}
```

## Dashboard Metrics
```typescript
async function getDashboardStats() {
  return {
    totalUsers: await db.count(users),
    activeToday: await db.count(users, { lastActive: today }),
    newThisWeek: await db.count(users, { createdAt: thisWeek }),
    revenue: await db.sum(invoices, 'amount', { status: 'paid' })
  };
}
```

## Data Tables
```typescript
interface TableConfig {
  columns: Column[];
  sortable: string[];
  filterable: string[];
  searchable: string[];
  actions: ('view' | 'edit' | 'delete')[];
}
```
