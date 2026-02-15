#!/bin/bash
#===============================================================================
#
#   CLAUDE CODE INCREMENTAL UPDATE v2.1
#   Adds: Community Skills + HuggingFace Skills + Latest Insights
#
#===============================================================================
#
# RUN AFTER: claude-code-master-setup.sh
#
# ADDS:
#   ├── 4 HuggingFace Skills (llm-trainer, dataset-creator, model-evaluator, paper-publisher)
#   ├── 12 Community Skills (from ComposioHQ/awesome-claude-skills)
#   ├── 3 New Skill Rules
#   └── Updated CLAUDE.md with Agent SDK info
#
#===============================================================================

set -e

VERSION="2.1.0"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m'

echo -e "${PURPLE}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║     CLAUDE CODE INCREMENTAL UPDATE v${VERSION}                    ║"
echo "║     Community Skills + HuggingFace + Agent Insights           ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Pre-flight
if [ ! -d ".claude/skills" ]; then
    echo -e "${YELLOW}ERROR: Run claude-code-master-setup.sh first${NC}"
    exit 1
fi

echo -e "${YELLOW}Adding:${NC}"
echo "  • 4 HuggingFace Skills"
echo "  • 12 Community Skills"
echo "  • Agent SDK awareness"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo
[[ ! $REPLY =~ ^[Yy]$ ]] && exit 1

#===============================================================================
# HUGGINGFACE SKILLS (4)
#===============================================================================

echo ""
echo -e "${GREEN}━━━ HuggingFace Skills (4) ━━━${NC}"

# 1. HF LLM Trainer
mkdir -p .claude/skills/hf-llm-trainer
cat > .claude/skills/hf-llm-trainer/SKILL.md << 'EOF'
---
name: hf-llm-trainer
description: Fine-tune open-source LLMs on HuggingFace infrastructure
---
# HuggingFace LLM Trainer

## Overview
Teaches Claude to fine-tune open-source LLMs end-to-end using HuggingFace Jobs.

## Installation
```bash
/plugin install hf-llm-trainer@huggingface-skills
```

## Capabilities
- **Training Methods:** SFT, DPO, GRPO (used for DeepSeek R1)
- **Model Sizes:** 0.5B to 70B parameters
- **Output:** GGUF conversion for local deployment

## Hardware Mapping
| Model Size | Hardware | Method |
|------------|----------|--------|
| <1B | t4-small | Full fine-tune |
| 1-3B | t4-medium | Full or LoRA |
| 3-7B | a10g-large | LoRA recommended |
| 7B+ | a10g-large | LoRA required |

## Usage Examples
```
# Quick test run
Do a quick test run to SFT Qwen-0.6B with 100 examples of my-org/support-conversations

# Production training
SFT Qwen-0.6B for production on full dataset. Checkpoints every 500 steps, 3 epochs.

# Dataset validation
Check if my-org/conversation-data works for SFT training
```

## Dataset Validation Output
```
SFT: ✓ READY - Found 'messages' column
DPO: ✗ INCOMPATIBLE - Missing 'chosen'/'rejected' columns
```

## Best Practices
- ✅ Always run demo ($0.50) before production ($30+)
- ✅ Validate dataset format first
- ✅ Use LoRA for 7B+ models
- ❌ Don't skip test runs
EOF
echo -e "${GREEN}✓${NC} hf-llm-trainer"

# 2. HF Dataset Creator
mkdir -p .claude/skills/hf-dataset-creator
cat > .claude/skills/hf-dataset-creator/SKILL.md << 'EOF'
---
name: hf-dataset-creator
description: Create structured training datasets for HuggingFace
---
# HuggingFace Dataset Creator

## Overview
Prompts, templates, and scripts for creating structured training datasets.

## Dataset Formats

### SFT (Supervised Fine-Tuning)
```json
{
  "messages": [
    {"role": "user", "content": "Question"},
    {"role": "assistant", "content": "Answer"}
  ]
}
```

