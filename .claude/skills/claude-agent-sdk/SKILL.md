---
name: claude-agent-sdk
description: Build production agents with Claude Agent SDK
---
# Claude Agent SDK

## Overview
The Claude Agent SDK is a world-class agentic harness for building production agents.
Per McKay Wrigley: "An agent's harness matters almost as much as its model."

## Key Features
- **Long Time Horizons:** Opus 4.5 + SDK enables reliable multi-hour agent tasks
- **Tool Orchestration:** Built-in tool management
- **Error Recovery:** Automatic retry and recovery
- **Checkpoints:** State management for long tasks

## Installation
```bash
pip install anthropic[agent]
# or
npm install @anthropic-ai/agent-sdk
```

## Basic Agent
```python
from anthropic.agent import Agent

agent = Agent(
    model="claude-opus-4-5-20251101",
    tools=[...],
    system="You are a helpful assistant"
)

result = await agent.run("Complete this task")
```

## Claude Code Integration
- **Terminal:** `claude` command
- **Desktop:** Claude Code Desktop (GUI option)
- **AskUserQuestion:** Interactive prompts during execution

## Best Practices
- ✅ Use Opus 4.5 for complex agent tasks
- ✅ Define clear success criteria
- ✅ Add checkpoints for long tasks
- ✅ Handle errors gracefully
- ❌ Don't skip testing with shorter tasks first

## Pricing (Opus 4.5)
- Input: $5 / 1M tokens
- Output: $25 / 1M tokens
- 1/3 cost of Opus 4 with better performance
