"""Prompt templates for the AI summary layer.

Kept in a dedicated module so prompts can be reviewed independently of
code, the way the project keeps notifications.yml separate from the
notifier. Never put a prompt string inline in summarizer.py.
"""

from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT = (
    "You are a security analyst reviewing Confluent Cloud audit logs.\n"
    "Your job is to summarize activity, identify anomalies, and flag\n"
    "anything that warrants human attention.\n"
    "Be concise and direct. Write for a security engineer, not an executive.\n"
    "Never fabricate data. Only reason from the numbers provided.\n"
    "If the data shows nothing unusual, say so clearly."
)


SUMMARY_INSTRUCTIONS = (
    "Produce a JSON response with exactly these fields:\n"
    "{\n"
    '  "headline": "one sentence, the most important thing happening right now",\n'
    '  "health": "healthy|elevated|critical",\n'
    '  "summary": "2-3 sentences covering overall activity pattern",\n'
    '  "anomalies": ["list of specific anomalies worth investigating"],\n'
    '  "top_risk": "the single highest-risk finding, or null if none",\n'
    '  "recommended_actions": ["concrete action items, max 3"],\n'
    '  "confidence": "high|medium|low — how confident are you given the data quality"\n'
    "}\n"
    "Respond with JSON only. No preamble, no markdown, no explanation."
)


def render_summary_prompt(context: dict[str, Any]) -> str:
    """Return the user-turn content for the summary call.

    ``context`` must be the structured payload built by the summarizer —
    NEVER raw audit events. Serialised with ``default=str`` so any
    accidentally-non-JSON value (datetime, Decimal) is stringified
    instead of raising, which would otherwise make the whole AI layer
    return an error status for a transient data shape change.
    """
    context_block = json.dumps(context, indent=2, sort_keys=True, default=str)
    return (
        f"Audit context for the last {context.get('window_hours', '?')} hour(s):\n"
        f"```json\n{context_block}\n```\n\n"
        f"{SUMMARY_INSTRUCTIONS}"
    )