### DPO (Direct Preference Optimization)
```json
{
  "prompt": "Question",
  "chosen": "Better answer",
  "rejected": "Worse answer"
}
```

### GRPO (Group Relative Policy Optimization)
```json
{
  "prompt": "Question",
  "responses": ["Answer1", "Answer2", "Answer3"],
  "scores": [0.9, 0.7, 0.3]
}
```

## Usage
```
Create a SFT dataset from my customer support logs
Convert my CSV to DPO format for preference training
```

## Best Practices
- ✅ Include diverse examples
- ✅ Balance positive/negative cases
- ✅ Validate format before training
- ❌ Don't use < 100 examples
EOF
echo -e "${GREEN}✓${NC} hf-dataset-creator"

# 3. HF Model Evaluator
mkdir -p .claude/skills/hf-model-evaluator
cat > .claude/skills/hf-model-evaluator/SKILL.md << 'EOF'
---
name: hf-model-evaluator
description: Evaluate LLM performance and generate reports
---
# HuggingFace Model Evaluator

## Overview
Orchestrate evaluation jobs, generate reports, and map metrics.

## Evaluation Types
- **Accuracy:** Task completion rate
- **Perplexity:** Language model quality
- **BLEU/ROUGE:** Text generation quality
- **Custom:** Domain-specific metrics

## Usage
```
Evaluate my fine-tuned model against the base model
Run benchmark suite on my-org/custom-model
Generate comparison report for models A vs B
```

## Metrics Dashboard
```python
from evaluate import load
accuracy = load("accuracy")
results = accuracy.compute(predictions=preds, references=refs)
```

## Best Practices
- ✅ Use held-out test set
- ✅ Compare against baseline
- ✅ Track metrics over training
EOF
echo -e "${GREEN}✓${NC} hf-model-evaluator"

# 4. HF Paper Publisher
mkdir -p .claude/skills/hf-paper-publisher
cat > .claude/skills/hf-paper-publisher/SKILL.md << 'EOF'
---
name: hf-paper-publisher
description: Publish and manage research papers on HuggingFace Hub
---
# HuggingFace Paper Publisher

## Overview
Tools for publishing and managing research papers on HuggingFace Hub.

## Features
- Model cards with paper references
- Dataset documentation
- Arxiv integration
- Citation generation

## Usage
```
Create a model card for my fine-tuned model with paper citation
Generate BibTeX for my HuggingFace model
Link my arxiv paper to my model repository
```

## Model Card Template
```markdown
# Model Name
## Model Description
## Training Data
## Evaluation Results
## Citation
```
EOF
echo -e "${GREEN}✓${NC} hf-paper-publisher"

#===============================================================================
# COMMUNITY SKILLS - DEVELOPMENT (4)
#===============================================================================

echo ""
echo -e "${GREEN}━━━ Community Skills - Development (4) ━━━${NC}"

# 1. MCP Builder
mkdir -p .claude/skills/mcp-builder
cat > .claude/skills/mcp-builder/SKILL.md << 'EOF'
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
EOF
echo -e "${GREEN}✓${NC} mcp-builder"

# 2. Systematic Debugging
mkdir -p .claude/skills/systematic-debugging
cat > .claude/skills/systematic-debugging/SKILL.md << 'EOF'
---
name: systematic-debugging
description: Structured approach to debugging any issue
---
# Systematic Debugging

## When to Use
Before proposing fixes for any bug, test failure, or unexpected behavior.

## Debug Process
1. **Reproduce:** Confirm the issue exists
2. **Isolate:** Find minimal reproduction
3. **Hypothesize:** List possible causes
4. **Test:** Verify each hypothesis
5. **Fix:** Apply targeted solution
6. **Verify:** Confirm fix works
7. **Prevent:** Add test/guard

## Debug Checklist
```markdown
- [ ] Can I reproduce consistently?
- [ ] What changed recently?
- [ ] What are the error messages?
- [ ] What do the logs show?
- [ ] Is it environment-specific?
```

