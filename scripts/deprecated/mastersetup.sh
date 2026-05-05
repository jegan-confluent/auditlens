#!/bin/bash
#===============================================================================
#
#   CLAUDE CODE MASTER SETUP v2.0
#   Universal Foundation for ANY Project
#
#===============================================================================
#
# WHAT THIS INSTALLS:
#   ├── 6 Universal Hooks (cost, tokens, skills, build, security, audit)
#   ├── 9 Universal Skills (typescript, react, testing, api, database, supabase, security, deployment, performance)
#   ├── 6 Slash Commands (/deploy, /security-audit, /cost-report, /test, /document, /optimize)
#   ├── 5 Prompting Templates
#   ├── 3 Dev Docs (plan.md, context.md, tasks.md)
#   └── 3 Helper Tools (analyze-costs, setup-project, skill-tester)
#
# USAGE:
#   cd ~/your-project
#   ./claude-code-master-setup.sh
#
# AFTER SETUP, ADD DOMAIN ADDONS:
#   ./claude-code-addon-healthcare.sh      # For Tidify-like projects
#   ./claude-code-addon-patient-portal.sh  # For CareLink-like projects
#   ./claude-code-addon-fintech.sh         # For CashKoda-like projects
#   ./claude-code-addon-edtech.sh          # For SpiralSpeak-like projects
#
#===============================================================================

set -e

VERSION="2.0.0"
PROJECT_ROOT="$(pwd)"
PROJECT_NAME=$(basename "$PROJECT_ROOT")
TIMESTAMP=$(date +%Y-%m-%d)

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

print_banner() {
    echo -e "${PURPLE}"
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║     CLAUDE CODE MASTER SETUP v${VERSION}                          ║"
    echo "║     Universal Foundation for ANY Project                      ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

print_section() {
    echo ""
    echo -e "${GREEN}━━━ $1 ━━━${NC}"
}

#===============================================================================
# DIRECTORY STRUCTURE
#===============================================================================

create_directories() {
    print_section "Creating Directory Structure"
    
    mkdir -p .claude/{skills,hooks,commands,prompts,templates}
    mkdir -p .dev-docs
    mkdir -p logs
    mkdir -p tools
    
    echo -e "${GREEN}✓${NC} .claude/{skills,hooks,commands,prompts,templates}"
    echo -e "${GREEN}✓${NC} .dev-docs/, logs/, tools/"
}

#===============================================================================
# CLAUDE.md - Project Context
#===============================================================================

create_claude_md() {
    print_section "Creating CLAUDE.md"
    
    [ -f ".claude/CLAUDE.md" ] && echo -e "${YELLOW}⊘${NC} CLAUDE.md exists (skipping)" && return
    
    cat > .claude/CLAUDE.md << 'EOF'
# Project: PROJECT_NAME_PLACEHOLDER

## Quick Context
<!-- Describe your project in 2-3 sentences -->

## Tech Stack
- **Frontend:** 
- **Backend:** 
- **Database:** 
- **Deployment:** 

## Quick Commands
```bash
npm run dev      # Development
npm run build    # Production build
npm test         # Run tests
```

## Project Structure
```
src/
├── components/    # UI components
├── services/      # Business logic
├── hooks/         # Custom hooks
├── types/         # TypeScript types
└── utils/         # Utilities
```

## Critical Rules
1. Follow TypeScript strict mode
2. Write tests for new features
3. Use conventional commits
4. Never hardcode secrets

## Current Focus
- [ ] Current task

## Skills Available
Base: typescript-patterns, react-patterns, testing-patterns, api-patterns, database-patterns
Extended: supabase-patterns, security-first, deployment-patterns, performance-patterns

---
Last Updated: TIMESTAMP_PLACEHOLDER
EOF

    sed -i "s/PROJECT_NAME_PLACEHOLDER/${PROJECT_NAME}/g" .claude/CLAUDE.md 2>/dev/null || \
    sed -i '' "s/PROJECT_NAME_PLACEHOLDER/${PROJECT_NAME}/g" .claude/CLAUDE.md
    sed -i "s/TIMESTAMP_PLACEHOLDER/${TIMESTAMP}/g" .claude/CLAUDE.md 2>/dev/null || \
    sed -i '' "s/TIMESTAMP_PLACEHOLDER/${TIMESTAMP}/g" .claude/CLAUDE.md
    
    echo -e "${GREEN}✓${NC} CLAUDE.md"
}

#===============================================================================
# hooks.json - Hook Configuration
#===============================================================================

create_hooks_json() {
    print_section "Creating hooks.json"
    
    cat > .claude/hooks.json << 'EOF'
{
  "version": "2.0",
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Task|Bash|mcp__*",
        "hooks": [{"type": "command", "command": ".claude/hooks/cost-guard.sh"}]
      },
      {
        "matcher": "str_replace|create_file|Edit|Write",
        "hooks": [{"type": "command", "command": ".claude/hooks/security-guard.sh"}]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "str_replace|create_file",
        "hooks": [{"type": "command", "command": ".claude/hooks/build-checker.sh"}]
      },
      {
        "matcher": "*",
        "hooks": [
          {"type": "command", "command": ".claude/hooks/token-tracker.sh"},
          {"type": "command", "command": ".claude/hooks/audit-logger.sh"}
        ]
      }
    ],
    "UserPromptSubmit": [
      {"hooks": [{"type": "command", "command": ".claude/hooks/skill-loader.sh"}]}
    ]
  }
}
EOF
    echo -e "${GREEN}✓${NC} hooks.json"
}

