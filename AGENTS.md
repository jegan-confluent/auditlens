# AGENTS.md

This repository uses a lightweight repo-local session memory workflow for Codex.

## Git commit rules

- NEVER add Co-Authored-By lines to any commit message
- NEVER add co-author attribution of any kind
- NEVER mention Claude, AI, or any tool in commit messages
- Commit messages must be written as if authored solely by the developer

## Core Working Rules

- Work in the `AuditLens` repository only.
- Preserve the current foundation architecture:
  - Kafka-native ingestion
  - canonical topics
  - centralized normalization and classification
  - single-instance product model
- Do not introduce Flink, Tableflow, MCP-first workflows, HA coordination, or distributed storage unless the user explicitly asks for them.
- Prefer cleanup and explicit contracts over adding parallel architecture paths.

## Coding Constraints

- Keep changes practical and repo-local.
- Prefer small scripts and docs over large frameworks.
- Do not silently rewrite historical records or prior changelog entries.
- Before editing, inspect current repo state and unresolved work.
- Before claiming completion, run practical validation for the files you touched.

## Testing-First Stop Point

- Stop after implementation reaches a testable state.
- Report what changed, what was validated, what still needs testing, and what remains intentionally deferred.
- Do not continue into adjacent feature work unless the user asks.

## Session Start Workflow

At the beginning of every future session:

1. Read `CHANGELOG.md`.
2. Run `scripts/session_start.sh`.
3. Review:
   - last recorded session summary
   - carried-forward known issues
   - `git status --short`
   - `git log -5 --oneline`
4. Summarize the current repo state in plain English.
5. Stop and ask the user what to work on next before editing files.

## Session End Workflow

Before ending any future session:

1. Run `scripts/session_end_draft.sh`.
2. Show the generated draft to the user.
3. Ask exactly:
   `Here is the session summary I will append to CHANGELOG.md. Confirm? YES / edit it`
4. Append only after confirmation using `scripts/append_changelog_entry.sh <draft-file>`.
5. Never rewrite previous `CHANGELOG.md` entries.

## Changelog Rules

- `CHANGELOG.md` is append-only for session memory.
- New session entries must use this structure:

```md
## [DATE] Session [N]

### Fixed
- [what was broken] -> [what it does now]
  Why: [impact]
  Files: [exact paths]

### Added
- [what was built]
  Why: [problem it solves]
  Files: [exact paths]

### Removed
- [what was deleted, if any]
  Why: [why safe to remove]
  Files: [exact paths]

### Architecture Decisions
- [decisions made]
  Why: [reasoning]
  Impact: [what this affects going forward]

### Known Issues / Not Done
- [anything deferred]
  Why deferred: [reason]
```

## Helper Files

- `scripts/session_start.sh`
- `scripts/session_end_draft.sh`
- `scripts/append_changelog_entry.sh`
- `docs/SESSION_MEMORY_WORKFLOW.md`

Use these instead of inventing a new workflow per session.
