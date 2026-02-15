---
name: api-patterns
description: "REST API design, validation, and error handling patterns. Use when building or consuming APIs."
allowed-tools: "Read,Write"
version: 1.0.0
---

# API Patterns

## When to Use
- Designing REST APIs
- Input validation
- Error handling
- API documentation

## REST Conventions
| Method | Endpoint | Action |
|--------|----------|--------|
| GET | /users | List users |
| GET | /users/:id | Get single user |
| POST | /users | Create user |
| PUT | /users/:id | Replace user |
| PATCH | /users/:id | Update user |
| DELETE | /users/:id | Delete user |

## Response Format
```typescript
// Success
{
  "data": { ... },
  "meta": { "total": 100, "page": 1, "limit": 20 }
}

// Error
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input",
    "details": [{ "field": "email", "message": "Invalid email format" }]
  }
}
```

## Validation with Zod
```typescript
import { z } from 'zod';

const CreateUserSchema = z.object({
  name: z.string().min(1).max(100),
  email: z.string().email(),
  age: z.number().int().positive().optional()
});

type CreateUser = z.infer<typeof CreateUserSchema>;

// In handler
const result = CreateUserSchema.safeParse(req.body);
if (!result.success) {
  return res.status(400).json({ error: result.error });
}
```

## Error Handling
```typescript
class AppError extends Error {
  constructor(
    public statusCode: number,
    public code: string,
    message: string
  ) {
    super(message);
  }
}

// Usage
throw new AppError(404, 'USER_NOT_FOUND', 'User does not exist');
```

## Status Codes
- 200: Success
- 201: Created
- 204: No Content
- 400: Bad Request
- 401: Unauthorized
- 403: Forbidden
- 404: Not Found
- 500: Server Error