#===============================================================================
# skill-rules.json - Auto-Activation Rules
#===============================================================================

create_skill_rules() {
    print_section "Creating skill-rules.json"
    
    cat > .claude/skill-rules.json << 'EOF'
{
  "version": "2.0",
  "rules": [
    {"skill": "typescript-patterns", "keywords": ["typescript", "type", "interface", "generic", "enum"]},
    {"skill": "react-patterns", "keywords": ["component", "hook", "useState", "useEffect", "context", "props"]},
    {"skill": "testing-patterns", "keywords": ["test", "jest", "vitest", "playwright", "mock", "coverage"]},
    {"skill": "api-patterns", "keywords": ["api", "endpoint", "REST", "GraphQL", "route", "middleware"]},
    {"skill": "database-patterns", "keywords": ["database", "SQL", "query", "migration", "schema", "ORM"]},
    {"skill": "supabase-patterns", "keywords": ["supabase", "RLS", "RPC", "auth", "storage", "realtime"]},
    {"skill": "security-first", "keywords": ["security", "encrypt", "auth", "JWT", "password", "secret"]},
    {"skill": "deployment-patterns", "keywords": ["deploy", "CI/CD", "Docker", "Vercel", "AWS", "pipeline"]},
    {"skill": "performance-patterns", "keywords": ["performance", "optimize", "cache", "lazy", "bundle"]}
  ]
}
EOF
    echo -e "${GREEN}✓${NC} skill-rules.json"
}

#===============================================================================
# HOOKS (6)
#===============================================================================