## Common Patterns
| Symptom | Check First |
|---------|-------------|
| Works locally, fails CI | Environment variables, dependencies |
| Intermittent failure | Race conditions, timing |
| Worked yesterday | Recent commits, dependency updates |
| Only in production | Config differences, data scale |
EOF
echo -e "${GREEN}✓${NC} systematic-debugging"

# 3. Test Driven Development
mkdir -p .claude/skills/test-driven-development
cat > .claude/skills/test-driven-development/SKILL.md << 'EOF'
---
name: test-driven-development
description: Write tests before implementation
---
# Test Driven Development

## When to Use
Before writing implementation code for any feature or bugfix.

## TDD Cycle
```
RED → GREEN → REFACTOR
```

1. **RED:** Write failing test
2. **GREEN:** Minimal code to pass
3. **REFACTOR:** Clean up, keep tests green

## Example Flow
```typescript
// 1. RED - Write test first
it('should calculate total with tax', () => {
  expect(calculateTotal(100, 0.1)).toBe(110);
});

// 2. GREEN - Make it pass
function calculateTotal(amount: number, taxRate: number): number {
  return amount * (1 + taxRate);
}

// 3. REFACTOR - Improve if needed
```

## Best Practices
- ✅ One assertion per test
- ✅ Descriptive test names
- ✅ Test edge cases
- ❌ Don't test implementation details
EOF
echo -e "${GREEN}✓${NC} test-driven-development"

# 4. Subagent Driven Development
mkdir -p .claude/skills/subagent-development
cat > .claude/skills/subagent-development/SKILL.md << 'EOF'
---
name: subagent-development
description: Dispatch independent subagents for parallel development
---
# Subagent Driven Development

## Overview
Dispatch independent subagents for individual tasks with code review checkpoints.

## When to Use
- Multiple independent features
- Large refactoring tasks
- Parallel workstreams

## Pattern
```
Main Agent
├── Subagent 1: Feature A
│   └── Checkpoint: Review
├── Subagent 2: Feature B
│   └── Checkpoint: Review
└── Integration: Merge all
```

## Implementation
```typescript
// Dispatch pattern
const tasks = [
  { name: "auth", prompt: "Implement auth module" },
  { name: "api", prompt: "Build API endpoints" },
  { name: "ui", prompt: "Create UI components" }
];

// Each runs independently, checkpoints for review
```

## Best Practices
- ✅ Clear task boundaries
- ✅ Review checkpoints between iterations
- ✅ Integration tests after merge
EOF
echo -e "${GREEN}✓${NC} subagent-development"

#===============================================================================
# COMMUNITY SKILLS - DATA & CONTENT (4)
#===============================================================================

echo ""
echo -e "${GREEN}━━━ Community Skills - Data & Content (4) ━━━${NC}"

# 1. CSV Data Summarizer
mkdir -p .claude/skills/csv-data-summarizer
cat > .claude/skills/csv-data-summarizer/SKILL.md << 'EOF'
---
name: csv-data-summarizer
description: Automatically analyze CSV files
---
# CSV Data Summarizer

## Overview
Automatically analyzes CSVs: columns, distributions, missing data, correlations.

## Analysis Output
```
Column Analysis:
- name: string (100% complete)
- age: numeric (mean: 34.5, std: 12.3, 2% missing)
- email: string (unique: 98%, 0% missing)

Correlations:
- age ↔ income: 0.72 (strong positive)

Missing Data:
- phone: 15% missing
- address: 8% missing
```

## Usage
```
Analyze this CSV and summarize the data quality
What columns have the most missing values?
Show me the distribution of the 'status' column
```

## Code Pattern
```python
import pandas as pd
df = pd.read_csv('data.csv')
print(df.describe())
print(df.isnull().sum())
print(df.dtypes)
```
EOF
echo -e "${GREEN}✓${NC} csv-data-summarizer"

