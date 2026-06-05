#!/usr/bin/env python3
"""Report catch-up progress when AuditLens is in catch-up mode.

Reads CATCH_UP_MODE from .env to decide whether to render the
catch-up table or short-circuit with a "not in catch-up mode" line.

When in catch-up mode, polls http://localhost:8003/health twice 10s
apart so the noise-rate delta can be computed (noise_short_circuited_total
is a cumulative counter — instantaneous rate requires two samples).
Signal rate is computed the same way for consistency.

Exit codes:
  0  catch-up status printed (or not in catch-up mode)
  2  forwarder unreachable / went away mid-sample
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parent.parent
HEALTH_URL = "http://localhost:8003/health"
SAMPLE_SECONDS = 10


# ───── ANSI ──────────────────────────────────────────────────────────────────
def _ansi(code: str, text: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def green(t: str) -> str:  return _ansi("32", t)
def yellow(t: str) -> str: return _ansi("33", t)
def red(t: str) -> str:    return _ansi("31", t)
def cyan(t: str) -> str:   return _ansi("36", t)
def dim(t: str) -> str:    return _ansi("2",  t)
def bold(t: str) -> str:   return _ansi("1",  t)


def _read_env(key: str) -> str:
    """Read a single key from REPO_ROOT/.env. Returns '' if absent.

    Tolerates quoted values, comments, and blank lines. Does not source
    the file — we only need one value and python-dotenv would be overkill.
    """
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return ""
    try:
        for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def _fetch_health(url: str = HEALTH_URL, timeout: float = 5.0) -> dict[str, Any] | None:
    """Single /health probe. Returns parsed JSON or None on any failure."""
    try:
        with urlopen(Request(url), timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None


def _format_eta(lag: int, total_rate: float) -> str:
    """Render ETA per spec. total_rate=0 → calculating; >100h → flag
    catch-up; <1h → near done."""
    if total_rate <= 0:
        return "calculating..."
    hours = (lag / total_rate) / 3600.0
    if hours > 100:
        return "> 100 hours — consider IAM_ENRICHMENT_ENABLED=false"
    if hours < 1:
        return "< 1 hour"
    return f"~{hours:.1f} hours"


def main() -> int:
    catch_up_flag = _read_env("CATCH_UP_MODE").strip().lower()
    if catch_up_flag != "true":
        print(dim("Not in catch-up mode. Run `make diagnose-ingest` for health check."))
        return 0

    first = _fetch_health()
    if first is None:
        print(red(f"  ❌ Forwarder not reachable at {HEALTH_URL}"))
        print(dim("     Is the forwarder running? Try: docker compose -f docker-compose.prod.yml ps"))
        return 2

    print(dim(f"  Sampling forwarder for {SAMPLE_SECONDS}s (noise-rate delta)..."))
    time.sleep(SAMPLE_SECONDS)
    second = _fetch_health()
    if second is None:
        print(red("  ❌ Forwarder went away mid-sample — likely crashed."))
        return 2

    # Counter deltas over the 10s window — more accurate than the lifetime
    # averages reported by /health (processing_rate, noise_rate_per_second,
    # total_rate_per_second) for an actively-running catch-up.
    processed_a = int(first.get("processed_total") or 0)
    processed_b = int(second.get("processed_total") or 0)
    noise_a = int(first.get("noise_short_circuited_total") or 0)
    noise_b = int(second.get("noise_short_circuited_total") or 0)

    signal_rate = max(0.0, (processed_b - processed_a) / float(SAMPLE_SECONDS))
    noise_rate = max(0.0, (noise_b - noise_a) / float(SAMPLE_SECONDS))
    total_rate = signal_rate + noise_rate

    consumer_lag = int(second.get("consumer_lag") or 0)

    iam_env = _read_env("IAM_ENRICHMENT_ENABLED").strip().lower()
    iam_status = "disabled (catch-up)" if iam_env == "false" else "enabled"
    iam_colour = yellow if iam_env == "false" else green

    eta = _format_eta(consumer_lag, total_rate)

    print()
    print(cyan("Catch-up progress"))
    print(cyan("─" * 60))
    print(f"  Backlog (consumer lag):  {consumer_lag:>12,} events")
    print(f"  Signal rate:             {signal_rate:>12.1f} msg/s")
    print(f"  Noise rate:              {noise_rate:>12.1f} msg/s")
    print(f"  Total rate:              {total_rate:>12.1f} msg/s")
    print(f"  Est. time to clear:      {eta}")
    print(f"  IAM enrichment:          {iam_colour(iam_status)}")
    print(cyan("─" * 60))
    print()
    print(dim("  When lag drops below 10k events, run `make catchup-done`"))
    print(dim("  to remove the catch-up tuning and restore normal settings."))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
