---
name: security-audit
description: Run security audit
---
# Security Audit
1. `grep -rn "password\s*=\|api_key\s*=" src/`
2. `npm audit`
3. Check RLS policies
4. Verify HTTPS
5. Check rate limiting
