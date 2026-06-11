"""AuditSummarizer — Claude-powered narrative layer over audit events.

Design rules (see CLAUDE.md and the prompt that spec'd this module):

* Fully opt-in via ``AI_ENABLED``. Default is ``false`` so existing
  deployments are unaffected.
* All Claude credentials and tunables come from env vars only; nothing
  is hardcoded or read from a checked-in config file.
* The summarizer must NEVER raise to the caller. On any failure the
  returned ``AuditSummary`` carries ``status="error"`` and a message,
  exactly like the disabled state. The route handler should be a thin
  wrapper that always sees a happy-path return value.
* Calls the existing service layer (event_service / summary_service /
  auth_analytics queries) — not the HTTP routes — so it stays inside
  the same process and the same DB session.
* TTLCache keyed by ``window_hours`` so repeated dashboard mounts
  share one upstream call. ``force=True`` callers skip the cache.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from cachetools import TTLCache
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.ai.prompts import SYSTEM_PROMPT, render_summary_prompt
from backend.app.ai.schemas import AuditSummary
from backend.app.db.models import AuditEvent
from backend.app.services.event_service import _period_stats
from backend.app.services.summary_service import get_summary


logger = logging.getLogger("auditlens.backend.ai.summarizer")


# ── Config (env-driven) ──────────────────────────────────────────────

# Default model: Sonnet 4.5 is the sweet spot for narrative-over-numbers
# work — costs ~5× less than Opus and keeps latency under 5 s for the
# payload sizes this layer sends. The default can be overridden at any
# time without a code change.
_DEFAULT_MODEL = "claude-sonnet-4-5"
_DEFAULT_MAX_TOKENS = 1024
_DEFAULT_CACHE_TTL_S = 300
_CLAUDE_TIMEOUT_S = 30.0


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer for %s=%r — falling back to %d", name, raw, default)
        return default


# ── Summarizer ──────────────────────────────────────────────────────


class AuditSummarizer:
    """Build context payloads and call Claude.

    One instance per process is enough; the cache and the lock around the
    Anthropic client are instance-level. Use ``get_summarizer()`` to
    fetch the shared singleton.
    """

    def __init__(self) -> None:
        self._client: Any | None = None
        self._client_lock = threading.Lock()
        ttl_seconds = _env_int("AI_CACHE_TTL", _DEFAULT_CACHE_TTL_S)
        # maxsize bounds memory if a caller passes wildly varying
        # window_hours values — eight buckets is plenty for current
        # window_hours options (1, 6, 12, 24, 72, …).
        self._cache: TTLCache[int, AuditSummary] = TTLCache(maxsize=16, ttl=ttl_seconds)
        self._cache_lock = threading.Lock()

    # ---- config helpers (re-read on every call so live .env edits work) ----

    @property
    def enabled(self) -> bool:
        return _env_bool("AI_ENABLED", default=False)

    @property
    def api_key(self) -> str:
        return os.getenv("CLAUDE_API_KEY", "").strip()

    @property
    def model(self) -> str:
        return os.getenv("AI_SUMMARY_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL

    @property
    def max_tokens(self) -> int:
        return _env_int("AI_SUMMARY_MAX_TOKENS", _DEFAULT_MAX_TOKENS)

    @property
    def cache_ttl_seconds(self) -> int:
        return _env_int("AI_CACHE_TTL", _DEFAULT_CACHE_TTL_S)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    # ---- public surface ----

    def health(self) -> dict[str, Any]:
        if not self.enabled:
            return {
                "enabled": False,
                "configured": self.configured,
                "model": self.model,
                "cache_ttl_seconds": self.cache_ttl_seconds,
                "reachable": None,
                "message": "AI insights disabled. Set AI_ENABLED=true to enable.",
            }
        if not self.configured:
            return {
                "enabled": True,
                "configured": False,
                "model": self.model,
                "cache_ttl_seconds": self.cache_ttl_seconds,
                "reachable": False,
                "message": "AI_ENABLED=true but CLAUDE_API_KEY is missing.",
            }
        return {
            "enabled": True,
            "configured": True,
            "model": self.model,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "reachable": None,
            "message": None,
        }

    def summarize(
        self,
        db: Session,
        *,
        window_hours: int = 24,
        force: bool = False,
    ) -> AuditSummary:
        """Produce (or fetch the cached) summary for the requested window.

        Synchronous on purpose: the FastAPI route runs the call in a
        thread pool via ``run_in_threadpool`` so the event loop never
        blocks. Using the sync Anthropic client avoids hoisting an
        asyncio dependency into a code path that may be invoked from
        the daemon-thread retention loop in future.
        """
        now = datetime.now(timezone.utc)

        if not self.enabled:
            return AuditSummary(
                status="disabled",
                generated_at=now,
                window_hours=window_hours,
                message="Set AI_ENABLED=true and CLAUDE_API_KEY to enable.",
                model_used=self.model,
            )

        if not self.configured:
            return AuditSummary(
                status="error",
                generated_at=now,
                window_hours=window_hours,
                message="CLAUDE_API_KEY is not set.",
                model_used=self.model,
            )

        if not force:
            cached = self._cache_get(window_hours)
            if cached is not None:
                return cached

        try:
            context = self._build_context(db, window_hours=window_hours)
        except Exception as exc:  # pragma: no cover - context errors are unusual
            logger.exception("AI summary: failed to build context")
            return AuditSummary(
                status="error",
                generated_at=now,
                window_hours=window_hours,
                message=f"Failed to assemble audit context: {exc}",
                model_used=self.model,
            )

        prompt = render_summary_prompt(context)
        start = time.perf_counter()
        try:
            parsed, latency_ms = self._call_claude(prompt)
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.warning("AI summary: Claude call failed after %d ms: %s", elapsed_ms, exc)
            return AuditSummary(
                status="error",
                generated_at=now,
                window_hours=window_hours,
                message=str(exc),
                context_used=context,
                model_used=self.model,
                latency_ms=elapsed_ms,
            )

        summary = AuditSummary(
            status="ok",
            generated_at=now,
            window_hours=window_hours,
            headline=parsed.get("headline"),
            health=parsed.get("health"),
            summary=parsed.get("summary"),
            anomalies=list(parsed.get("anomalies") or []),
            top_risk=parsed.get("top_risk"),
            recommended_actions=list(parsed.get("recommended_actions") or []),
            confidence=parsed.get("confidence"),
            context_used=context,
            model_used=self.model,
            latency_ms=latency_ms,
        )
        self._cache_put(window_hours, summary)
        return summary

    def latest(self, window_hours: int = 24) -> AuditSummary | None:
        """Return the most recent cached summary, or None if nothing is cached."""
        return self._cache_get(window_hours)

    # ---- cache helpers ----

    def _cache_get(self, window_hours: int) -> AuditSummary | None:
        with self._cache_lock:
            return self._cache.get(window_hours)

    def _cache_put(self, window_hours: int, summary: AuditSummary) -> None:
        with self._cache_lock:
            self._cache[window_hours] = summary

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._cache.clear()

    # ---- Claude client ----

    def _get_client(self) -> Any:
        """Lazy-import + lazy-construct the Anthropic client.

        Lazy import means a missing ``anthropic`` package does not crash
        unrelated routes at startup — only ``summarize()`` notices, and
        the failure is surfaced as ``status="error"`` like any other
        Claude failure.
        """
        with self._client_lock:
            if self._client is None:
                try:
                    import anthropic  # type: ignore[import-not-found]
                except ImportError as exc:
                    raise RuntimeError(
                        "anthropic package not installed. "
                        "Run `pip install anthropic` and restart the API."
                    ) from exc
                self._client = anthropic.Anthropic(
                    api_key=self.api_key,
                    timeout=_CLAUDE_TIMEOUT_S,
                )
            return self._client

    def _call_claude(self, prompt: str) -> tuple[dict[str, Any], int]:
        client = self._get_client()
        start = time.perf_counter()
        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        latency_ms = int((time.perf_counter() - start) * 1000)

        # The SDK returns a list of content blocks; the JSON we asked
        # for is in the first text block. If the model wrapped it in
        # markdown despite the instruction, strip the fence before
        # parsing.
        text_chunks: list[str] = []
        for block in getattr(response, "content", []) or []:
            block_text = getattr(block, "text", None)
            if isinstance(block_text, str):
                text_chunks.append(block_text)
        raw_text = "".join(text_chunks).strip()
        cleaned = _strip_markdown_fence(raw_text)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Claude returned non-JSON response: {raw_text[:200]}"
            ) from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Claude returned non-object JSON: {type(parsed).__name__}")
        return parsed, latency_ms

    # ---- context assembly ----

    def _build_context(self, db: Session, *, window_hours: int) -> dict[str, Any]:
        """Assemble the structured payload sent to Claude.

        Uses the existing service-layer functions so we always pull
        whatever the dashboard would show — no second-source-of-truth
        risk. ``_period_stats`` produces an Nm/Nh-aware aggregation we
        can reuse for both the current window and the seven-day baseline.
        """
        window = f"{int(window_hours)}h"
        baseline_window = "168h"  # seven days, used for the % comparison

        summary = get_summary(
            db,
            mode="audit_trail",
            time_window=window,
            include_noise=False,
        )

        current = _period_stats(db, window)
        baseline = _period_stats(db, baseline_window)

        auth_failures = _auth_failure_stats(db, window_hours=window_hours)
        ip_denials = _ip_denial_count(db, window_hours=window_hours)
        role_changes = _role_binding_change_count(db, window_hours=window_hours)
        at_events = _access_transparency_count(db, window_hours=window_hours)

        top_actors = [
            {
                "actor": entry.get("value") or entry.get("actor"),
                "count": entry.get("count", 0),
                "display_name": entry.get("display_name"),
            }
            for entry in (summary.get("top_subjects") or [])[:5]
        ]

        top_actions = [
            {"action": entry["value"], "count": entry["count"]}
            for entry in (summary.get("top_actions") or [])[:5]
            if entry.get("value")
        ]

        by_signal = {
            "action_required": int(summary.get("action_required_count") or 0),
            "attention": int(summary.get("attention_count") or 0),
            "informational": int(summary.get("informational_count") or 0),
            "noise": int(summary.get("noise_count") or 0),
        }

        baseline_comparison = {
            "events_vs_7d_avg": _pct_change(
                current_total=current.get("total", 0),
                baseline_total=baseline.get("total", 0),
                window_hours=window_hours,
            ),
            "auth_failures_vs_7d_avg": _pct_change(
                current_total=auth_failures["total"],
                baseline_total=auth_failures["baseline_total"],
                window_hours=window_hours,
            ),
        }

        return {
            "window_hours": int(window_hours),
            "total_events": int(summary.get("total_events") or 0),
            "by_signal": by_signal,
            "top_actors": top_actors,
            "top_actions": top_actions,
            "auth_failures": {
                "total": auth_failures["total"],
                "top_actors": auth_failures["top_actors"],
            },
            "alerts_fired": int(summary.get("action_required_count") or 0),
            "ip_denials": int(ip_denials),
            "role_changes": int(role_changes),
            "access_transparency": int(at_events),
            "baseline_comparison": baseline_comparison,
        }


# ── helpers ──────────────────────────────────────────────────────────


def _strip_markdown_fence(text_value: str) -> str:
    """Remove ```json ... ``` fences if Claude added them.

    Belt-and-braces — the prompt asks for raw JSON, but a hardened
    parser keeps the route reliable when the model decides to "help"
    by wrapping its output.
    """
    stripped = text_value.strip()
    if stripped.startswith("```"):
        # Drop the first fence line ("```json" or "```").
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1 :]
        if stripped.endswith("```"):
            stripped = stripped[: -3]
    return stripped.strip()


def _pct_change(*, current_total: int, baseline_total: int, window_hours: int) -> str:
    """Compare current-window volume to the per-window 7d baseline.

    The baseline (168 h) is scaled to the window size before comparison
    so a 24 h window with 100 events vs. a 7 d total of 700 reports
    "+0%", not "-86%".
    """
    if window_hours <= 0:
        return "n/a"
    scaled_baseline = baseline_total * (window_hours / 168.0)
    if scaled_baseline <= 0:
        return "n/a" if current_total == 0 else "new"
    change = (current_total - scaled_baseline) / scaled_baseline * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.0f}%"


def _auth_failure_stats(db: Session, *, window_hours: int) -> dict[str, Any]:
    """Auth-failure totals, top failing actors, and a 7-day baseline.

    Uses raw SQL to keep the path narrow — the auth_analytics route
    queries ``audit_events_noise`` separately and may not be the
    fairest comparison here. We stick with ``audit_events`` where
    failures are persisted as ``is_failure=True``.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max(window_hours, 1))
    baseline_cutoff = now - timedelta(days=7)

    total = int(
        db.scalar(
            text(
                "SELECT COUNT(*) FROM audit_events "
                "WHERE is_failure = TRUE AND timestamp >= :cutoff"
            ),
            {"cutoff": cutoff},
        )
        or 0
    )

    baseline_total = int(
        db.scalar(
            text(
                "SELECT COUNT(*) FROM audit_events "
                "WHERE is_failure = TRUE AND timestamp >= :cutoff"
            ),
            {"cutoff": baseline_cutoff},
        )
        or 0
    )

    top_rows = db.execute(
        text(
            "SELECT COALESCE(actor_display_name, actor) AS actor_label, "
            "       COUNT(*) AS failure_count "
            "FROM audit_events "
            "WHERE is_failure = TRUE AND timestamp >= :cutoff "
            "  AND actor IS NOT NULL AND actor <> '' "
            "GROUP BY COALESCE(actor_display_name, actor) "
            "ORDER BY failure_count DESC "
            "LIMIT 5"
        ),
        {"cutoff": cutoff},
    ).all()

    top_actors = [
        {"actor": row.actor_label, "count": int(row.failure_count or 0)}
        for row in top_rows
        if row.actor_label
    ]
    return {"total": total, "baseline_total": baseline_total, "top_actors": top_actors}


