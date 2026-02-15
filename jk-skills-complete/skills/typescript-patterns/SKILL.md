---
name: typescript-patterns
description: "TypeScript best practices including strict typing, generics, utility types, and type guards. Use when writing TypeScript code or reviewing types."
allowed-tools: "Read,Write"
version: 1.0.0
---

# TypeScript Patterns

## When to Use
- Writing TypeScript code
- Defining interfaces and types
- Using generics
- Type safety concerns

## Strict Types
```typescript
interface User {
  id: string;
  name: string;
  email: string;
  createdAt: Date;
}

// Avoid any - use unknown instead
const data: unknown = fetchData();
```

## Utility Types
```typescript
type UpdateUser = Partial<User>;           // All optional
type UserPreview = Pick<User, 'id' | 'name'>; // Select specific
type CreateUser = Omit<User, 'id' | 'createdAt'>; // Exclude
type UserMap = Record<string, User>;       // Dictionary
```

## Type Guards
```typescript
function isUser(obj: unknown): obj is User {
  return typeof obj === 'object' && obj !== null && 'email' in obj;
}
```

## Generics
```typescript
async function fetchOne<T>(id: string): Promise<T> {
  const response = await fetch(`/api/${id}`);
  return response.json();
}

function merge<T extends object, U extends object>(a: T, b: U): T & U {
  return { ...a, ...b };
}
```

## Best Practices
- ✅ Enable strict mode in tsconfig.json
- ✅ Use interfaces for objects, types for unions
- ✅ Prefer unknown over any
- ✅ Use const assertions for literals
- ❌ Don't use @ts-ignore without comment
