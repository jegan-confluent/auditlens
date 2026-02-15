"""Parser for Prometheus metrics from the audit forwarder."""

import re
import requests
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class MetricValue:
    """Represents a single metric value with labels."""
    name: str
    value: float
    labels: Dict[str, str]
    help_text: str = ""
    metric_type: str = "gauge"


def parse_prometheus_text(text: str) -> List[MetricValue]:
    """
    Parse Prometheus text format into MetricValue objects.

    Args:
        text: Raw Prometheus metrics text

    Returns:
        List of MetricValue objects
    """
    metrics = []
    current_help = {}
    current_type = {}

    for line in text.strip().split('\n'):
        line = line.strip()

        if not line or line.startswith('#'):
            # Parse HELP and TYPE comments
            if line.startswith('# HELP'):
                parts = line[7:].split(' ', 1)
                if len(parts) == 2:
                    current_help[parts[0]] = parts[1]
            elif line.startswith('# TYPE'):
                parts = line[7:].split(' ', 1)
                if len(parts) == 2:
                    current_type[parts[0]] = parts[1]
            continue

        # Parse metric line: metric_name{label1="value1",label2="value2"} value
        match = re.match(r'^(\w+)(?:\{([^}]*)\})?\s+([0-9eE.+-]+|NaN|Inf|-Inf)$', line)
        if match:
            name = match.group(1)
            labels_str = match.group(2) or ""
            value_str = match.group(3)

            # Parse labels
            labels = {}
            if labels_str:
                for label_match in re.finditer(r'(\w+)="([^"]*)"', labels_str):
                    labels[label_match.group(1)] = label_match.group(2)

            # Parse value
            try:
                if value_str in ('NaN', 'Inf', '-Inf'):
                    value = float(value_str)
                else:
                    value = float(value_str)
            except ValueError:
                continue

            metrics.append(MetricValue(
                name=name,
                value=value,
                labels=labels,
                help_text=current_help.get(name, ""),
                metric_type=current_type.get(name, "gauge"),
            ))

    return metrics


def fetch_metrics(url: str = "http://localhost:8003/metrics", timeout: int = 5) -> Optional[List[MetricValue]]:
    """
    Fetch and parse metrics from the forwarder.

    Args:
        url: Metrics endpoint URL
        timeout: Request timeout in seconds

    Returns:
        List of MetricValue objects or None if fetch failed
    """
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return parse_prometheus_text(response.text)
    except requests.RequestException:
        return None


def get_metrics_dict(url: str = "http://localhost:8003/metrics") -> Dict[str, Any]:
    """
    Fetch metrics and return as a simple dictionary.

    Args:
        url: Metrics endpoint URL

    Returns:
        Dictionary with metric names as keys
    """
    metrics = fetch_metrics(url)
    if not metrics:
        return {}

    result = {}
    for m in metrics:
        # For metrics without labels, use simple name
        if not m.labels:
            result[m.name] = m.value
        else:
            # For metrics with labels, create nested structure
            if m.name not in result:
                result[m.name] = {}
            label_key = ','.join(f'{k}={v}' for k, v in sorted(m.labels.items()))
            result[m.name][label_key] = m.value

    return result


def get_forwarder_status(url: str = "http://localhost:8003/metrics") -> Dict[str, Any]:
    """
    Get a summary of forwarder status from metrics.

    Args:
        url: Metrics endpoint URL

    Returns:
        Dictionary with status information
    """
    metrics = fetch_metrics(url)
    if not metrics:
        return {
            'status': 'unreachable',
            'last_check': datetime.now().isoformat(),
            'error': 'Could not connect to metrics endpoint',
        }

    metrics_dict = {m.name: m.value for m in metrics if not m.labels}

    return {
        'status': 'running',
        'last_check': datetime.now().isoformat(),
        'events_processed': int(metrics_dict.get('audit_events_processed_total', 0)),
        'events_forwarded': int(metrics_dict.get('audit_events_forwarded_total', 0)),
        'errors': int(metrics_dict.get('audit_errors_total', 0)),
        'delivery_failures': int(metrics_dict.get('audit_delivery_failures_total', 0)),
        'anomalies_detected': int(metrics_dict.get('audit_anomalies_detected_total', 0)),
        'uptime_seconds': metrics_dict.get('process_start_time_seconds', 0),
    }


def get_criticality_distribution(url: str = "http://localhost:8003/metrics") -> Dict[str, int]:
    """
    Get event counts by criticality level from metrics.

    Args:
        url: Metrics endpoint URL

    Returns:
        Dictionary mapping criticality level to count
    """
    metrics = fetch_metrics(url)
    if not metrics:
        return {}

    distribution = {}
    for m in metrics:
        if m.name == 'audit_events_by_criticality':
            level = m.labels.get('criticality', 'unknown')
            distribution[level] = int(m.value)

    return distribution


def get_method_distribution(url: str = "http://localhost:8003/metrics") -> Dict[str, int]:
    """
    Get event counts by method name from metrics.

    Args:
        url: Metrics endpoint URL

    Returns:
        Dictionary mapping method name to count
    """
    metrics = fetch_metrics(url)
    if not metrics:
        return {}

    distribution = {}
    for m in metrics:
        if m.name == 'audit_events_by_method':
            method = m.labels.get('method', 'unknown')
            distribution[method] = int(m.value)

    return distribution


def get_anomaly_counts(url: str = "http://localhost:8003/metrics") -> Dict[str, int]:
    """
    Get anomaly counts by type from metrics.

    Args:
        url: Metrics endpoint URL

    Returns:
        Dictionary mapping anomaly type to count
    """
    metrics = fetch_metrics(url)
    if not metrics:
        return {}

    anomalies = {}
    for m in metrics:
        if m.name == 'audit_anomalies_by_type':
            anomaly_type = m.labels.get('type', 'unknown')
            anomalies[anomaly_type] = int(m.value)

    return anomalies


def get_rate_metrics(url: str = "http://localhost:8003/metrics") -> Dict[str, float]:
    """
    Get rate-based metrics (events per second, etc.).

    Args:
        url: Metrics endpoint URL

    Returns:
        Dictionary with rate metrics
    """
    metrics = fetch_metrics(url)
    if not metrics:
        return {}

    rates = {}
    for m in metrics:
        if 'rate' in m.name.lower() or 'per_second' in m.name.lower():
            rates[m.name] = m.value

    return rates
