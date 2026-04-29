"""
Prometheus metrics collection and exposition.

Exposes metrics in Prometheus format at /metrics endpoint.
Supports optional authentication via Bearer token or Basic auth.
"""

import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, Optional, Set


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

logger = logging.getLogger(__name__)


@dataclass
class MetricValue:
    """A single metric value with labels."""
    name: str
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    metric_type: str = "gauge"  # gauge, counter, histogram
    help_text: str = ""


class MetricsCollector:
    """
    Collects and exposes metrics in Prometheus format.

    Usage:
        collector = MetricsCollector()
        collector.set_gauge("my_metric", 42, {"label": "value"})
        collector.inc_counter("requests_total")
    """

    def __init__(self):
        self._gauges: Dict[str, MetricValue] = {}
        self._counters: Dict[str, MetricValue] = {}
        self._lock = threading.Lock()
        self._start_time = time.time()

        # Register default metrics
        self._register_default_metrics()

    def _register_default_metrics(self) -> None:
        """Register default application metrics."""
        self.register_gauge(
            "audit_forwarder_uptime_seconds",
            "Uptime of the forwarder in seconds",
        )
        self.register_counter(
            "audit_forwarder_processed_messages_total",
            "Total number of messages processed",
        )
        self.register_gauge(
            "audit_forwarder_processing_rate_per_second",
            "Rate of messages processed per second",
        )
        self.register_counter(
            "audit_forwarder_error_count_total",
            "Total number of processing errors",
        )
        self.register_gauge(
            "audit_forwarder_idle_seconds",
            "Seconds since last message was processed",
        )
        self.register_gauge(
            "audit_forwarder_consumer_lag_total",
            "Total consumer lag across all partitions",
        )
        self.register_gauge(
            "audit_forwarder_consumer_lag",
            "Consumer lag by partition",
        )

    def register_gauge(self, name: str, help_text: str = "") -> None:
        """Register a gauge metric."""
        with self._lock:
            self._gauges[name] = MetricValue(
                name=name,
                value=0,
                metric_type="gauge",
                help_text=help_text,
            )

    def register_counter(self, name: str, help_text: str = "") -> None:
        """Register a counter metric."""
        with self._lock:
            self._counters[name] = MetricValue(
                name=name,
                value=0,
                metric_type="counter",
                help_text=help_text,
            )

    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Set a gauge metric value."""
        with self._lock:
            key = self._make_key(name, labels)
            self._gauges[key] = MetricValue(
                name=name,
                value=value,
                labels=labels or {},
                metric_type="gauge",
                help_text=self._gauges.get(name, MetricValue(name, 0)).help_text,
            )

    def inc_counter(self, name: str, value: float = 1, labels: Optional[Dict[str, str]] = None) -> None:
        """Increment a counter metric."""
        with self._lock:
            key = self._make_key(name, labels)
            if key not in self._counters:
                self._counters[key] = MetricValue(
                    name=name,
                    value=0,
                    labels=labels or {},
                    metric_type="counter",
                    help_text=self._counters.get(name, MetricValue(name, 0)).help_text,
                )
            self._counters[key].value += value

    def get_counter(self, name: str, labels: Optional[Dict[str, str]] = None) -> float:
        """Get a counter value."""
        with self._lock:
            key = self._make_key(name, labels)
            return self._counters.get(key, MetricValue(name, 0)).value

    def _make_key(self, name: str, labels: Optional[Dict[str, str]]) -> str:
        """Create a unique key for a metric with labels."""
        if not labels:
            return name
        # Sanitize label values to prevent injection
        label_str = ",".join(f'{k}="{sanitize_label(v)}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def format_prometheus(self) -> str:
        """Format all metrics in Prometheus exposition format."""
        lines = []

        with self._lock:
            # Update uptime
            self._gauges["audit_forwarder_uptime_seconds"] = MetricValue(
                name="audit_forwarder_uptime_seconds",
                value=time.time() - self._start_time,
                metric_type="gauge",
                help_text="Uptime of the forwarder in seconds",
            )

            # Group metrics by base name
            all_metrics = {}
            for metric in list(self._gauges.values()) + list(self._counters.values()):
                if metric.name not in all_metrics:
                    all_metrics[metric.name] = {
                        "type": metric.metric_type,
                        "help": metric.help_text,
                        "values": [],
                    }
                all_metrics[metric.name]["values"].append(metric)

            # Format each metric group
            for name, data in sorted(all_metrics.items()):
                if data["help"]:
                    lines.append(f"# HELP {name} {data['help']}")
                lines.append(f"# TYPE {name} {data['type']}")

                for metric in data["values"]:
                    if metric.labels:
                        # Sanitize all label values to prevent injection
                        label_str = ",".join(f'{k}="{sanitize_label(v)}"' for k, v in sorted(metric.labels.items()))
                        lines.append(f"{metric.name}{{{label_str}}} {metric.value}")
                    else:
                        lines.append(f"{metric.name} {metric.value}")

        return "\n".join(lines)

    def get_metrics_dict(self) -> Dict[str, Any]:
        """Get all metrics as a dictionary."""
        with self._lock:
            return {
                "uptime_seconds": time.time() - self._start_time,
                "gauges": {k: v.value for k, v in self._gauges.items()},
                "counters": {k: v.value for k, v in self._counters.items()},
            }


@dataclass
class MetricsAuthConfig:
    """
    Authentication configuration for metrics endpoint.

    Supports:
    - Bearer token auth (recommended for Prometheus)
    - Basic auth (username/password)
    - IP allowlist (optional additional security)

    Environment variables:
        METRICS_AUTH_ENABLED: Enable authentication (default: false for backward compat)
        METRICS_AUTH_TOKEN: Bearer token for authentication
        METRICS_AUTH_USERNAME: Username for basic auth
        METRICS_AUTH_PASSWORD: Password for basic auth
        METRICS_AUTH_ALLOWED_IPS: Comma-separated list of allowed IPs (optional)
    """
    enabled: bool = False
    bearer_token: Optional[str] = None
    basic_username: Optional[str] = None
    basic_password: Optional[str] = None
    allowed_ips: Set[str] = field(default_factory=set)

    @classmethod
    def from_env(cls) -> "MetricsAuthConfig":
        """Load configuration from environment variables."""
        enabled = os.getenv("METRICS_AUTH_ENABLED", "false").lower() in ("true", "1", "yes")

        # Load credentials
        bearer_token = os.getenv("METRICS_AUTH_TOKEN")
        basic_username = os.getenv("METRICS_AUTH_USERNAME")
        basic_password = os.getenv("METRICS_AUTH_PASSWORD")

        # Load IP allowlist
        allowed_ips_str = os.getenv("METRICS_AUTH_ALLOWED_IPS", "")
        allowed_ips = set(ip.strip() for ip in allowed_ips_str.split(",") if ip.strip())

        # Always allow localhost
        allowed_ips.update(["127.0.0.1", "::1", "localhost"])

        config = cls(
            enabled=enabled,
            bearer_token=bearer_token,
            basic_username=basic_username,
            basic_password=basic_password,
            allowed_ips=allowed_ips,
        )

        if enabled and not (bearer_token or (basic_username and basic_password)):
            logger.warning(
                "Metrics auth enabled but no credentials configured. "
                "Set METRICS_AUTH_TOKEN or METRICS_AUTH_USERNAME/PASSWORD"
            )

        return config

    def generate_token(self) -> str:
        """Generate a secure random token for metrics authentication."""
        return secrets.token_urlsafe(32)


class MetricsHandler(BaseHTTPRequestHandler):
    """
    HTTP handler for metrics endpoint with optional authentication.

    Supports:
    - Bearer token: Authorization: Bearer <token>
    - Basic auth: Authorization: Basic <base64(user:pass)>
    - IP allowlist: Only allow requests from specific IPs
    """

    collector: Optional[MetricsCollector] = None
    auth_config: Optional[MetricsAuthConfig] = None

    def _check_auth(self) -> bool:
        """
        Check if the request is authenticated.

        Returns True if:
        - Auth is disabled
        - Client IP is in allowlist and no other auth configured
        - Valid Bearer token provided
        - Valid Basic auth credentials provided
        """
        if not self.auth_config or not self.auth_config.enabled:
            return True

        # Check IP allowlist
        client_ip = self.client_address[0]
        if client_ip in self.auth_config.allowed_ips:
            # If only IP allowlist is configured (no token/basic), allow
            if not self.auth_config.bearer_token and not self.auth_config.basic_username:
                return True

        # Get Authorization header
        auth_header = self.headers.get("Authorization", "")

        # Check Bearer token
        if self.auth_config.bearer_token:
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                # Use constant-time comparison to prevent timing attacks
                if hmac.compare_digest(token, self.auth_config.bearer_token):
                    return True

        # Check Basic auth
        if self.auth_config.basic_username and self.auth_config.basic_password:
            if auth_header.startswith("Basic "):
                try:
                    decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                    username, password = decoded.split(":", 1)
                    if (hmac.compare_digest(username, self.auth_config.basic_username) and
                        hmac.compare_digest(password, self.auth_config.basic_password)):
                        return True
                except (ValueError, UnicodeDecodeError):
                    pass

        return False

    def _send_unauthorized(self) -> None:
        """Send 401 Unauthorized response."""
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Bearer realm="metrics"')
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Unauthorized")

    def do_GET(self) -> None:
        """Handle GET requests."""
        # Check authentication first
        if not self._check_auth():
            logger.warning(f"Unauthorized metrics access attempt from {self.client_address[0]}")
            self._send_unauthorized()
            return

        if self.path == "/metrics":
            if self.collector:
                content = self.collector.format_prometheus()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(content.encode())
            else:
                self.send_response(500)
                self.end_headers()
        elif self.path == "/health":
            # Health endpoint - always accessible for load balancers
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "healthy"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress HTTP server logs."""
        pass


