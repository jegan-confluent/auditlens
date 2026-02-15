---
name: dev-browser
description: "Browser automation that lets Claude see and control your web browser. Use when testing UI, debugging frontend, verifying changes, or when you need Claude to interact with a running web app. Much more efficient than Playwright MCP."
allowed-tools: "Bash,Read,Write"
version: 1.0.0
---

# Dev Browser

Let Claude see and control your web browser for testing, debugging, and visual verification.

## When to Use This Skill

- Testing your running web application
- Debugging UI issues visually
- Verifying frontend changes work
- Filling forms, clicking buttons, navigating pages
- Iterating on design until it looks right
- Any task where Claude needs to "see" a browser

## Prerequisites

**1. Install Bun runtime:**
```bash
curl -fsSL https://bun.sh/install | bash
```

**2. Install the Dev Browser plugin in Claude Code:**
```bash
/plugin marketplace add sawyerhood/dev-browser
/plugin install dev-browser@sawyerhood/dev-browser
```

**3. Restart Claude Code**

## How It Works

Dev Browser runs a **persistent Playwright server** that maintains browser state across script executions:

- **Pages stay alive** - Navigate once, interact across multiple scripts
- **Stateful** - Forms stay filled, sessions persist
- **Codebase-aware** - Claude looks at your actual code to inform debugging
- **LLM-friendly** - Structured DOM snapshots optimized for AI

## Usage Examples

### Test Your App
```
"Open localhost:3000 and create an account to verify the signup flow"
```

### Debug UI Issues
```
"Go to the settings page and figure out why the save button isn't working"
```

### Iterate on Design
```
"Use dev-browser to check the landing page, then improve the styling until it looks professional"
```

### Verify Changes
```
"I just updated the checkout form - open the cart page and test it"
```

## Why Dev Browser Over Alternatives

| Approach | Time | Cost | Context Efficiency |
|----------|------|------|-------------------|
| **Dev Browser** | 3m 53s | $0.88 | Best |
| Playwright MCP | 4m 31s | $1.45 | Burns context |
| Playwright Skill | 8m 07s | $1.45 | Medium |

- **14% faster** than Playwright MCP
- **39% cheaper** than alternatives
- **43% fewer turns** needed

## Combining with Other Skills

Dev Browser works great with:
- `frontend-design` - Design then verify visually
- `webapp-testing` - Automated + visual testing
- `root-cause-tracing` - Debug with visual confirmation

## Troubleshooting

### Plugin not working?
1. Ensure Bun is installed: `bun --version`
2. Restart Claude Code after plugin install
3. Check plugin is enabled: `/plugin list`

### Browser not opening?
- Make sure no other Playwright instances are running
- Try: `pkill -f playwright`

## Resources

- GitHub: https://github.com/SawyerHood/dev-browser
- Author: Sawyer Hood
