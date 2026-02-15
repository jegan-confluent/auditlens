---
name: deployment-patterns
description: "Deployment strategies for Vercel, Docker, and CI/CD. Use when deploying applications."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# Deployment Patterns

## Vercel Deployment
```json
// vercel.json
{
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "env": {
    "DATABASE_URL": "@database-url"
  }
}
```

## Docker
```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
EXPOSE 3000
CMD ["node", "dist/index.js"]
```

## GitHub Actions CI/CD
```yaml
name: Deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - run: npm ci
      - run: npm test
      - run: npm run build
```

## Environment Strategy
- development: Local dev
- staging: Pre-production testing
- production: Live environment

## Health Checks
```typescript
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: Date.now() });
});
```
