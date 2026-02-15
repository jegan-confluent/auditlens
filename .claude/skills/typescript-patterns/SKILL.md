---
name: typescript-patterns
description: TypeScript best practices and strict typing
---
# TypeScript Patterns

## Strict Config
```json
{"compilerOptions": {"strict": true, "noImplicitAny": true, "strictNullChecks": true}}
```

## Type Definitions
```typescript
interface User { id: string; email: string; createdAt: Date; }
type Status = 'pending' | 'active' | 'archived';
type Result<T> = { success: true; data: T } | { success: false; error: string };
```

## Type Guards
```typescript
function isUser(obj: unknown): obj is User {
  return typeof obj === 'object' && obj !== null && 'id' in obj && 'email' in obj;
}
```

## Best Practices
- ✅ Enable strict mode
- ✅ Use `unknown` instead of `any`
- ✅ Prefer interfaces for objects
- ❌ Avoid `any` and `@ts-ignore`