# 2. Content Research Writer
mkdir -p .claude/skills/content-research-writer
cat > .claude/skills/content-research-writer/SKILL.md << 'EOF'
---
name: content-research-writer
description: Research-backed content creation with citations
---
# Content Research Writer

## Overview
Write high-quality content with research, citations, and iterative feedback.

## Process
1. **Research:** Gather sources
2. **Outline:** Structure content
3. **Draft:** Write sections
4. **Cite:** Add references
5. **Polish:** Improve hooks, flow

## Content Structure
```markdown
# Title (Hook)

## Introduction (Problem + Promise)

## Section 1 (Key Point)
[Supporting evidence + citation]

## Section 2 (Key Point)
[Supporting evidence + citation]

## Conclusion (Summary + CTA)

## References
```

## Best Practices
- ✅ Cite credible sources
- ✅ Strong opening hook
- ✅ Clear structure
- ❌ Don't make unsupported claims
EOF
echo -e "${GREEN}✓${NC} content-research-writer"

# 3. YouTube Transcript
mkdir -p .claude/skills/youtube-transcript
cat > .claude/skills/youtube-transcript/SKILL.md << 'EOF'
---
name: youtube-transcript
description: Fetch and summarize YouTube video transcripts
---
# YouTube Transcript

## Overview
Fetch transcripts from YouTube videos for summarization and analysis.

## Usage
```
Get the transcript from this YouTube video: [URL]
Summarize the key points from this video
Extract action items from this tutorial
```

## Tools
```bash
# yt-dlp for transcripts
yt-dlp --write-auto-sub --sub-lang en --skip-download [URL]

# Or use API
youtube-transcript-api [VIDEO_ID]
```

## Output Format
```
[00:00] Introduction
[02:30] Key Point 1
[05:45] Key Point 2
[10:00] Conclusion

Summary: [Brief overview]
Key Takeaways:
1. [Point 1]
2. [Point 2]
```
EOF
echo -e "${GREEN}✓${NC} youtube-transcript"

# 4. Article Extractor
mkdir -p .claude/skills/article-extractor
cat > .claude/skills/article-extractor/SKILL.md << 'EOF'
---
name: article-extractor
description: Extract full article text and metadata from web pages
---
# Article Extractor

## Overview
Extract clean article text, metadata, and key information from web pages.

## Extracted Data
- Title
- Author
- Publication date
- Main content (cleaned)
- Images
- Related links

## Usage
```
Extract the article from this URL
Get the main content without ads/navigation
Summarize this news article
```

## Tools
```python
from newspaper import Article

article = Article(url)
article.download()
article.parse()

print(article.title)
print(article.text)
print(article.authors)
print(article.publish_date)
```
EOF
echo -e "${GREEN}✓${NC} article-extractor"

#===============================================================================
# COMMUNITY SKILLS - PRODUCTIVITY (4)
#===============================================================================

echo ""
echo -e "${GREEN}━━━ Community Skills - Productivity (4) ━━━${NC}"

# 1. File Organizer
mkdir -p .claude/skills/file-organizer
cat > .claude/skills/file-organizer/SKILL.md << 'EOF'
---
name: file-organizer
description: Intelligently organize files and folders
---
# File Organizer

## Overview
Intelligently organizes files and folders across your computer.

## Organization Patterns
```
Downloads/
├── Documents/
│   ├── PDFs/
│   ├── Spreadsheets/
│   └── Presentations/
├── Images/
│   ├── Screenshots/
│   └── Photos/
├── Code/
│   └── [by language]
└── Archives/
    └── [by date]
```

## Usage
```
Organize my Downloads folder by file type
Sort these files by date
Move old files to archive
```

## Script Pattern
```bash
# Organize by extension
for ext in pdf docx xlsx png jpg; do
  mkdir -p "$ext"
  mv *.$ext "$ext/" 2>/dev/null
done
```
EOF
echo -e "${GREEN}✓${NC} file-organizer"