class MetricsServer:
    """
    HTTP server for exposing Prometheus metrics.

    Supports optional authentication via Bearer token or Basic auth.
    Authentication is disabled by default for backward compatibility.

    To enable authentication, set:
        METRICS_AUTH_ENABLED=true
        METRICS_AUTH_TOKEN=<your-secret-token>

    Or for basic auth:
        METRICS_AUTH_ENABLED=true
        METRICS_AUTH_USERNAME=prometheus
        METRICS_AUTH_PASSWORD=<your-secret-password>

    Configure Prometheus to use the same credentials:
        scrape_configs:
          - job_name: 'audit-forwarder'
            authorization:
              type: Bearer
              credentials: <your-secret-token>
    """

    def __init__(
        self,
        collector: MetricsCollector,
        port: int = 8000,
        auth_config: Optional[MetricsAuthConfig] = None,
    ):
        self.collector = collector
        self.port = port
        self.auth_config = auth_config or MetricsAuthConfig.from_env()
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the metrics server."""
        MetricsHandler.collector = self.collector
        MetricsHandler.auth_config = self.auth_config
        self._server = HTTPServer(("0.0.0.0", self.port), MetricsHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        auth_status = "enabled" if self.auth_config.enabled else "disabled (set METRICS_AUTH_ENABLED=true)"
        logger.info(f"Metrics server started on port {self.port}, auth: {auth_status}")

    def stop(self) -> None:
        """Stop the metrics server."""
        if self._server:
            self._server.shutdown()
            logger.info("Metrics server stopped")
