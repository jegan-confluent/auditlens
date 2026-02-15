"""
Webhook Sender for Slack Alerting

Sends alerts to Slack (and other webhook endpoints) for CRITICAL events.
Includes rate limiting, cooldown, and rich formatting.
"""

import os
import time
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from collections import defaultdict
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .webhook_config import WebhookConfig, WebhookType

logger = logging.getLogger(__name__)


class WebhookSender:
    """
    Sends alerts to configured webhook endpoints with rate limiting.
    """

    def __init__(self, config: Optional[WebhookConfig] = None):
        """
        Initialize webhook sender.
        
        Args:
            config: WebhookConfig instance, or None to load from environment
        """
        self.config = config or WebhookConfig.from_env("SLACK_WEBHOOK")
        self.enabled = self.config is not None and self.config.enabled
        
        # Rate limiting state
        self.alert_counts = defaultdict(int)  # alerts per minute bucket
        self.last_alert_time = {}  # cooldown tracking per alert type
        self.current_minute_bucket = 0
        
        if self.enabled:
            logger.info(f"WebhookSender initialized: {self.config.webhook_type} alerts enabled")
        else:
            logger.info("WebhookSender initialized: alerts disabled (no configuration)")

    def should_send_alert(self, criticality: str, alert_key: str) -> bool:
        """
        Check if alert should be sent based on configuration and rate limits.
        
        Args:
            criticality: Event criticality level (CRITICAL, HIGH, MEDIUM, LOW)
            alert_key: Unique key for this alert type (for cooldown tracking)
            
        Returns:
            True if alert should be sent
        """
        if not self.enabled:
            return False

        # Check if this criticality level should trigger alerts
        criticality_upper = criticality.upper()
        if criticality_upper == 'CRITICAL' and not self.config.send_critical:
            return False
        if criticality_upper == 'HIGH' and not self.config.send_high:
            return False
        if criticality_upper == 'MEDIUM' and not self.config.send_medium:
            return False
        if criticality_upper == 'LOW' and not self.config.send_low:
            return False

        # Rate limiting - check current minute bucket
        current_time = time.time()
        current_minute = int(current_time / 60)
        
        # Reset counter if we're in a new minute
        if current_minute != self.current_minute_bucket:
            self.alert_counts.clear()
            self.current_minute_bucket = current_minute
        
        # Check rate limit
        if self.alert_counts[current_minute] >= self.config.max_alerts_per_minute:
            logger.warning(f"Rate limit reached: {self.alert_counts[current_minute]} alerts/min")
            return False

        # Cooldown check - has enough time passed since last alert of this type?
        if alert_key in self.last_alert_time:
            time_since_last = current_time - self.last_alert_time[alert_key]
            if time_since_last < self.config.cooldown_seconds:
                logger.debug(f"Cooldown active for {alert_key}: {time_since_last:.0f}s / {self.config.cooldown_seconds}s")
                return False

        return True

    def send_critical_event_alert(self, event: Dict[str, Any]) -> bool:
        """
        Send alert for a CRITICAL event.
        
        Args:
            event: The audit event dict with keys like methodName, principal, etc.
            
        Returns:
            True if alert was sent successfully
        """
        method_name = event.get('methodName', 'unknown')
        principal = event.get('principal', 'unknown')
        result_status = event.get('resultStatus', 'unknown')
        
        alert_key = f"critical_event:{method_name}"
        
        if not self.should_send_alert('CRITICAL', alert_key):
            return False

        # Format message based on webhook type
        if self.config.webhook_type == WebhookType.SLACK:
            payload = self._format_slack_message(event)
        else:
            payload = self._format_generic_message(event)

        # Send the webhook
        success = self._send_webhook(payload)
        
        if success:
            # Update rate limiting state
            current_minute = int(time.time() / 60)
            self.alert_counts[current_minute] += 1
            self.last_alert_time[alert_key] = time.time()
            logger.info(f"Alert sent for CRITICAL event: {method_name} by {principal}")
        
        return success

    def _format_slack_message(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format event as Slack message with rich formatting.
        
        Args:
            event: The audit event
            
        Returns:
            Slack-formatted payload
        """
        method_name = event.get('methodName', 'unknown')
        principal = event.get('principal', 'unknown')
        result_status = event.get('resultStatus', 'unknown')
        source_ip = event.get('source_ip') or event.get('clientIp', 'unknown')
        event_time = event.get('time', datetime.utcnow().isoformat())
        criticality = event.get('criticality', 'UNKNOWN')
        
        # Color based on criticality
        color_map = {
            'CRITICAL': '#dc3545',  # Red
            'HIGH': '#fd7e14',      # Orange
            'MEDIUM': '#ffc107',    # Yellow
            'LOW': '#28a745',       # Green
        }
        color = color_map.get(criticality, '#6c757d')
        
        # Build fields
        fields = [
            {
                "title": "Method",
                "value": method_name,
                "short": True
            },
            {
                "title": "Principal",
                "value": principal[:50],  # Truncate long principals
                "short": True
            },
            {
                "title": "Status",
                "value": result_status,
                "short": True
            },
            {
                "title": "Source IP",
                "value": source_ip,
                "short": True
            }
        ]
        
        # Add classification reason if available
        if 'classification_reason' in event:
            fields.append({
                "title": "Reason",
                "value": event['classification_reason'],
                "short": False
            })
        
        return {
            "attachments": [
                {
                    "fallback": f"{criticality}: {method_name} by {principal}",
                    "color": color,
                    "title": f":rotating_light: {criticality} Audit Event Detected",
                    "text": f"*{method_name}* triggered by *{principal}*",
                    "fields": fields,
                    "footer": "Confluent Audit Log Intelligence",
                    "ts": int(datetime.fromisoformat(event_time.replace('Z', '+00:00')).timestamp()),
                }
            ]
        }

    def _format_generic_message(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format event as generic JSON payload.
        
        Args:
            event: The audit event
            
        Returns:
            Generic JSON payload
        """
        return {
            "alert_type": "critical_audit_event",
            "severity": event.get('criticality', 'CRITICAL'),
            "timestamp": event.get('time', datetime.utcnow().isoformat()),
            "event": {
                "method": event.get('methodName'),
                "principal": event.get('principal'),
                "status": event.get('resultStatus'),
                "source_ip": event.get('source_ip') or event.get('clientIp'),
                "granted": event.get('granted'),
            },
            "classification_reason": event.get('classification_reason', ''),
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
        reraise=True
    )
    def _send_webhook_with_retry(self, url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """
        Send HTTP POST to webhook URL with retry logic.

        Args:
            url: Webhook URL
            payload: JSON payload to send
            headers: HTTP headers

        Returns:
            Response object

        Raises:
            requests.RequestException on failure after retries
        """
        logger.debug(f"Attempting webhook POST to {url}")
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=5
        )

        # Raise for 5xx status codes to trigger retry
        if response.status_code >= 500:
            logger.warning(f"Webhook returned {response.status_code}, will retry")
            response.raise_for_status()

        return response

    def _send_webhook(self, payload: Dict[str, Any]) -> bool:
        """
        Send HTTP POST to webhook URL with automatic retries.

        Args:
            payload: JSON payload to send

        Returns:
            True if successful (2xx status code)
        """
        try:
            headers = {'Content-Type': 'application/json'}

            # Add authentication if configured
            if self.config.auth_header and self.config.auth_token:
                headers[self.config.auth_header] = self.config.auth_token

            response = self._send_webhook_with_retry(self.config.url, payload, headers)

            if response.status_code in (200, 201, 202, 204):
                logger.debug(f"Webhook sent successfully: {response.status_code}")
                return True
            else:
                logger.warning(f"Webhook failed: {response.status_code} - {response.text[:200]}")
                return False

        except requests.RequestException as e:
            logger.error(f"Webhook request failed after retries: {e}")
            return False

    def send_aggregated_denial_alert(self, alert: Dict[str, Any]) -> bool:
        """
        Send alert for an aggregated denial alert (HIGH criticality).

        Args:
            alert: The aggregated denial alert dict with keys like principal,
                   denial_count, operations, etc.

        Returns:
            True if alert was sent successfully
        """
        principal = alert.get('principal', 'unknown')
        denial_count = alert.get('denial_count', 0)
        criticality = alert.get('criticality', 'HIGH')

        alert_key = f"aggregated_denial:{principal}"

        if not self.should_send_alert(criticality, alert_key):
            return False

        # Format message based on webhook type
        if self.config.webhook_type == WebhookType.SLACK:
            payload = self._format_slack_aggregated_denial(alert)
        else:
            payload = self._format_generic_aggregated_denial(alert)

        # Send the webhook
        success = self._send_webhook(payload)

        if success:
            # Update rate limiting state
            current_minute = int(time.time() / 60)
            self.alert_counts[current_minute] += 1
            self.last_alert_time[alert_key] = time.time()
            logger.info(f"Alert sent for aggregated denials: {principal} ({denial_count} denials)")

        return success

    def _format_slack_aggregated_denial(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format aggregated denial alert as Slack message.

        Args:
            alert: The aggregated denial alert

        Returns:
            Slack-formatted payload
        """
        principal = alert.get('principal', 'unknown')
        denial_count = alert.get('denial_count', 0)
        criticality = alert.get('criticality', 'HIGH')
        window_start = alert.get('window_start', '')
        window_end = alert.get('window_end', '')
        operations = alert.get('operations') or alert.get('unique_operations', [])
        source_ips = alert.get('source_ips', [])
        environment_ids = alert.get('environment_ids', [])
        cluster_ids = alert.get('cluster_ids', [])
        threshold = alert.get('threshold', 10)

        # Color based on criticality
        color_map = {
            'CRITICAL': '#dc3545',
            'HIGH': '#fd7e14',
            'MEDIUM': '#ffc107',
        }
        color = color_map.get(criticality, '#fd7e14')

        # Build fields
        fields = [
            {
                "title": "Principal",
                "value": principal[:50],
                "short": True
            },
            {
                "title": "Denial Count",
                "value": str(denial_count),
                "short": True
            },
            {
                "title": "Threshold Exceeded",
                "value": f"Yes (threshold: {threshold})" if denial_count >= threshold else f"No (threshold: {threshold})",
                "short": True
            },
            {
                "title": "Window",
                "value": f"{window_start[:19]} to {window_end[:19]}" if window_start and window_end else "N/A",
                "short": True
            }
        ]

        # Add operations if any
        if operations:
            ops_display = ', '.join(operations[:5])
            if len(operations) > 5:
                ops_display += f' (+{len(operations) - 5} more)'
            fields.append({
                "title": "Operations",
                "value": ops_display,
                "short": False
            })

        # Add source IPs if any
        if source_ips:
            ips_display = ', '.join(source_ips[:5])
            if len(source_ips) > 5:
                ips_display += f' (+{len(source_ips) - 5} more)'
            fields.append({
                "title": "Source IPs",
                "value": ips_display,
                "short": True
            })

        # Add environments/clusters
        if environment_ids:
            fields.append({
                "title": "Environments",
                "value": ', '.join(environment_ids[:3]),
                "short": True
            })

        return {
            "attachments": [
                {
                    "fallback": f"{criticality}: {denial_count} auth denials by {principal}",
                    "color": color,
                    "title": f":lock: {criticality} - Aggregated Authorization Denials",
                    "text": f"*{denial_count}* authorization denials detected for *{principal}*",
                    "fields": fields,
                    "footer": "Confluent Audit Log Intelligence",
                    "ts": int(time.time()),
                }
            ]
        }

    def _format_generic_aggregated_denial(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format aggregated denial alert as generic JSON payload.

        Args:
            alert: The aggregated denial alert

        Returns:
            Generic JSON payload
        """
        return {
            "alert_type": "aggregated_auth_denials",
            "severity": alert.get('criticality', 'HIGH'),
            "timestamp": alert.get('window_end', datetime.utcnow().isoformat()),
            "aggregation": {
                "principal": alert.get('principal'),
                "denial_count": alert.get('denial_count'),
                "threshold": alert.get('threshold'),
                "threshold_exceeded": alert.get('threshold_exceeded'),
                "window_start": alert.get('window_start'),
                "window_end": alert.get('window_end'),
            },
            "context": {
                "operations": alert.get('operations') or alert.get('unique_operations', []),
                "source_ips": alert.get('source_ips', []),
                "environment_ids": alert.get('environment_ids', []),
                "cluster_ids": alert.get('cluster_ids', []),
            },
        }

    def send_test_alert(self) -> bool:
        """
        Send a test alert to verify configuration.

        Returns:
            True if test alert was sent successfully
        """
        test_event = {
            'methodName': 'TestAlert',
            'principal': 'System:test',
            'resultStatus': 'SUCCESS',
            'source_ip': '127.0.0.1',
            'time': datetime.utcnow().isoformat() + 'Z',
            'criticality': 'CRITICAL',
            'classification_reason': 'Test alert to verify webhook configuration',
        }

        logger.info("Sending test alert...")
        return self.send_critical_event_alert(test_event)


# Singleton instance for easy import
_webhook_sender_instance = None


def get_webhook_sender() -> WebhookSender:
    """Get or create singleton WebhookSender instance."""
    global _webhook_sender_instance
    if _webhook_sender_instance is None:
        _webhook_sender_instance = WebhookSender()
    return _webhook_sender_instance
