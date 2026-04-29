# Diary Entry: 2025-02-19

## Session Summary
Fixed critical issues in the AuditLens setup wizard where the Launch command was failing silently. Implemented comprehensive pre-launch validation, improved error detection, and fixed the GF_ADMIN_PASSWORD configuration issue that was causing docker compose to fail.

## Key Decisions

- **Use default value `:-admin` instead of required syntax `:?error`**: The docker-compose.yml `${VAR:?error}` syntax requires the variable in shell environment at parse time, but env_file only injects into containers. Changed to `${VAR:-default}` which works with env_file.

- **Pre-launch checks before docker compose**: Added comprehensive validation (Docker running, Compose available, files exist, ports free) BEFORE attempting build/start. This catches issues early with clear fix instructions.

- **Check stderr content, not just exit code**: Docker compose sometimes returns exit code 0 even on config errors (like missing required variables). Now grep output for "error|failed|missing" patterns.

- **Port-in-use is warning, not error**: If ports are already in use, services might already be running. Show warning but continue, don't block.

## Challenges & Solutions

- **Problem**: `GF_ADMIN_PASSWORD=` (empty) in .secrets caused docker compose to fail with cryptic error
  - **Solution**: Added default `admin` in three places: docker-compose.yml, save_configuration(), and load_existing_config()

- **Problem**: Wizard showed "Starting services... %" and exited silently
  - **Solution**: The % was from swallowed stderr. Added pre_launch_checks() to catch issues before docker compose runs

- **Problem**: `${VAR:?error}` in docker-compose.yml doesn't work with env_file
  - **Solution**: env_file only injects vars into containers, but `:?` requires shell env at parse time. Use `:-default` instead

## User Preferences Learned
- User expects EXACT output examples in bug reports - not "it should work" but actual terminal output
- User wants ALL paths to end properly (every launch path should show end menu)
- User provides detailed pseudocode for fixes - follow the pattern closely

## Code Patterns Used

- **Pre-flight validation pattern**: Check all prerequisites before attempting operation
  ```bash
  pre_launch_checks() {
      check_docker || return 1
      check_compose || return 1
      check_files || return 1
      # Only proceed if all checks pass
  }
  ```

- **Stderr error detection**: Check output content, not just exit code
  ```bash
  output=$(command 2>&1)
  if [ $? -ne 0 ] || echo "$output" | grep -qi "error\|failed"; then
  ```

- **Default value cascade**: Set defaults at multiple points
  ```bash
  # In load_existing_config
  CFG_VAR="${CFG_VAR:-default}"
  # In save_configuration
  VAR=${CFG_VAR:-default}
  # In docker-compose.yml
  - ENV_VAR=${VAR:-default}
  ```

## Potential CLAUDE.md Rules

- Docker compose `${VAR:?error}` syntax requires shell env, not env_file; use `${VAR:-default}` for env_file compatibility
- Always check both exit code AND stderr for docker compose commands; exit 0 doesn't mean success
- Pre-launch validation should check: daemon running, compose available, config files exist, ports free
- When fixing "silent failures", add pre-flight checks that catch issues early with clear error messages
- Test wizard flows by piping simulated input: `printf 'k\nk\nL\n' | ./script.sh 2>&1`
- For required config values, set defaults at load, save, AND docker-compose.yml levels

---
Created: 2025-02-19T16:30:00+05:30
Project: AuditLens (audit-forwarder-feb)