create_hooks() {
    print_section "Creating Hooks (6)"
    
    # 1. Cost Guard
    cat > .claude/hooks/cost-guard.sh << 'EOF'
#!/bin/bash
BUDGET=${CLAUDE_DAILY_BUDGET:-50.00}
TODAY=$(date +%Y-%m-%d)
LOG_FILE="logs/tokens-$TODAY.jsonl"
mkdir -p logs
if [ -f "$LOG_FILE" ] && command -v jq &>/dev/null && command -v bc &>/dev/null; then
    TODAY_COST=$(jq -s 'map(.cost // 0) | add // 0' "$LOG_FILE" 2>/dev/null || echo "0")
    if (( $(echo "$TODAY_COST > $BUDGET" | bc -l 2>/dev/null || echo "0") )); then
        echo "🚨 Budget exceeded: \$$TODAY_COST / \$$BUDGET" >&2
        exit 2
    fi
    WARN=$(echo "$BUDGET * 0.8" | bc -l)
    (( $(echo "$TODAY_COST > $WARN" | bc -l 2>/dev/null || echo "0") )) && echo "⚠️ Budget: \$$TODAY_COST / \$$BUDGET" >&2
fi
exit 0
EOF
    chmod +x .claude/hooks/cost-guard.sh
    echo -e "${GREEN}✓${NC} cost-guard.sh"
    
    # 2. Token Tracker
    cat > .claude/hooks/token-tracker.sh << 'EOF'
#!/bin/bash
mkdir -p logs
TODAY=$(date +%Y-%m-%d)
LOG_FILE="logs/tokens-$TODAY.jsonl"
if [ -n "$HOOK_OUTPUT" ] && command -v jq &>/dev/null; then
    INPUT=$(echo "$HOOK_OUTPUT" | jq -r '.usage.input_tokens // 0' 2>/dev/null)
    OUTPUT=$(echo "$HOOK_OUTPUT" | jq -r '.usage.output_tokens // 0' 2>/dev/null)
    if [ "$INPUT" != "0" ] || [ "$OUTPUT" != "0" ]; then
        COST=$(echo "scale=6; ($INPUT * 0.000003) + ($OUTPUT * 0.000015)" | bc 2>/dev/null || echo "0")
        echo "{\"ts\":\"$(date -Iseconds)\",\"in\":$INPUT,\"out\":$OUTPUT,\"cost\":$COST}" >> "$LOG_FILE"
        echo "📊 ${INPUT}in/${OUTPUT}out (~\$$(printf '%.4f' $COST))" >&2
    fi
fi
exit 0
EOF
    chmod +x .claude/hooks/token-tracker.sh
    echo -e "${GREEN}✓${NC} token-tracker.sh"
    
    # 3. Skill Loader
    cat > .claude/hooks/skill-loader.sh << 'EOF'
#!/bin/bash
command -v jq &>/dev/null || exit 0
MSG=$(echo "$HOOK_INPUT" | jq -r '.message // .content // ""' 2>/dev/null | head -c 500)
[ -z "$MSG" ] && exit 0
[ ! -f ".claude/skill-rules.json" ] && exit 0
SKILLS=$(jq -r --arg m "$MSG" '.rules[] | select(.keywords | any(. as $k | $m | test($k; "i"))) | .skill' .claude/skill-rules.json 2>/dev/null | head -3)
if [ -n "$SKILLS" ]; then
    echo "" >&2
    echo "🎯 Auto-loading: $SKILLS" >&2
    for s in $SKILLS; do
        [ -f ".claude/skills/$s/SKILL.md" ] && head -80 ".claude/skills/$s/SKILL.md"
    done
fi
exit 0
EOF
    chmod +x .claude/hooks/skill-loader.sh
    echo -e "${GREEN}✓${NC} skill-loader.sh"
    
    # 4. Build Checker
    cat > .claude/hooks/build-checker.sh << 'EOF'
#!/bin/bash
command -v jq &>/dev/null || exit 0
FILE=$(echo "$HOOK_INPUT" | jq -r '.tool_input.path // ""' 2>/dev/null)
[[ ! "$FILE" =~ \.(ts|tsx|js|jsx)$ ]] && exit 0
if [ -f "package.json" ] && [ -f "tsconfig.json" ]; then
    if command -v npx &>/dev/null; then
        echo "🔨 Type checking..." >&2
        npx tsc --noEmit 2>&1 | tail -3 >&2 || echo "⚠️ TS errors" >&2
    fi
fi
exit 0
EOF
    chmod +x .claude/hooks/build-checker.sh
    echo -e "${GREEN}✓${NC} build-checker.sh"
    
    # 5. Security Guard
    cat > .claude/hooks/security-guard.sh << 'EOF'
#!/bin/bash
command -v jq &>/dev/null || exit 0
CONTENT=$(echo "$HOOK_INPUT" | jq -r '.tool_input.content // .tool_input.file_text // .tool_input.new_str // ""' 2>/dev/null)
[ -z "$CONTENT" ] && exit 0
VIOLATIONS=()
echo "$CONTENT" | grep -iE '(password|api[_-]?key|secret)\s*[:=]\s*["\047][^"\047]{8,}' >/dev/null && VIOLATIONS+=("Hardcoded credential")
echo "$CONTENT" | grep -E 'AKIA[0-9A-Z]{16}' >/dev/null && VIOLATIONS+=("AWS key")
echo "$CONTENT" | grep -E '-----BEGIN.*PRIVATE KEY-----' >/dev/null && VIOLATIONS+=("Private key")
if [ ${#VIOLATIONS[@]} -gt 0 ]; then
    echo "🔒 SECURITY: ${VIOLATIONS[*]}" >&2
    exit 1
fi
exit 0
EOF
    chmod +x .claude/hooks/security-guard.sh
    echo -e "${GREEN}✓${NC} security-guard.sh"
    
    # 6. Audit Logger
    cat > .claude/hooks/audit-logger.sh << 'EOF'
#!/bin/bash
mkdir -p logs
AUDIT="logs/audit-$(date +%Y-%m).jsonl"
command -v jq &>/dev/null || exit 0
TOOL=$(echo "$HOOK_INPUT" | jq -r '.tool_name // "unknown"' 2>/dev/null)
[[ "$TOOL" == "View" ]] || [[ "$TOOL" == "Read" ]] && exit 0
FILE=$(echo "$HOOK_INPUT" | jq -r '.tool_input.path // "N/A"' 2>/dev/null)
echo "{\"ts\":\"$(date -Iseconds)\",\"tool\":\"$TOOL\",\"file\":\"$FILE\"}" >> "$AUDIT"
exit 0
EOF
    chmod +x .claude/hooks/audit-logger.sh
    echo -e "${GREEN}✓${NC} audit-logger.sh"
}

#===============================================================================
# SKILLS (9)
#===============================================================================

create_skills() {
    print_section "Creating Skills (9)"
    
    # 1. TypeScript Patterns
    mkdir -p .claude/skills/typescript-patterns
    cat > .claude/skills/typescript-patterns/SKILL.md << 'EOF'
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
EOF
    echo -e "${GREEN}✓${NC} typescript-patterns"
    
    # 2. React Patterns
    mkdir -p .claude/skills/react-patterns
    cat > .claude/skills/react-patterns/SKILL.md << 'EOF'
---
name: react-patterns
description: React 18+ patterns and hooks
---
# React Patterns

## Component Structure
```typescript
interface Props { label: string; onClick: () => void; disabled?: boolean; }
export function Button({ label, onClick, disabled = false }: Props) {
  return <button onClick={onClick} disabled={disabled}>{label}</button>;
}
```

## Custom Hook
```typescript
function useData<T>(url: string) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    fetch(url).then(r => r.json()).then(setData).finally(() => setLoading(false));
  }, [url]);
  return { data, loading };
}
```

## Performance
```typescript
const MemoComponent = memo(ExpensiveComponent);
const handleClick = useCallback(() => doSomething(id), [id]);
const sorted = useMemo(() => items.sort(), [items]);
```

## Best Practices
- ✅ Use functional components
- ✅ Clean up effects
- ❌ Don't mutate state directly
EOF
    echo -e "${GREEN}✓${NC} react-patterns"
    
    # 3. Testing Patterns
    mkdir -p .claude/skills/testing-patterns
    cat > .claude/skills/testing-patterns/SKILL.md << 'EOF'
---
name: testing-patterns
description: Jest, Vitest, Playwright testing
---
# Testing Patterns

## Unit Test
```typescript
describe('UserService', () => {
  it('should return user', async () => {
    const mockRepo = { findById: vi.fn().mockResolvedValue({ id: '1' }) };
    const service = new UserService(mockRepo);
    const result = await service.getUser('1');
    expect(result.id).toBe('1');
  });
});
```

## Component Test
```typescript
import { render, screen } from '@testing-library/react';
it('renders button', () => {
  render(<Button label="Click" onClick={() => {}} />);
  expect(screen.getByRole('button')).toHaveTextContent('Click');
});
```

## E2E (Playwright)
```typescript
test('login flow', async ({ page }) => {
  await page.goto('/login');
  await page.fill('[name="email"]', 'test@example.com');
  await page.click('button[type="submit"]');
  await expect(page).toHaveURL('/dashboard');
});
```

## Best Practices
- ✅ AAA pattern: Arrange, Act, Assert
- ✅ Test behavior, not implementation
- ❌ Don't share state between tests
EOF
    echo -e "${GREEN}✓${NC} testing-patterns"
    
    # 4. API Patterns
    mkdir -p .claude/skills/api-patterns
    cat > .claude/skills/api-patterns/SKILL.md << 'EOF'
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
EOF
    echo -e "${GREEN}✓${NC} api-patterns"
    
    # 5. Database Patterns
    mkdir -p .claude/skills/database-patterns
    cat > .claude/skills/database-patterns/SKILL.md << 'EOF'
---
name: database-patterns
description: Database design and queries
---
# Database Patterns

## Schema
```sql
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(255) UNIQUE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_users_email ON users(email);
```

## Queries
```typescript
// Parameterized (safe)
const user = await db.query('SELECT * FROM users WHERE email = $1', [email]);

// Pagination
const getUsers = (page: number, limit: number) =>
  db.query('SELECT * FROM users ORDER BY created_at DESC LIMIT $1 OFFSET $2',
    [limit, (page - 1) * limit]);
```

## Best Practices
- ✅ Use UUIDs for PKs
- ✅ Add indexes
- ✅ Use parameterized queries
- ❌ Never SELECT *
EOF
    echo -e "${GREEN}✓${NC} database-patterns"
    
    # 6. Supabase Patterns
    mkdir -p .claude/skills/supabase-patterns
    cat > .claude/skills/supabase-patterns/SKILL.md << 'EOF'
---
name: supabase-patterns
description: Supabase RLS, RPC, auth
---
# Supabase Patterns

## RLS Policies
```sql
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users view own" ON documents FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users insert own" ON documents FOR INSERT WITH CHECK (auth.uid() = user_id);
```

## RPC Function
```sql
CREATE FUNCTION insert_encrypted(p_data TEXT, p_key TEXT) RETURNS UUID AS $$
  INSERT INTO records (data) VALUES (pgp_sym_encrypt(p_data, p_key)) RETURNING id;
$$ LANGUAGE sql SECURITY DEFINER;
```

## Client
```typescript
const supabase = createBrowserClient(url, anonKey);
const { data } = await supabase.from('users').select('*').eq('id', userId);
```

## Best Practices
- ✅ Always enable RLS
- ✅ Use RPC for sensitive ops
- ❌ Never expose service key
EOF
    echo -e "${GREEN}✓${NC} supabase-patterns"
    
    # 7. Security First
    mkdir -p .claude/skills/security-first
    cat > .claude/skills/security-first/SKILL.md << 'EOF'
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
EOF
    echo -e "${GREEN}✓${NC} security-first"
    
    # 8. Deployment Patterns
    mkdir -p .claude/skills/deployment-patterns
    cat > .claude/skills/deployment-patterns/SKILL.md << 'EOF'
---
name: deployment-patterns
description: CI/CD and deployment
---
# Deployment Patterns

## GitHub Actions
```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
      - run: npm ci && npm test
```

## Dockerfile
```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine
COPY --from=builder /app/.next/standalone ./
EXPOSE 3000
CMD ["node", "server.js"]
```

## Best Practices
- ✅ Test before deploy
- ✅ Use environment vars
- ❌ Don't deploy without tests
EOF
    echo -e "${GREEN}✓${NC} deployment-patterns"
    
    # 9. Performance Patterns
    mkdir -p .claude/skills/performance-patterns
    cat > .claude/skills/performance-patterns/SKILL.md << 'EOF'
---
name: performance-patterns
description: Performance optimization
---
# Performance Patterns

## React Optimization
```typescript
const Heavy = lazy(() => import('./Heavy'));
<Suspense fallback={<Loading />}><Heavy /></Suspense>
```

## Caching
```typescript
const cache = new Map<string, { value: any; expiry: number }>();
function get(key: string) {
  const entry = cache.get(key);
  if (!entry || Date.now() > entry.expiry) return undefined;
  return entry.value;
}
```

## Database
```sql
EXPLAIN ANALYZE SELECT * FROM users WHERE email = $1;
CREATE INDEX CONCURRENTLY idx_email ON users(email);
```

## Best Practices
- ✅ Measure before optimizing
- ✅ Lazy load heavy components
- ✅ Use proper indexes
- ❌ Don't premature optimize
EOF
    echo -e "${GREEN}✓${NC} performance-patterns"
}

#===============================================================================
# COMMANDS (6)
#===============================================================================

create_commands() {
    print_section "Creating Commands (6)"
    
    cat > .claude/commands/deploy.md << 'EOF'
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
EOF
    echo -e "${GREEN}✓${NC} /deploy"
    
    cat > .claude/commands/security-audit.md << 'EOF'
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
EOF
    echo -e "${GREEN}✓${NC} /security-audit"
    
    cat > .claude/commands/cost-report.md << 'EOF'
---
name: cost-report
description: API cost report
---
# Cost Report
```bash
cat logs/tokens-$(date +%Y-%m-%d).jsonl | jq -s 'map(.cost) | add'
./tools/analyze-costs.sh
```
EOF
    echo -e "${GREEN}✓${NC} /cost-report"
    
    cat > .claude/commands/test.md << 'EOF'
---
name: test
description: Run tests
---
# Test
- All: `npm test`
- Coverage: `npm test -- --coverage`
- Watch: `npm test -- --watch`
- E2E: `npm run test:e2e`
EOF
    echo -e "${GREEN}✓${NC} /test"
    
    cat > .claude/commands/document.md << 'EOF'
---
name: document
description: Generate docs
---
# Document
Generate: Purpose, API, Examples, Edge cases
Use JSDoc format with @param, @returns, @example
EOF
    echo -e "${GREEN}✓${NC} /document"
    
    cat > .claude/commands/optimize.md << 'EOF'
---
name: optimize
description: Performance optimization
---
# Optimize
1. Bundle: `npx @next/bundle-analyzer`
2. Lighthouse audit
3. Lazy load components
4. Add DB indexes
5. Implement caching
EOF
    echo -e "${GREEN}✓${NC} /optimize"
}

#===============================================================================
# PROMPTS (5)
#===============================================================================

create_prompts() {
    print_section "Creating Prompts (5)"
    
    cat > .claude/prompts/constraint-stacking.md << 'EOF'
# Constraint Stacking
```
[Task] that must:
• Follow [constraint 1]
• Respect [constraint 2]
• Avoid [anti-pattern]
• Output in [format]
```
EOF
    echo -e "${GREEN}✓${NC} constraint-stacking"
    
    cat > .claude/prompts/reversal-prompts.md << 'EOF'
# Reversal Prompts
```
What could go wrong with [code]?
How would an attacker exploit this?
What edge cases break this?
```
EOF
    echo -e "${GREEN}✓${NC} reversal-prompts"
    
    cat > .claude/prompts/perspective-swap.md << 'EOF'
# Perspective Swap
```
As a [role], review [artifact] for [concerns]
```
Roles: User, Developer, Security, Ops, QA
EOF
    echo -e "${GREEN}✓${NC} perspective-swap"
    
    cat > .claude/prompts/scaffolding-prompts.md << 'EOF'
# Scaffolding
```
Build [feature] in stages:
1. Foundation
2. Core functionality
3. Advanced features
4. Polish
```
EOF
    echo -e "${GREEN}✓${NC} scaffolding-prompts"
    
    cat > .claude/prompts/high-resolution-objectives.md << 'EOF'
# High Resolution Objectives
```
[Task] that targets:
• [Specific audience]
• [Specific constraints]
• [Specific success criteria]
• [Specific format]
```
EOF
    echo -e "${GREEN}✓${NC} high-resolution-objectives"
}

#===============================================================================
# DEV DOCS (3)
#===============================================================================

create_dev_docs() {
    print_section "Creating Dev Docs (3)"
    
    cat > .dev-docs/plan.md << 'EOF'
# Feature Plan
## Current Feature
- **Name:** 
- **Goal:** 
- **Status:** Planning | In Progress | Done

## Scope
### In Scope
- 
### Out of Scope
- 

## Success Criteria
- [ ] 
EOF
    echo -e "${GREEN}✓${NC} plan.md"
    
    cat > .dev-docs/context.md << 'EOF'
# Project Context
## Architecture Overview

## Key Decisions
| Date | Decision | Rationale |
|------|----------|-----------|

## Learnings
- 
EOF
    echo -e "${GREEN}✓${NC} context.md"
    
    cat > .dev-docs/tasks.md << 'EOF'
# Tasks
## ✅ Completed

## 🚧 In Progress

## 📋 TODO

## 🐛 Known Issues

EOF
    echo -e "${GREEN}✓${NC} tasks.md"
}

#===============================================================================
# TOOLS (3)
#===============================================================================

create_tools() {
    print_section "Creating Tools (3)"
    
    cat > tools/analyze-costs.sh << 'EOF'
#!/bin/bash
echo "📊 Claude Code Cost Analysis"
echo "════════════════════════════"
TODAY=$(date +%Y-%m-%d)
if [ -f "logs/tokens-$TODAY.jsonl" ] && command -v jq &>/dev/null; then
    echo "Today:"
    cat "logs/tokens-$TODAY.jsonl" | jq -s '{requests: length, cost: (map(.cost) | add)}'
fi
echo ""
echo "This Week:"
cat logs/tokens-*.jsonl 2>/dev/null | jq -s 'group_by(.ts[:10]) | map({date: .[0].ts[:10], cost: (map(.cost)|add)}) | sort_by(.date) | reverse | .[:7]' 2>/dev/null || echo "No data"
EOF
    chmod +x tools/analyze-costs.sh
    echo -e "${GREEN}✓${NC} analyze-costs.sh"
    
    cat > tools/skill-tester.sh << 'EOF'
#!/bin/bash
echo "🧪 Skill Tester"
[ -z "$1" ] && echo "Usage: ./tools/skill-tester.sh \"prompt\"" && exit 0
command -v jq &>/dev/null || { echo "Install jq"; exit 1; }
echo "Testing: \"$1\""
jq -r --arg p "$1" '.rules[] | select(.keywords | any(. as $k | $p | test($k;"i"))) | "  ✓ \(.skill)"' .claude/skill-rules.json
EOF
    chmod +x tools/skill-tester.sh
    echo -e "${GREEN}✓${NC} skill-tester.sh"
    
    cat > tools/setup-project.sh << 'EOF'
#!/bin/bash
[ -z "$1" ] && echo "Usage: ./tools/setup-project.sh /path/to/project" && exit 1
echo "📦 Setting up: $1"
echo "Copy master setup script and run it in the target project"
EOF
    chmod +x tools/setup-project.sh
    echo -e "${GREEN}✓${NC} setup-project.sh"
}

#===============================================================================
# VERIFICATION & GITIGNORE
#===============================================================================

create_verification() {
    print_section "Creating Verification Script"
    
    cat > .claude/verify-setup.sh << 'EOF'
#!/bin/bash
echo "🔍 Verifying Claude Code Setup..."
echo ""
PASS=0; FAIL=0
check() { [ "$1" = "true" ] && echo -e "  \033[32m✓\033[0m $2" && ((PASS++)) || { echo -e "  \033[31m✗\033[0m $2"; ((FAIL++)); } }

echo "📁 Directories:"
check "$([ -d .claude ] && echo true)" ".claude/"
check "$([ -d .claude/hooks ] && echo true)" ".claude/hooks/"
check "$([ -d .claude/skills ] && echo true)" ".claude/skills/"
check "$([ -d .dev-docs ] && echo true)" ".dev-docs/"

echo ""
echo "📄 Config:"
check "$([ -f .claude/CLAUDE.md ] && echo true)" "CLAUDE.md"
check "$([ -f .claude/hooks.json ] && echo true)" "hooks.json"
check "$([ -f .claude/skill-rules.json ] && echo true)" "skill-rules.json"

echo ""
echo "🪝 Hooks (6):"
for h in cost-guard token-tracker skill-loader build-checker security-guard audit-logger; do
    check "$([ -f .claude/hooks/${h}.sh ] && [ -x .claude/hooks/${h}.sh ] && echo true)" "$h"
done

echo ""
echo "🎓 Skills (9):"
for s in typescript-patterns react-patterns testing-patterns api-patterns database-patterns supabase-patterns security-first deployment-patterns performance-patterns; do
    check "$([ -f .claude/skills/$s/SKILL.md ] && echo true)" "$s"
done

echo ""
echo "⚡ Commands (6):"
for c in deploy security-audit cost-report test document optimize; do
    check "$([ -f .claude/commands/$c.md ] && echo true)" "/$c"
done

echo ""
echo "════════════════════════════════════════"
echo "Results: $PASS passed, $FAIL failed"
[ $FAIL -eq 0 ] && echo -e "\033[32m✅ Setup complete!\033[0m" || echo -e "\033[31m⚠️ Issues found\033[0m"
EOF
    chmod +x .claude/verify-setup.sh
    echo -e "${GREEN}✓${NC} verify-setup.sh"
}

update_gitignore() {
    print_section "Updating .gitignore"
    
    ADDITIONS='
# Claude Code
logs/tokens-*.jsonl
logs/audit-*.jsonl
.claude/CLAUDE.local.md
'
    if [ -f ".gitignore" ]; then
        grep -q "# Claude Code" .gitignore || echo "$ADDITIONS" >> .gitignore
    else
        echo "$ADDITIONS" > .gitignore
    fi
    echo -e "${GREEN}✓${NC} .gitignore"
}

#===============================================================================
# MAIN
#===============================================================================

show_summary() {
    echo ""
    echo -e "${PURPLE}╔═══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${PURPLE}║     ✅ CLAUDE CODE MASTER SETUP COMPLETE!                     ║${NC}"
    echo -e "${PURPLE}╚═══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BLUE}📊 Installed:${NC}"
    echo "   Hooks (6):    cost-guard, token-tracker, skill-loader, build-checker, security-guard, audit-logger"
    echo "   Skills (9):   typescript, react, testing, api, database, supabase, security, deployment, performance"
    echo "   Commands (6): /deploy, /security-audit, /cost-report, /test, /document, /optimize"
    echo "   Prompts (5):  constraint-stacking, reversal, perspective-swap, scaffolding, high-resolution"
    echo ""
    echo -e "${YELLOW}📦 Add Domain Addons:${NC}"
    echo "   ./claude-code-addon-healthcare.sh      # Tidify, HIPAA"
    echo "   ./claude-code-addon-patient-portal.sh  # CareLink, Xero"
    echo "   ./claude-code-addon-fintech.sh         # CashKoda"
    echo "   ./claude-code-addon-edtech.sh          # SpiralSpeak"
    echo ""
    echo -e "${GREEN}🚀 Next Steps:${NC}"
    echo "   1. Verify:    ./.claude/verify-setup.sh"
    echo "   2. Customize: Edit .claude/CLAUDE.md"
    echo "   3. Test:      ./tools/skill-tester.sh \"your prompt\""
    echo "   4. Start:     claude"
    echo ""
}

main() {
    print_banner
    
    echo -e "${YELLOW}This installs:${NC}"
    echo "  • 6 Hooks • 9 Skills • 6 Commands • 5 Prompts • 3 Dev Docs • 3 Tools"
    echo ""
    echo -e "${CYAN}Project: ${PROJECT_NAME}${NC}"
    echo ""
    read -p "Continue? (y/n) " -n 1 -r
    echo
    [[ ! $REPLY =~ ^[Yy]$ ]] && echo "Aborted." && exit 1
    
    create_directories
    create_claude_md
    create_hooks_json
    create_skill_rules
    create_hooks
    create_skills
    create_commands
    create_prompts
    create_dev_docs
    create_tools
    create_verification
    update_gitignore
    
    echo ""
    ./.claude/verify-setup.sh
    
    show_summary
}

main "$@"

