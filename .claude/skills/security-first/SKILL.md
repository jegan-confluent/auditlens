---
name: security-first
description: Security patterns
---
# Security First

## Environment Variables
```typescript
// ✅ Good
const apiKey = process.env.API_KEY;
// ❌ Bad
const apiKey = 'sk-1234567890';
```

## Password Hashing
```typescript
import bcrypt from 'bcrypt';
const hash = await bcrypt.hash(password, 12);
const valid = await bcrypt.compare(password, hash);
```

## JWT
```typescript
const token = jwt.sign({ userId }, process.env.JWT_SECRET!, { expiresIn: '1h' });
const payload = jwt.verify(token, process.env.JWT_SECRET!);
```

## Best Practices
- ✅ Hash passwords (bcrypt 12+)
- ✅ Use HTTPS
- ✅ Validate all input
- ❌ Never log sensitive data
