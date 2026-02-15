---
name: mcp-builder
description: "Guide for creating high-quality MCP (Model Context Protocol) servers for integrating external APIs and services with LLMs. Use when building Claude integrations, API connectors, or tool servers."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# MCP Builder

Create MCP servers to extend Claude's capabilities with external tools and APIs.

## When to Use This Skill

- User wants to "connect Claude to X"
- Building API integrations
- Creating custom tools for Claude
- User asks about MCP servers
- Extending Claude Code capabilities

## What is MCP?

Model Context Protocol (MCP) is a standard for connecting LLMs to external tools and data sources. An MCP server exposes:
- **Tools**: Functions Claude can call
- **Resources**: Data Claude can read
- **Prompts**: Pre-built prompt templates

## MCP Server Structure

```
my-mcp-server/
├── src/
│   └── index.ts          # Server implementation
├── package.json
├── tsconfig.json
└── README.md
```

## Basic Server Template (TypeScript)

```typescript
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const server = new Server(
  {
    name: "my-mcp-server",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// Define available tools
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "my_tool",
      description: "Does something useful",
      inputSchema: {
        type: "object",
        properties: {
          param1: {
            type: "string",
            description: "First parameter",
          },
        },
        required: ["param1"],
      },
    },
  ],
}));

// Handle tool calls
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  if (name === "my_tool") {
    const result = await doSomething(args.param1);
    return {
      content: [{ type: "text", text: JSON.stringify(result) }],
    };
  }

  throw new Error(`Unknown tool: ${name}`);
});

// Start server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch(console.error);
```

## package.json

```json
{
  "name": "my-mcp-server",
  "version": "1.0.0",
  "type": "module",
  "main": "dist/index.js",
  "scripts": {
    "build": "tsc",
    "start": "node dist/index.js"
  },
  "dependencies": {
    "@modelcontextprotocol/sdk": "^1.0.0"
  },
  "devDependencies": {
    "typescript": "^5.0.0"
  }
}
```

## tsconfig.json

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "outDir": "dist",
    "strict": true,
    "esModuleInterop": true
  },
  "include": ["src/**/*"]
}
```

## Registering with Claude Code

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "my-server": {
      "command": "node",
      "args": ["/path/to/my-mcp-server/dist/index.js"],
      "env": {
        "API_KEY": "your-key"
      }
    }
  }
}
```

## Best Practices

### Tool Design
- Clear, descriptive names (snake_case)
- Comprehensive descriptions
- Validate all inputs
- Return structured data
- Handle errors gracefully

### Security
- Never hardcode secrets
- Validate external inputs
- Limit scope of operations
- Log access appropriately

### Performance
- Implement timeouts
- Cache when appropriate
- Batch operations
- Handle rate limits

## Example: GitHub Integration

```typescript
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "create_issue",
      description: "Create a GitHub issue",
      inputSchema: {
        type: "object",
        properties: {
          repo: { type: "string", description: "owner/repo" },
          title: { type: "string", description: "Issue title" },
          body: { type: "string", description: "Issue body" },
        },
        required: ["repo", "title"],
      },
    },
    {
      name: "list_prs",
      description: "List pull requests",
      inputSchema: {
        type: "object",
        properties: {
          repo: { type: "string" },
          state: { type: "string", enum: ["open", "closed", "all"] },
        },
        required: ["repo"],
      },
    },
  ],
}));
```

## Testing Your Server

```bash
# Build
npm run build

# Test with MCP inspector
npx @modelcontextprotocol/inspector dist/index.js

# Or test in Claude Code
# Add to settings.json and restart Claude Code
```

## Common MCP Servers

| Server | Purpose |
|--------|---------|
| github | GitHub operations |
| slack | Slack messaging |
| postgres | Database queries |
| filesystem | File operations |
| brave-search | Web search |
| puppeteer | Browser automation |