# 2. Meeting Insights Analyzer
mkdir -p .claude/skills/meeting-insights
cat > .claude/skills/meeting-insights/SKILL.md << 'EOF'
---
name: meeting-insights
description: Transform meeting transcripts into actionable insights
---
# Meeting Insights Analyzer

## Overview
Transforms meeting transcripts into actionable insights about communication patterns.

## Analysis Output
```
MEETING SUMMARY
- Duration: 45 min
- Participants: 5
- Decisions: 3
- Action Items: 7

KEY DECISIONS
1. [Decision with context]
2. [Decision with context]

ACTION ITEMS
- [ ] @person: Task (due: date)
- [ ] @person: Task (due: date)

FOLLOW-UPS NEEDED
- Topic requiring clarification
```

## Usage
```
Analyze this meeting transcript
Extract action items from our standup
What decisions were made in this meeting?
```
EOF
echo -e "${GREEN}✓${NC} meeting-insights"

# 3. Invoice Organizer
mkdir -p .claude/skills/invoice-organizer
cat > .claude/skills/invoice-organizer/SKILL.md << 'EOF'
---
name: invoice-organizer
description: Organize invoices and receipts for tax preparation
---
# Invoice Organizer

## Overview
Automatically organizes invoices and receipts for tax preparation.

## Organization Structure
```
Finances/
├── 2025/
│   ├── Q1/
│   │   ├── Income/
│   │   └── Expenses/
│   │       ├── Software/
│   │       ├── Hardware/
│   │       └── Services/
│   ├── Q2/
│   └── ...
└── Summary.xlsx
```

## Extracted Data
- Vendor name
- Date
- Amount
- Category
- Tax deductible (Y/N)

## Usage
```
Organize these receipts by quarter
Categorize my business expenses
Generate tax summary for 2025
```
EOF
echo -e "${GREEN}✓${NC} invoice-organizer"

# 4. Git Worktrees
mkdir -p .claude/skills/git-worktrees
cat > .claude/skills/git-worktrees/SKILL.md << 'EOF'
---
name: git-worktrees
description: Manage isolated git worktrees for parallel development
---
# Git Worktrees

## Overview
Creates isolated git worktrees for parallel development on multiple branches.

## Commands
```bash
# Create worktree
git worktree add ../feature-x feature-x

# List worktrees
git worktree list

# Remove worktree
git worktree remove ../feature-x
```

## Use Cases
- Work on multiple features simultaneously
- Test changes without stashing
- Review PRs while coding
- Parallel Claude Code sessions

## Structure
```
project/
├── main/           # Main worktree
├── feature-a/      # Feature A worktree
└── feature-b/      # Feature B worktree
```

## Best Practices
- ✅ Use descriptive directory names
- ✅ Clean up after merging
- ✅ Each worktree = separate terminal
EOF
echo -e "${GREEN}✓${NC} git-worktrees"

#===============================================================================
# AGENT SDK AWARENESS
#===============================================================================

echo ""
echo -e "${GREEN}━━━ Adding Agent SDK Awareness ━━━${NC}"

mkdir -p .claude/skills/claude-agent-sdk
cat > .claude/skills/claude-agent-sdk/SKILL.md << 'EOF'
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
EOF
echo -e "${GREEN}✓${NC} claude-agent-sdk"

#===============================================================================
# UPDATE SKILL RULES
#===============================================================================

echo ""
echo -e "${GREEN}━━━ Updating Skill Rules ━━━${NC}"

