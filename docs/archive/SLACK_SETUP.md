# Slack Alerting Setup Guide

Real-time Slack alerts for CRITICAL audit events detected by the forwarder.

## Overview

The forwarder can send automatic Slack alerts when CRITICAL audit events are detected, enabling your team to respond quickly to security incidents.

**Features:**
- Real-time alerts for CRITICAL events (configurable for HIGH/MEDIUM/LOW as well)
- Rich Slack formatting with color-coded severity
- Rate limiting to prevent alert spam (10 alerts/min by default)
- Cooldown period between duplicate alerts (60s by default)
- Zero infrastructure required (uses Slack Incoming Webhooks)

## Quick Start

### 1. Create Slack Webhook

1. Go to https://api.slack.com/apps
2. Click **"Create New App"** → **"From scratch"**
3. Name it "Audit Log Alerts" and select your workspace
4. In the app settings, go to **"Incoming Webhooks"**
5. Toggle **"Activate Incoming Webhooks"** to ON
6. Click **"Add New Webhook to Workspace"**
7. Select the channel for alerts (e.g., `#security-alerts`) and click **"Allow"**
8. Copy the webhook URL (looks like: `https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX`)

### 2. Configure Environment

Add to your `.env` file:

```bash
# Slack Webhook Alerting
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
SLACK_WEBHOOK_ENABLED=true
SLACK_WEBHOOK_SEND_CRITICAL=true
```

### 3. Restart Forwarder

```bash
./run_forwarder.sh
```

You should see in the logs:
```
Webhook alerting enabled: slack
```

### 4. Test the Integration

Send a test alert:

```python
python3 -c "from src.alerting import get_webhook_sender; get_webhook_sender().send_test_alert()"
```

You should receive a test alert in your Slack channel!

## Configuration Options

### Environment Variables

All Slack webhook configuration uses the `SLACK_WEBHOOK_` prefix:

```bash
# Required
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX

# Optional (with defaults)
SLACK_WEBHOOK_ENABLED=true                      # Enable/disable alerting
SLACK_WEBHOOK_TYPE=slack                        # Webhook type (slack, pagerduty, teams, generic)
SLACK_WEBHOOK_SEND_CRITICAL=true                # Send CRITICAL events
SLACK_WEBHOOK_SEND_HIGH=false                   # Send HIGH events
SLACK_WEBHOOK_SEND_MEDIUM=false                 # Send MEDIUM events
SLACK_WEBHOOK_SEND_LOW=false                    # Send LOW events
SLACK_WEBHOOK_MAX_ALERTS_PER_MINUTE=10          # Rate limit
SLACK_WEBHOOK_COOLDOWN_SECONDS=60               # Cooldown between duplicate alerts
```

### Severity Levels

By default, only **CRITICAL** events trigger alerts. You can customize:

```bash
# Alert on CRITICAL and HIGH events
SLACK_WEBHOOK_SEND_CRITICAL=true
SLACK_WEBHOOK_SEND_HIGH=true
SLACK_WEBHOOK_SEND_MEDIUM=false
SLACK_WEBHOOK_SEND_LOW=false
```

⚠️ **Warning:** Enabling MEDIUM or LOW will generate many more alerts. Monitor your alert volume carefully.

### Rate Limiting

Prevent alert fatigue with built-in rate limiting:

- **Per-minute limit**: Max 10 alerts per minute by default
- **Cooldown period**: 60 seconds between duplicate alerts of the same type
- **Smart deduplication**: Same event type (e.g., `DeleteKafkaCluster`) won't spam

Example: If 15 CRITICAL events occur in 1 minute, only 10 alerts are sent. The rest are rate-limited (logged but not sent).

## Slack Message Format

Alerts appear as rich Slack messages:

```
🚨 CRITICAL Audit Event Detected

DeleteKafkaCluster triggered by User:john.doe@example.com

Method:     DeleteKafkaCluster
Principal:  User:john.doe@example.com  
Status:     SUCCESS
Source IP:  203.0.113.45
Reason:     Explicit CRITICAL method: DeleteKafkaCluster

Confluent Audit Log Intelligence
```

**Color coding:**
- 🔴 CRITICAL: Red
- 🟠 HIGH: Orange
- 🟡 MEDIUM: Yellow
- 🟢 LOW: Green

## Example CRITICAL Events

These events will trigger alerts (if configured):

### Security Failures
- `UNAUTHENTICATED` - Failed authentication attempt
- `PERMISSION_DENIED` - Unauthorized access attempt
- `UNAUTHORIZED` - Invalid credentials

### Destructive Operations
- `DeleteKafkaCluster` - Cluster deletion
- `DeleteEnvironment` - Environment deletion
- `kafka.DeleteTopics` - Topic deletion
- `kafka.DeleteRecords` - Data deletion

### Security Configuration Changes
- `DeleteServiceAccount` - Service account deletion
- `DeleteApiKey` - API key deletion
- `kafka.DeleteAcls` - ACL deletion
- `DeleteIdentityProvider` - IdP deletion

## Troubleshooting

### No alerts are being sent

1. **Check forwarder logs:**
   ```bash
   # Look for "Webhook alerting enabled"
   grep "Webhook alerting" <forwarder-log>
   ```

