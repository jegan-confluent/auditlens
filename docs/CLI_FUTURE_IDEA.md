# AuditLens CLI Future Idea

This is not part of the current patch. Current priority is UI latest-mode reliability.

## Purpose

A future CLI could help operators quickly query creation, deletion, configuration, access, failure, and denied events without opening the UI.

## Example Future Commands

```bash
auditlens events changes --since 2h --group-by environment,cluster,actor
auditlens events topics --since 2h --group-by environment,cluster,user
auditlens events action-required --since 24h
auditlens events actor sa-prod-admin --since 1h
auditlens events topic auditlens-test-123 --show-flow
```

## Possible Output

- grouped by environment
- grouped by cluster
- grouped by user or service account
- created/deleted topics
- configuration changes
- failures and denied attempts

## Timing

Useful for v1.1/v2. Do not implement until the UI latest-mode path is reliable.
