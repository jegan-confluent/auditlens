# Project: AuditLens (audit-forwarder)

## Quick Context
Confluent Audit Log Intelligence System - consumes audit events from Confluent Cloud, classifies by criticality, routes to dedicated topics, and visualizes in real-time dashboard.

## Tech Stack
- **Backend:** Python 3.9+, confluent-kafka, orjson
- **Dashboard:** Streamlit, Pandas
- **Monitoring:** Prometheus, Grafana, Loki
- **Deployment:** Docker Compose

## Quick Commands
```bash
./scripts/setup.sh        # Full setup
./scripts/verify.sh       # Health check
docker logs -f audit-forwarder  # View logs
```

## Project Structure
```
src/
├── classification/   # Event criticality
├── routing/          # Multi-topic routing
├── anomaly/          # Rate-based detection
├── alerting/         # Webhook integration
├── aggregation/      # Denial aggregation
├── metrics/          # Prometheus metrics
├── secrets/          # Multi-backend secrets
└── config/           # Pydantic validation
dashboard/
├── data/             # Kafka consumer, transforms
├── components/       # Reusable UI
└── tabs/             # 10 specialized views
```

## Critical Rules
1. Never hardcode secrets - use env vars or secrets manager
2. Use conventional commits
3. Run verify.sh before committing

## Communication Rules
4. Give direct answers, not explanations of "normal behavior"
5. When user corrects you, fix immediately - don't defend wrong approach
6. User has deep domain expertise - don't explain basics, just solve problems
7. When user approves a plan, execute ALL items without asking for confirmation on each
8. Use parallel agents (Task tool) for independent tasks to reduce total time
9. Track progress with TodoWrite for multi-step implementations
10. Use tables for comparison and summary - include "Winner" column when comparing options
11. Provide testing checklists with checkboxes for UI features

## Audit Log Rules
12. Never filter out service account entries - they represent applications
13. Audit log fields vary by event type - check multiple paths (request vs requestMetadata)
14. Critical security fields: principal, clientId, clientIp, resourceName
15. CRN IDs can be in source, resourceName, or subject - check all three
16. mds.Authorize denials are routine RBAC checks (MEDIUM), not security events (CRITICAL)
17. DROP_LOW_EVENTS saves ~89% storage - LOW events are routine and rarely investigated

## Security Patterns
18. Never allow default passwords in docker-compose (use ${VAR:?error} syntax)
19. Run containers as non-root where possible (user: "uid:gid")
20. Use hmac.compare_digest() for constant-time token comparison
21. Defense-in-depth: non-root + network segmentation + secrets management

## Performance Patterns
22. Use orjson instead of json module (2-3x faster parsing)
23. Use cachetools.LRUCache for bounded caching (prevent memory leaks)
24. Use tenacity for retry with exponential backoff on external calls
25. Batch operations: 5000 messages per consume, flush offsets per batch; for cross-region Kafka use 30s socket timeout, 45s session timeout

## Documentation Patterns
26. Create END_TO_END_FLOW.md explaining "why" not just "what"
27. When explaining architecture, provide ASCII diagrams FIRST, then details
28. Include tables for configuration reference and decision rationale

## Testing & Verification Rules
29. Always verify changes work before reporting completion - use browser tools if available, check logs otherwise
30. When refactoring files, compare against original to catch missing features
31. Create testing checklists for UI changes so user can systematically verify
32. Bump version number when making user-facing changes (dashboard, API)

## Streamlit Dashboard Patterns
33. Use session_state for runtime configuration (theme, filters) over config constants
34. Use type checking in formatting: isinstance(value, (int, float)) before f"{value:,}"
35. Tabs receive filtered df only - don't reference variables from parent scope
36. For nested JSON config, support both new and legacy flat formats

## Architecture & Comparison Rules
37. For technology comparisons, always include: cost, security, performance, retention
38. Include "Winner" column in comparison tables to make recommendations clear
39. Provide one-liner summaries for quick stakeholder communication
40. When comparing managed services, consider data residency and control implications
41. Recommend hybrid approaches when "both" beats "either/or" (e.g., real-time + historical)