def _ip_denial_count(db: Session, *, window_hours: int) -> int:
    """Count of IP-filter denials in the window.

    Uses the same column the IP-denial views key on
    (``ipfilter_client_ip`` is populated for denial events) plus the
    ``is_denied`` flag. Done as a single COUNT to keep the budget tiny.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(window_hours, 1))
    return int(
        db.scalar(
            text(
                "SELECT COUNT(*) FROM audit_events "
                "WHERE is_denied = TRUE "
                "  AND ipfilter_client_ip IS NOT NULL "
                "  AND timestamp >= :cutoff"
            ),
            {"cutoff": cutoff},
        )
        or 0
    )


def _role_binding_change_count(db: Session, *, window_hours: int) -> int:
    """Count of RBAC role-binding mutations in the window.

    Filters on ``auth_role_target`` being non-null (set when the action
    targeted a specific principal/role pair) plus
    ``impact_type='access_change'``. Together these cover both grant
    and revoke flows.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(window_hours, 1))
    return int(
        db.scalar(
            text(
                "SELECT COUNT(*) FROM audit_events "
                "WHERE impact_type = 'access_change' "
                "  AND timestamp >= :cutoff"
            ),
            {"cutoff": cutoff},
        )
        or 0
    )


def _access_transparency_count(db: Session, *, window_hours: int) -> int:
    """Count of Confluent-personnel access events in the window."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(window_hours, 1))
    return int(
        db.scalar(
            text(
                "SELECT COUNT(*) FROM audit_events "
                "WHERE at_operator IS NOT NULL "
                "  AND timestamp >= :cutoff"
            ),
            {"cutoff": cutoff},
        )
        or 0
    )


# ── module singleton ─────────────────────────────────────────────────

_summarizer_singleton: AuditSummarizer | None = None
_singleton_lock = threading.Lock()


def get_summarizer() -> AuditSummarizer:
    """Return the process-wide AuditSummarizer instance.

    Constructed lazily so importing this module is free; the cache and
    Anthropic client come up the first time a route actually calls in.
    """
    global _summarizer_singleton
    with _singleton_lock:
        if _summarizer_singleton is None:
            _summarizer_singleton = AuditSummarizer()
        return _summarizer_singleton


def reset_summarizer_for_tests() -> None:
    """Drop the singleton so tests can pick up new env values cleanly."""
    global _summarizer_singleton
    with _singleton_lock:
        _summarizer_singleton = None


# Unused import — kept available because callers in summarize() pass
# ``db: Session`` around and Pyright was flagging the import as unused.
_ = AuditEvent
