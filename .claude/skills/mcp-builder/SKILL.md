---
name: mcp-builder
description: Build Model Context Protocol servers and tools
---
# MCP Builder

## Overview
Create custom MCP servers for Claude integrations.

## MCP Server Structure
```typescript
import { Server } from "@modelcontextprotocol/sdk/server";

const server = new Server({
  name: "my-mcp-server",
  version: "1.0.0"
}, {
  capabilities: { tools: {} }
});

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [{
    name: "my_tool",
    description: "What it does",
    inputSchema: { type: "object", properties: {} }
  }]
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  if (request.params.name === "my_tool") {
    return { content: [{ type: "text", text: "Result" }] };
  }
});
```

## Installation
```bash
claude mcp add my-server -- node /path/to/server.js
```

## Best Practices
- ✅ Clear tool descriptions
- ✅ Proper error handling
- ✅ Input validation
