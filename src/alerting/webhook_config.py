"""
Webhook Configuration for Future Alerting Integration.

This module provides configuration and setup guides for integrating
with various webhook-based alerting systems:
- Slack
- PagerDuty
- Microsoft Teams
- Generic webhooks

Currently provides configuration structures and documentation.
Actual webhook sending will be implemented in a future phase.
"""

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List


class WebhookType(str, Enum):
    """Supported webhook types."""
    SLACK = "slack"
    PAGERDUTY = "pagerduty"
    TEAMS = "teams"
    GENERIC = "generic"


@dataclass
class WebhookConfig:
    """Configuration for a webhook endpoint."""

    webhook_type: WebhookType
    url: str
    enabled: bool = True

    # Optional authentication
    auth_header: Optional[str] = None
    auth_token: Optional[str] = None

    # Rate limiting
    max_alerts_per_minute: int = 10
    cooldown_seconds: int = 60

    # Filtering - which alert types to send
    send_critical: bool = True
    send_high: bool = True
    send_medium: bool = False
    send_low: bool = False

    # Additional configuration
    extra_config: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls, prefix: str = "WEBHOOK") -> Optional['WebhookConfig']:
        """
        Create webhook configuration from environment variables.

        Environment variables:
        - {PREFIX}_TYPE: slack, pagerduty, teams, generic
        - {PREFIX}_URL: The webhook URL
        - {PREFIX}_ENABLED: true/false
        - {PREFIX}_AUTH_HEADER: Authorization header name
        - {PREFIX}_AUTH_TOKEN: Authorization token
        - {PREFIX}_SEND_CRITICAL: true/false
        - {PREFIX}_SEND_HIGH: true/false
        - {PREFIX}_SEND_MEDIUM: true/false
        - {PREFIX}_SEND_LOW: true/false
        """
        url = os.getenv(f'{prefix}_URL')
        if not url:
            return None

        webhook_type_str = os.getenv(f'{prefix}_TYPE', 'generic').lower()
        try:
            webhook_type = WebhookType(webhook_type_str)
        except ValueError:
            webhook_type = WebhookType.GENERIC

        return cls(
            webhook_type=webhook_type,
            url=url,
            enabled=os.getenv(f'{prefix}_ENABLED', 'true').lower() == 'true',
            auth_header=os.getenv(f'{prefix}_AUTH_HEADER'),
            auth_token=os.getenv(f'{prefix}_AUTH_TOKEN'),
            send_critical=os.getenv(f'{prefix}_SEND_CRITICAL', 'true').lower() == 'true',
            send_high=os.getenv(f'{prefix}_SEND_HIGH', 'true').lower() == 'true',
            send_medium=os.getenv(f'{prefix}_SEND_MEDIUM', 'false').lower() == 'true',
            send_low=os.getenv(f'{prefix}_SEND_LOW', 'false').lower() == 'true',
        )


def get_slack_setup_guide() -> str:
    """Get setup guide for Slack webhooks."""
    return """
# Slack Webhook Setup Guide

## Step 1: Create a Slack App
1. Go to https://api.slack.com/apps
2. Click "Create New App" → "From scratch"
3. Name it "Audit Log Alerts" and select your workspace

## Step 2: Enable Incoming Webhooks
1. In your app settings, go to "Incoming Webhooks"
2. Toggle "Activate Incoming Webhooks" to ON
3. Click "Add New Webhook to Workspace"
4. Select the channel for alerts and click "Allow"
5. Copy the webhook URL

## Step 3: Configure Environment Variables
Add to your .env file:
```
WEBHOOK_TYPE=slack
WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
WEBHOOK_ENABLED=true
WEBHOOK_SEND_CRITICAL=true
WEBHOOK_SEND_HIGH=true
WEBHOOK_SEND_MEDIUM=false
WEBHOOK_SEND_LOW=false
```

## Slack Message Format
Alerts will be sent as rich Slack messages with:
- Color-coded severity (red=critical, orange=high, yellow=medium)
- Event details in structured blocks
- Links to investigate in your dashboard
"""


def get_pagerduty_setup_guide() -> str:
    """Get setup guide for PagerDuty webhooks."""
    return """
# PagerDuty Integration Setup Guide

## Step 1: Create a PagerDuty Service
1. Log into PagerDuty
2. Go to Services → Service Directory
3. Click "+ New Service"
4. Name it "Confluent Audit Alerts"

## Step 2: Create an Events API v2 Integration
1. In your service, go to the "Integrations" tab
2. Click "Add Integration"
3. Select "Events API v2"
4. Copy the "Integration Key" (Routing Key)

## Step 3: Configure Environment Variables
Add to your .env file:
```
WEBHOOK_TYPE=pagerduty
WEBHOOK_URL=https://events.pagerduty.com/v2/enqueue
WEBHOOK_AUTH_TOKEN=YOUR_INTEGRATION_KEY
WEBHOOK_ENABLED=true
WEBHOOK_SEND_CRITICAL=true
WEBHOOK_SEND_HIGH=true
WEBHOOK_SEND_MEDIUM=false
```

## PagerDuty Event Format
- CRITICAL alerts create incidents with "critical" severity
- HIGH alerts create incidents with "error" severity
- Includes dedup_key to prevent duplicate incidents
"""


