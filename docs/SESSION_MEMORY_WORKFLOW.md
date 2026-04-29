# Session Memory Workflow

This repository keeps session memory local with:

- `AGENTS.md` for Codex instructions
- `CHANGELOG.md` as the append-only session log
- small helper scripts in `scripts/`

## Start of Session

Run:

```bash
./scripts/session_start.sh
```

What it does:

- reads the most recent session entry from `CHANGELOG.md` if present
- extracts the last session number and date
- extracts the first `Fixed`, `Added`, and `Known Issues / Not Done` bullets
- shows `git log -5 --oneline`
- shows `git status --short`
- runs a lightweight Python compile check when the core forwarder files exist
- prints a plain-English session brief and stops

Expected Codex behavior:

1. Read the brief
2. Summarize the current state for the user
3. Ask what to work on next before editing

## End of Session

Run:

```bash
./scripts/session_end_draft.sh > /tmp/auditlens-session-draft.md
```

Review the draft, then show it to the user and ask:

```text
Here is the session summary I will append to CHANGELOG.md. Confirm? YES / edit it
```

Only after confirmation:

```bash
./scripts/append_changelog_entry.sh /tmp/auditlens-session-draft.md
```

## Design Constraints

- append-only changelog
- no external services
- no automatic memory store outside the repo
- no rewriting older entries
- no required git hooks

## Notes

- The existing historical changelog entries remain for reference.
- The session-based entry format applies going forward.
- If the draft needs cleanup, edit the draft file before appending it.
