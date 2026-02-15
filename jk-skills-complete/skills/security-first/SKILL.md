---
name: security-first
description: "Security best practices including input validation, authentication, and secrets management. Use when implementing security features."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Security First

## Input Validation
```typescript
// Always validate and sanitize
import { z } from 'zod';
import DOMPurify from 'dompurify';

const input = DOMPurify.sanitize(userInput);
const validated = schema.parse(input);
```

## Authentication
```typescript
// Hash passwords
import bcrypt from 'bcrypt';
const hash = await bcrypt.hash(password, 12);
const valid = await bcrypt.compare(password, hash);

// JWT tokens
import jwt from 'jsonwebtoken';
const token = jwt.sign({ userId }, SECRET, { expiresIn: '1h' });
```

## Secrets Management
- ✅ Use environment variables
- ✅ Never commit secrets to git
- ✅ Rotate secrets regularly
- ✅ Use .env.local for local dev
- ❌ Never log secrets

## SQL Injection Prevention
```typescript
// ❌ NEVER do this
const query = `SELECT * FROM users WHERE id = '${userId}'`;

// ✅ Use parameterized queries
const result = await db.query('SELECT * FROM users WHERE id = $1', [userId]);
```

## XSS Prevention
- Escape HTML output
- Use Content-Security-Policy headers
- Sanitize user input
- Use httpOnly cookies

## HTTPS & Headers
```typescript
// Security headers
app.use(helmet());
app.use(cors({ origin: allowedOrigins }));
```
