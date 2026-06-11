"""AuditLens AI summary layer.

Self-contained module that produces plain-English narratives over the
classified audit signals already in the database. Fully opt-in via the
``AI_ENABLED`` env var; degrades gracefully when disabled, misconfigured,
or when the upstream Claude call fails.
"""

from backend.app.ai.summarizer import AuditSummarizer, get_summarizer

__all__ = ["AuditSummarizer", "get_summarizer"]