## Debugging Patterns
42. Dashboard zero-data: check in order (1) Kafka timeouts, (2) transform functions returning None, (3) filters removing all data
43. Python functions without explicit return statement return None - always verify function bodies are complete
44. Streamlit `@st.cache_data` can cache empty DataFrames; add `st.cache_data.clear()` on auto-refresh
45. UUID regex in "internal event" filters will match org IDs in resourceName - be careful with default=True
46. Cross-region Kafka: network latency is the bottleneck, not local CPU/memory (US West → AP South = 30s+ timeouts needed)
47. Test data loading with `docker exec <container> python3 -c "..."` before debugging UI layer
48. Add debug logging at data transformation boundaries to trace where data disappears

## Current State (Dec 19, 2025)

### Running Services
- **Forwarder**: audit-forwarder:v2.2.0 on port 8003
- **Dashboard**: audit-dashboard:v10.19 on port 8503
- **Monitoring**: Prometheus :9090, Grafana :3000
- **Network**: audit-network

### Dashboard v10.19 Features
- Theme toggle (Pastel/Clean/Professional)
- Filter presets (save/load combinations)
- PDF compliance report export (fpdf2)
- Clickable metric cards for quick filtering
- Activity heatmap (day × hour) in Time Insights
- Keyboard shortcuts (R to refresh)
- Cluster/Environment sidebar filters
- 10 tabs + modular architecture (480 lines main)
- Non-blocking auto-refresh (st_autorefresh)
- Static consumer group (no more group explosion)
- orjson for 2x faster JSON parsing

### Forwarder v2.2.0 Features
- Multi-topic routing (CRITICAL/HIGH/MEDIUM/LOW)
- Security Alerts aggregation (denial patterns)
- Secrets management (6 backends)
- Metrics endpoint with auth
- Webhook retry with tenacity
- Non-root containers
- acks=all + idempotence (zero data loss)
- Dead Letter Queue for failed events (`ENABLE_DLQ`, `DLQ_TOPIC`)
- Bounded LRU offset cache (memory safe)

### AWS Fargate Deployment (NEW)
- Complete Terraform configuration in `deploy/terraform/aws/`
- VPC, ECR, ECS, ALB, Secrets Manager, CloudWatch
- Estimated cost: ~$88/month
- Ready to apply: `terraform init && terraform apply`

### Key Files
- `audit_forwarder.py` - Main forwarder
- `dashboard/app.py` - Dashboard entry point
- `docs/END_TO_END_FLOW.md` - Technical architecture
- `docs/DLQ_API.md` - Dead Letter Queue documentation
- `FEATURES.md` - Complete feature list
- `CHANGELOG.md` - Version history
- `GETTING_STARTED.md` - Setup guide
- `.env` / `.secrets` - Configuration

### To Continue
```bash
./scripts/verify.sh           # Check health
open http://localhost:8503    # Dashboard
docker logs -f audit-forwarder  # Logs
curl http://localhost:8003/health | jq  # Health check

# Deploy to AWS Fargate
cd deploy/terraform/aws
terraform init && terraform apply
```

## Skills Available
Base: typescript-patterns, react-patterns, testing-patterns, api-patterns, database-patterns
Extended: supabase-patterns, security-first, deployment-patterns, performance-patterns

---
Last Updated: 2025-12-19

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

---

## Claude Diary System

### Memory Commands
- `/diary` - Capture session learnings after significant work
- `/reflect` - Analyze diary entries, propose CLAUDE.md updates
- `/digest` - Generate weekly work summary

### Memory Flow
```
Session → /diary → Entry → /reflect → CLAUDE.md Update
```

### Diary Location
- Entries: `.claude/diary/entries/`
- Reflections: `.claude/diary/reflections/`
- Archive: `.claude/diary/archive/`

### When to Use /diary
- After implementing significant features
- After solving complex bugs
- After receiving user feedback
- When PreCompact triggers (long sessions)

### When to Use /reflect
- Weekly (recommended)
- After 5+ diary entries accumulate
- Before starting new project phase