2. **Verify webhook URL:**
   ```bash
   curl -X POST -H 'Content-Type: application/json' \
     -d '{"text":"Test from curl"}' \
     YOUR_WEBHOOK_URL
   ```

3. **Check environment variables:**
   ```bash
   python3 -c "import os; print(os.getenv('SLACK_WEBHOOK_URL'))"
   ```

4. **Test webhook sender directly:**
   ```python
   from src.alerting import get_webhook_sender
   sender = get_webhook_sender()
   print(f"Enabled: {sender.enabled}")
   print(f"Config: {sender.config}")
   sender.send_test_alert()
   ```

### Alerts are being rate-limited

Check logs for:
```
Rate limit reached: 10 alerts/min
```

**Solutions:**
- Increase rate limit: `SLACK_WEBHOOK_MAX_ALERTS_PER_MINUTE=20`
- Reduce alert severity: Only send CRITICAL (default)
- Check for event loops or misconfiguration causing excessive CRITICAL events

### Webhook URL not working

1. **Verify webhook is active:**
   - Go to https://api.slack.com/apps
   - Select your app → Incoming Webhooks
   - Ensure webhook is listed and active

2. **Check webhook permissions:**
   - Webhook must be added to a specific channel
   - Bot must have permission to post in that channel

3. **Test with curl:**
   ```bash
   curl -X POST -H 'Content-Type: application/json' \
     -d '{"text":"Test message"}' \
     https://hooks.slack.com/services/YOUR/WEBHOOK/URL
   ```

### Duplicate alerts

This is expected for repeated events. The cooldown prevents spam:

```bash
# Increase cooldown to 5 minutes
SLACK_WEBHOOK_COOLDOWN_SECONDS=300
```

Alert key format: `critical_event:{methodName}`

Same method within cooldown period = suppressed.

## Advanced Configuration

### Multiple Webhooks

Want alerts in different channels for different severities?

Create multiple Slack apps and webhooks, then configure in code:

```python
from src.alerting import WebhookConfig, WebhookType, WebhookSender

# CRITICAL events → #security-critical
critical_config = WebhookConfig(
    webhook_type=WebhookType.SLACK,
    url=os.getenv('SLACK_WEBHOOK_CRITICAL_URL'),
    send_critical=True,
    send_high=False
)
critical_sender = WebhookSender(critical_config)

# HIGH events → #security-high
high_config = WebhookConfig(
    webhook_type=WebhookType.SLACK,
    url=os.getenv('SLACK_WEBHOOK_HIGH_URL'),
    send_critical=False,
    send_high=True
)
high_sender = WebhookSender(high_config)
```

### Custom Formatting

Modify `src/alerting/webhook_sender.py`:

```python
def _format_slack_message(self, event: Dict[str, Any]) -> Dict[str, Any]:
    # Customize message format here
    # Add custom fields, change colors, etc.
    ...
```

### Integration with Other Tools

The webhook sender supports multiple webhook types:

- **Slack**: Built-in support
- **PagerDuty**: Set `SLACK_WEBHOOK_TYPE=pagerduty`
- **Microsoft Teams**: Set `SLACK_WEBHOOK_TYPE=teams`
- **Generic**: Any JSON webhook endpoint

See `src/alerting/webhook_config.py` for examples.

## Best Practices

1. **Start with CRITICAL only**
   - Monitor volume before adding HIGH/MEDIUM

2. **Use dedicated alert channel**
   - Create `#audit-log-alerts` or `#security-alerts`
   - Don't use general team channels

3. **Configure appropriate rate limits**
   - Default (10/min) works for most cases
   - Adjust based on your event volume

4. **Set up Slack notifications**
   - Configure @mentions for urgent alerts
   - Use Slack workflows for escalation

5. **Monitor alert fatigue**
   - If getting too many alerts, increase cooldown
   - Review what's being classified as CRITICAL

6. **Test before production**
   - Send test alerts to verify formatting
   - Ensure team knows what alerts mean

## Metrics

Alert statistics are exposed via Prometheus metrics at `/metrics`:

```
# Total alerts sent
audit_alerts_sent_total{severity="CRITICAL"} 42

# Alerts rate-limited
audit_alerts_rate_limited_total{severity="CRITICAL"} 5

# Webhook failures
audit_webhook_failures_total{type="slack"} 0
```

## Security Considerations

1. **Webhook URL is sensitive**
   - Store in `.secrets`, not `.env`
   - Don't commit to git
   - Rotate regularly

2. **Alert content contains PII**
   - Principal names, IP addresses
   - Ensure Slack channel has appropriate access controls

3. **Rate limiting prevents DoS**
   - Built-in protection against alert storms
   - Malicious events can't spam your Slack

## Support

For issues or questions:
1. Check logs: `grep -i webhook <forwarder-log>`
2. Test webhook: `python3 -c "from src.alerting import get_webhook_sender; get_webhook_sender().send_test_alert()"`
3. Review configuration: Check `.env` for `SLACK_WEBHOOK_*` variables
4. See code: `src/alerting/webhook_sender.py`

---

**Last Updated:** December 5, 2024  
**Version:** 1.0