if [ -f ".claude/skill-rules.json" ] && command -v jq &>/dev/null; then
    jq '.rules += [
        {"skill": "hf-llm-trainer", "keywords": ["fine-tune", "fine-tuning", "training", "SFT", "DPO", "GRPO", "LoRA", "huggingface"]},
        {"skill": "hf-dataset-creator", "keywords": ["dataset", "training data", "create dataset", "data format"]},
        {"skill": "mcp-builder", "keywords": ["MCP", "model context protocol", "mcp server", "tool server"]},
        {"skill": "systematic-debugging", "keywords": ["debug", "bug", "error", "failing", "broken", "not working"]},
        {"skill": "test-driven-development", "keywords": ["TDD", "test first", "red green refactor"]},
        {"skill": "csv-data-summarizer", "keywords": ["CSV", "analyze data", "data quality", "missing values"]},
        {"skill": "claude-agent-sdk", "keywords": ["agent", "agent SDK", "autonomous", "long running", "multi-step"]}
    ]' .claude/skill-rules.json > .claude/skill-rules.json.tmp && mv .claude/skill-rules.json.tmp .claude/skill-rules.json
    echo -e "${GREEN}✓${NC} Added 7 new skill rules"
fi

#===============================================================================
# UPDATE CLAUDE.md
#===============================================================================

echo ""
echo -e "${GREEN}━━━ Updating CLAUDE.md ━━━${NC}"

if [ -f ".claude/CLAUDE.md" ]; then
    cat >> .claude/CLAUDE.md << 'EOF'

---

## v2.1 Update: Community & HuggingFace Skills

### HuggingFace Skills
- `hf-llm-trainer` - Fine-tune LLMs (SFT, DPO, GRPO)
- `hf-dataset-creator` - Create training datasets
- `hf-model-evaluator` - Evaluate model performance
- `hf-paper-publisher` - Publish to HF Hub

### Community Skills (Development)
- `mcp-builder` - Build MCP servers
- `systematic-debugging` - Structured debugging
- `test-driven-development` - TDD workflow
- `subagent-development` - Parallel agent tasks

### Community Skills (Data & Content)
- `csv-data-summarizer` - Analyze CSV files
- `content-research-writer` - Research-backed writing
- `youtube-transcript` - Video transcripts
- `article-extractor` - Web article extraction

### Community Skills (Productivity)
- `file-organizer` - Organize files
- `meeting-insights` - Meeting analysis
- `invoice-organizer` - Tax prep
- `git-worktrees` - Parallel development

### Agent Development
- `claude-agent-sdk` - Build production agents

### Key Insight (Dec 2025)
"Opus 4.5 is the unlock for agents" - McKay Wrigley
- Claude Code + Opus 4.5 = best AI coding tool
- Agent SDK = world-class agentic harness
- Reliable on longer time horizons (hours, not minutes)
EOF
    echo -e "${GREEN}✓${NC} Updated CLAUDE.md"
fi

#===============================================================================
# SUMMARY
#===============================================================================

echo ""
echo -e "${PURPLE}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${PURPLE}║     ✅ INCREMENTAL UPDATE v2.1 COMPLETE!                      ║${NC}"
echo -e "${PURPLE}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}📊 Added:${NC}"
echo ""
echo "  HuggingFace Skills (4):"
echo "    hf-llm-trainer, hf-dataset-creator, hf-model-evaluator, hf-paper-publisher"
echo ""
echo "  Community Skills - Development (4):"
echo "    mcp-builder, systematic-debugging, test-driven-development, subagent-development"
echo ""
echo "  Community Skills - Data & Content (4):"
echo "    csv-data-summarizer, content-research-writer, youtube-transcript, article-extractor"
echo ""
echo "  Community Skills - Productivity (4):"
echo "    file-organizer, meeting-insights, invoice-organizer, git-worktrees"
echo ""
echo "  Agent Awareness (1):"
echo "    claude-agent-sdk"
echo ""
echo -e "${YELLOW}📈 Total Skills After Update:${NC}"
echo "    Base: 9 + HuggingFace: 4 + Community: 12 + Agent: 1 = 26 skills"
echo ""
echo -e "${GREEN}🎯 New Auto-Triggers:${NC}"
echo "    'fine-tune', 'debug', 'TDD', 'CSV', 'agent' → Load relevant skills"
echo ""

