"""
Audit event metrics for Prometheus.

Tracks critical events, severity levels, operation types, and anomalies
for dashboard visibility and alerting.
"""

import re
import time
import threading
from typing import Dict, Any, Optional, List
from cachetools import LRUCache


def sanitize_label(value: str, max_length: int = 128) -> str:
    """
    Sanitize value for use as Prometheus label.

    Removes injection characters that could break Prometheus format:
    - Curly braces {} (label delimiter)
    - Double quotes " (value delimiter)
    - Newlines and backslashes

    Args:
        value: The raw value to sanitize
        max_length: Maximum length of the output

    Returns:
        Sanitized string safe for use as label value
    """
    if not value:
        return "unknown"
    return re.sub(r'[{}"\n\\]', '_', str(value))[:max_length]


class AuditEventMetrics:
    """Track audit event metrics for Prometheus exposition."""

    def __init__(self):
        self._lock = threading.Lock()
        # Counters by severity
        self._by_severity: Dict[str, int] = {
            'CRITICAL': 0,
            'HIGH': 0,
            'MEDIUM': 0,
            'LOW': 0
        }
        # Operation type counters
        self._deletions_total = 0
        self._creations_total = 0
        self._modifications_total = 0
        # Security counters
        self._auth_failures_total = 0
        self._permission_denied_total = 0
        # Resource type counters
        self._apikey_total = 0
        self._topic_total = 0
        self._cluster_total = 0
        # Anomaly counters
        self._anomalies_total = 0
        self._anomalies_by_type: Dict[str, int] = {}
        # Routing counters
        self._routed_by_topic: Dict[str, int] = {}
        self._routing_dry_run_total = 0
        # Per-principal activity (for anomaly context) - bounded to prevent memory leaks
        self._events_by_principal: LRUCache = LRUCache(maxsize=10000)
        # Recent critical events (last 100 for context)
        self._recent_critical_events: List[Dict[str, Any]] = []
        self._max_recent_events = 100
        # Schema Registry failures
        self._schema_registry_failures_total = 0

    def record_event(self, event: Dict[str, Any]) -> None:
        """Record metrics for a processed event."""
        with self._lock:
            # Severity
            severity = event.get('criticality', 'LOW')
            if severity in self._by_severity:
                self._by_severity[severity] += 1

            # Track critical events for context
            if severity == 'CRITICAL':
                self._recent_critical_events.append({
                    'time': event.get('time'),
                    'methodName': event.get('methodName'),
                    'principal': event.get('principal'),
                    'resultStatus': event.get('resultStatus'),
                })
                if len(self._recent_critical_events) > self._max_recent_events:
                    self._recent_critical_events.pop(0)

            # Operation types
            method = event.get('methodName', '') or ''
            if event.get('is_deletion') or 'Delete' in method:
                self._deletions_total += 1
            if event.get('is_creation') or 'Create' in method:
                self._creations_total += 1
            if event.get('is_modification') or any(op in method for op in ('Update', 'Alter')):
                self._modifications_total += 1

            # Security events
            result_status = event.get('resultStatus', '')
            granted = event.get('granted')
            if result_status in ('UNAUTHENTICATED', 'FAILURE'):
                self._auth_failures_total += 1
            if result_status == 'PERMISSION_DENIED' or granted is False:
                self._permission_denied_total += 1

            # Resource types
            if 'APIKey' in method or 'ApiKey' in method:
                self._apikey_total += 1
            if 'Topic' in method:
                self._topic_total += 1
            if 'Cluster' in method:
                self._cluster_total += 1

            # Track per-principal activity (bounded LRUCache prevents memory leaks)
            principal = event.get('principal')
            if principal:
                key = sanitize_label(str(principal), 100)
                self._events_by_principal[key] = self._events_by_principal.get(key, 0) + 1

    def record_anomaly(self, anomaly_type: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Record an anomaly detection event."""
        with self._lock:
            self._anomalies_total += 1
            key = sanitize_label(anomaly_type)
            self._anomalies_by_type[key] = self._anomalies_by_type.get(key, 0) + 1

    def record_routing(self, topic: str, dry_run: bool = False) -> None:
        """Record a routing event."""
        with self._lock:
            key = sanitize_label(topic)
            self._routed_by_topic[key] = self._routed_by_topic.get(key, 0) + 1
            if dry_run:
                self._routing_dry_run_total += 1

    def record_schema_registry_failure(self) -> None:
        """Record a Schema Registry failure."""
        with self._lock:
            self._schema_registry_failures_total += 1

    def format_prometheus(self) -> str:
        """Format metrics in Prometheus exposition format."""
        lines = []
        with self._lock:
            # Severity metrics
            lines.append("# HELP audit_events_by_severity Audit events by severity level")
            lines.append("# TYPE audit_events_by_severity counter")
            for severity, count in self._by_severity.items():
                lines.append(f'audit_events_by_severity{{severity="{sanitize_label(severity)}"}} {count}')

            # Total by severity for convenience
            lines.append("# HELP audit_events_critical_total Critical severity events")
            lines.append("# TYPE audit_events_critical_total counter")
            lines.append(f"audit_events_critical_total {self._by_severity.get('CRITICAL', 0)}")

            lines.append("# HELP audit_events_high_total High severity events")
            lines.append("# TYPE audit_events_high_total counter")
            lines.append(f"audit_events_high_total {self._by_severity.get('HIGH', 0)}")

            lines.append("# HELP audit_events_medium_total Medium severity events")
            lines.append("# TYPE audit_events_medium_total counter")
            lines.append(f"audit_events_medium_total {self._by_severity.get('MEDIUM', 0)}")

            lines.append("# HELP audit_events_low_total Low severity events")
            lines.append("# TYPE audit_events_low_total counter")
            lines.append(f"audit_events_low_total {self._by_severity.get('LOW', 0)}")

            # Operation type metrics
            lines.append("# HELP audit_events_deletions_total Deletion events")
            lines.append("# TYPE audit_events_deletions_total counter")
            lines.append(f"audit_events_deletions_total {self._deletions_total}")

            lines.append("# HELP audit_events_creations_total Creation events")
            lines.append("# TYPE audit_events_creations_total counter")
            lines.append(f"audit_events_creations_total {self._creations_total}")

            lines.append("# HELP audit_events_modifications_total Modification events")
            lines.append("# TYPE audit_events_modifications_total counter")
            lines.append(f"audit_events_modifications_total {self._modifications_total}")

            # Security metrics
            lines.append("# HELP audit_events_auth_failures_total Authentication failures")
            lines.append("# TYPE audit_events_auth_failures_total counter")
            lines.append(f"audit_events_auth_failures_total {self._auth_failures_total}")

            lines.append("# HELP audit_events_permission_denied_total Permission denied events")
            lines.append("# TYPE audit_events_permission_denied_total counter")
            lines.append(f"audit_events_permission_denied_total {self._permission_denied_total}")

            # Resource type metrics
            lines.append("# HELP audit_events_apikey_total API key operations")
            lines.append("# TYPE audit_events_apikey_total counter")
            lines.append(f"audit_events_apikey_total {self._apikey_total}")

            lines.append("# HELP audit_events_topic_total Topic operations")
            lines.append("# TYPE audit_events_topic_total counter")
            lines.append(f"audit_events_topic_total {self._topic_total}")

            lines.append("# HELP audit_events_cluster_total Cluster operations")
            lines.append("# TYPE audit_events_cluster_total counter")
            lines.append(f"audit_events_cluster_total {self._cluster_total}")

            # Anomaly metrics
            lines.append("# HELP audit_anomalies_total Total anomalies detected")
            lines.append("# TYPE audit_anomalies_total counter")
            lines.append(f"audit_anomalies_total {self._anomalies_total}")

            lines.append("# HELP audit_anomalies_by_type Anomalies by type")
            lines.append("# TYPE audit_anomalies_by_type counter")
            for anomaly_type, count in self._anomalies_by_type.items():
                # anomaly_type already sanitized on record
                lines.append(f'audit_anomalies_by_type{{type="{sanitize_label(anomaly_type)}"}} {count}')

            # Routing metrics
            lines.append("# HELP audit_routed_by_topic Events routed to each topic")
            lines.append("# TYPE audit_routed_by_topic counter")
            for topic, count in self._routed_by_topic.items():
                # topic already sanitized on record
                lines.append(f'audit_routed_by_topic{{topic="{sanitize_label(topic)}"}} {count}')

            lines.append("# HELP audit_routing_dry_run_total Events processed in dry-run mode")
            lines.append("# TYPE audit_routing_dry_run_total counter")
            lines.append(f"audit_routing_dry_run_total {self._routing_dry_run_total}")

            # Schema Registry failures
            lines.append("# HELP audit_schema_registry_failures_total Schema Registry connection/load failures")
            lines.append("# TYPE audit_schema_registry_failures_total counter")
            lines.append(f"audit_schema_registry_failures_total {self._schema_registry_failures_total}")

        return "\n".join(lines)

    def get_stats(self) -> Dict[str, Any]:
        """Get metrics as a dictionary."""
        with self._lock:
            return {
                'by_severity': dict(self._by_severity),
                'deletions_total': self._deletions_total,
                'creations_total': self._creations_total,
                'modifications_total': self._modifications_total,
                'auth_failures_total': self._auth_failures_total,
                'permission_denied_total': self._permission_denied_total,
                'apikey_total': self._apikey_total,
                'topic_total': self._topic_total,
                'cluster_total': self._cluster_total,
                'anomalies_total': self._anomalies_total,
                'anomalies_by_type': dict(self._anomalies_by_type),
                'routed_by_topic': dict(self._routed_by_topic),
                'routing_dry_run_total': self._routing_dry_run_total,
                'recent_critical_events': list(self._recent_critical_events),
                'schema_registry_failures_total': self._schema_registry_failures_total,
            }

    def get_top_principals(self, limit: int = 10) -> List[tuple]:
        """Get top principals by event count."""
        with self._lock:
            sorted_principals = sorted(
                self._events_by_principal.items(),
                key=lambda x: x[1],
                reverse=True
            )
            return sorted_principals[:limit]

    def get_recent_critical_events(self) -> List[Dict[str, Any]]:
        """Get recent critical events for context."""
        with self._lock:
            return list(self._recent_critical_events)


# Global instance
audit_event_metrics = AuditEventMetrics()


def record_event_metrics(event: Dict[str, Any]) -> None:
    """Convenience function to record event metrics."""
    audit_event_metrics.record_event(event)


def record_anomaly_metrics(anomaly_type: str, details: Optional[Dict[str, Any]] = None) -> None:
    """Convenience function to record anomaly metrics."""
    audit_event_metrics.record_anomaly(anomaly_type, details)


def record_routing_metrics(topic: str, dry_run: bool = False) -> None:
    """Convenience function to record routing metrics."""
    audit_event_metrics.record_routing(topic, dry_run)


def record_schema_registry_failure() -> None:
    """Convenience function to record Schema Registry failure."""
    audit_event_metrics.record_schema_registry_failure()
