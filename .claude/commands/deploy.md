---
name: deploy
description: Deploy to production
---
# Deploy
1. Run tests: `npm test`
2. Type check: `npm run type-check`
3. Build: `npm run build`
4. Tag: `git tag -a v{version} -m "Release"`
5. Push: `git push origin main --tags`
6. Verify health endpoint