def get_teams_setup_guide() -> str:
    """Get setup guide for Microsoft Teams webhooks."""
    return """
# Microsoft Teams Webhook Setup Guide

## Step 1: Create an Incoming Webhook
1. In Microsoft Teams, go to the channel where you want alerts
2. Click the "..." next to the channel name
3. Select "Connectors"
4. Find "Incoming Webhook" and click "Configure"
5. Name it "Audit Log Alerts" and optionally upload an icon
6. Click "Create" and copy the webhook URL

## Step 2: Configure Environment Variables
Add to your .env file:
```
WEBHOOK_TYPE=teams
WEBHOOK_URL=https://YOUR_TENANT.webhook.office.com/webhookb2/...
WEBHOOK_ENABLED=true
WEBHOOK_SEND_CRITICAL=true
WEBHOOK_SEND_HIGH=true
WEBHOOK_SEND_MEDIUM=false
```

## Teams Message Format
Alerts will be sent as Adaptive Cards with:
- Color-coded header based on severity
- Event details in facts format
- Action button to view in dashboard
"""


def get_generic_webhook_guide() -> str:
    """Get setup guide for generic webhooks."""
    return """
# Generic Webhook Setup Guide

For custom webhook integrations, configure a POST endpoint that accepts JSON.

## Expected Payload Format
```json
{
    "alert_type": "audit_anomaly",
    "severity": "CRITICAL",
    "timestamp": "2024-12-04T10:30:00Z",
    "anomaly": {
        "type": "auth_failure_spike",
        "principal": "User:12345",
        "source_ip": "1.2.3.4",
        "rate": 15.5,
        "threshold": 10,
        "window_seconds": 60
    },
    "details": {
        "failure_count": 15,
        "message": "Authentication failure spike detected"
    }
}
```

## Environment Variables
```
WEBHOOK_TYPE=generic
WEBHOOK_URL=https://your-endpoint.com/webhook
WEBHOOK_AUTH_HEADER=Authorization
WEBHOOK_AUTH_TOKEN=Bearer your-token
WEBHOOK_ENABLED=true
WEBHOOK_SEND_CRITICAL=true
WEBHOOK_SEND_HIGH=true
```

## Custom Headers
For custom authentication, set:
- WEBHOOK_AUTH_HEADER: The header name (e.g., "X-API-Key", "Authorization")
- WEBHOOK_AUTH_TOKEN: The header value (e.g., "your-api-key", "Bearer token")
"""


def get_webhook_setup_guides() -> Dict[WebhookType, str]:
    """Get all webhook setup guides."""
    return {
        WebhookType.SLACK: get_slack_setup_guide(),
        WebhookType.PAGERDUTY: get_pagerduty_setup_guide(),
        WebhookType.TEAMS: get_teams_setup_guide(),
        WebhookType.GENERIC: get_generic_webhook_guide(),
    }


def print_setup_guide(webhook_type: WebhookType):
    """Print the setup guide for a specific webhook type."""
    guides = get_webhook_setup_guides()
    print(guides.get(webhook_type, "Unknown webhook type"))


# Example alert payload formats for each webhook type
SLACK_PAYLOAD_EXAMPLE = {
    "attachments": [
        {
            "color": "#dc3545",  # Red for critical
            "title": "CRITICAL: Authentication Failure Spike Detected",
            "fields": [
                {"title": "Principal", "value": "User:12345", "short": True},
                {"title": "Source IP", "value": "1.2.3.4", "short": True},
                {"title": "Rate", "value": "15.5 events/min", "short": True},
                {"title": "Threshold", "value": "10 events/min", "short": True},
            ],
            "footer": "Confluent Audit Log Intelligence",
            "ts": 1701689400,
        }
    ]
}

PAGERDUTY_PAYLOAD_EXAMPLE = {
    "routing_key": "YOUR_INTEGRATION_KEY",
    "event_action": "trigger",
    "dedup_key": "auth_failure_spike:User:12345:1.2.3.4",
    "payload": {
        "summary": "Authentication failure spike from User:12345 @ 1.2.3.4",
        "severity": "critical",
        "source": "confluent-audit-intelligence",
        "custom_details": {
            "rate": 15.5,
            "threshold": 10,
            "window_seconds": 60,
        }
    }
}

TEAMS_PAYLOAD_EXAMPLE = {
    "@type": "MessageCard",
    "@context": "http://schema.org/extensions",
    "themeColor": "dc3545",
    "summary": "CRITICAL: Authentication Failure Spike",
    "sections": [
        {
            "activityTitle": "Authentication Failure Spike Detected",
            "facts": [
                {"name": "Principal", "value": "User:12345"},
                {"name": "Source IP", "value": "1.2.3.4"},
                {"name": "Rate", "value": "15.5 events/min"},
                {"name": "Threshold", "value": "10 events/min"},
            ],
            "markdown": True
        }
    ],
    "potentialAction": [
        {
            "@type": "OpenUri",
            "name": "View Dashboard",
            "targets": [
                {"os": "default", "uri": "http://localhost:8501"}
            ]
        }
    ]
}
