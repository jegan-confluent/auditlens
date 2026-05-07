# Versioning policy

`VERSION` is the single source of truth. Anything that needs to know "which
release of AuditLens is this?" — Docker image tags, the `/health` payload,
release-note tooling — reads `VERSION` (or accepts it as a build arg).

## Rules

1. **Bump `VERSION` and update `CHANGELOG.md` in the same commit.**
   Releases without a CHANGELOG entry are not allowed; CHANGELOG entries
   without a corresponding `VERSION` bump get rolled into the next release.
2. **`VERSION` is `MAJOR.MINOR.PATCH`** following SemVer:
   * **MAJOR** — breaking API contract changes (route removed, response
     shape changed in a way clients can't ignore, DB schema requires a
     manual migration).
   * **MINOR** — additive features and hardening passes (the Phase 1/2/3
     pass bumped 3.0.1 → 3.1.0).
   * **PATCH** — bug fixes / dependency-only updates that change no public
     contract.
3. **Pre-release tags** (`-alpha`, `-rc1`, etc.) are allowed but the
   committed `VERSION` file should never carry one in the `master` branch.
4. **Do not commit a CHANGELOG entry for an unreleased version.** Land the
   work, bump `VERSION`, write the entry, all in the same commit.

## How to bump

```bash
# 1. Decide the new version.
echo "3.2.0" > VERSION

# 2. Prepend a new entry to CHANGELOG.md under the heading
#    "## [3.2.0] - YYYY-MM-DD" with Added / Changed / Fixed / Security
#    sub-sections.

# 3. Commit both together:
git add VERSION CHANGELOG.md
git commit -m "release: 3.2.0 — <one-line summary>"
```

## How CI consumes `VERSION`

The Docker build reads `VERSION` via the `Makefile` (`IMAGE_NAME`/`VERSION`
variables), so `make build` produces `audit-forwarder:<VERSION>`. Avoid
hard-coding the version anywhere else.
