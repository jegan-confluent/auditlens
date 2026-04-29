#!/bin/bash
set -euo pipefail

exec python3 "$(dirname "$0")/scripts/bootstrap_auditlens.py" "$@"
