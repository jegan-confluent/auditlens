---
name: api-patterns
description: REST API design and validation
---
# API Patterns

## Route Handler
```typescript
import { z } from 'zod';
const Schema = z.object({ email: z.string().email(), name: z.string().min(2) });

export async function POST(req: NextRequest) {
  try {
    const body = Schema.parse(await req.json());
    const user = await createUser(body);
    return NextResponse.json(user, { status: 201 });
  } catch (e) {
    if (e instanceof z.ZodError) return NextResponse.json({ error: e.errors }, { status: 400 });
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}
```

## Response Helpers
```typescript
const ok = <T>(data: T) => NextResponse.json(data, { status: 200 });
const created = <T>(data: T) => NextResponse.json(data, { status: 201 });
const badRequest = (msg: string) => NextResponse.json({ error: msg }, { status: 400 });
```

## Best Practices
- ✅ Validate all inputs
- ✅ Consistent error format
- ❌ Don't expose internal errors
