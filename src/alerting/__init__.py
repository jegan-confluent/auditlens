"""
Alerting module for webhook integrations.
"""

from .webhook_config import WebhookConfig, WebhookType, get_webhook_setup_guides
from .webhook_sender import WebhookSender, get_webhook_sender

__all__ = [
    'WebhookConfig',
    'WebhookType',
    'get_webhook_setup_guides',
    'WebhookSender',
    'get_webhook_sender',
]
