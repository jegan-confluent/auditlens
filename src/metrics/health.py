"""
Health check endpoints and monitoring.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, Optional, Callable, List

logger = logging.getLogger(__name__)


def _utc_iso(dt: Optional[datetime] = None) -> str:
    """Return RFC3339 UTC timestamp without duplicating timezone suffixes."""
    ts = dt or datetime.now(timezone.utc)
    return ts.isoformat().replace("+00:00", "Z")


class HealthStatus(str, Enum):
    """Health check status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ComponentHealth:
    """Health status of a component."""
    name: str
    status: HealthStatus
    message: Optional[str] = None
    last_check: Optional[datetime] = None
    details: Optional[Dict[str, Any]] = None


class HealthChecker:
    """
    Health check manager.

    Aggregates health status from multiple components and
    provides endpoints for liveness and readiness probes.
    """

    def __init__(self):
        self._checks: Dict[str, Callable[[], ComponentHealth]] = {}
        self._last_results: Dict[str, ComponentHealth] = {}
        self._start_time = time.time()

    def register_check(self, name: str, check_func: Callable[[], ComponentHealth]) -> None:
        """Register a health check function."""
        self._checks[name] = check_func

    def run_checks(self) -> Dict[str, ComponentHealth]:
        """Run all health checks."""
        results = {}
        for name, check_func in self._checks.items():
            try:
                result = check_func()
                result.last_check = datetime.now(timezone.utc)
                results[name] = result
            except Exception as e:
                results[name] = ComponentHealth(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    message=str(e),
                    last_check=datetime.now(timezone.utc),
                )
        self._last_results = results
        return results

    def get_overall_status(self) -> HealthStatus:
        """Get aggregated health status."""
        if not self._last_results:
            self.run_checks()

        statuses = [c.status for c in self._last_results.values()]

        if all(s == HealthStatus.HEALTHY for s in statuses):
            return HealthStatus.HEALTHY
        elif any(s == HealthStatus.UNHEALTHY for s in statuses):
            return HealthStatus.UNHEALTHY
        else:
            return HealthStatus.DEGRADED

    def get_health_response(self) -> Dict[str, Any]:
        """Get health check response for API."""
        self.run_checks()

        return {
            "status": self.get_overall_status().value,
            "uptime_seconds": time.time() - self._start_time,
            "timestamp": _utc_iso(),
            "components": {
                name: {
                    "status": comp.status.value,
                    "message": comp.message,
                    "last_check": _utc_iso(comp.last_check) if comp.last_check else None,
                    "details": comp.details,
                }
                for name, comp in self._last_results.items()
            },
        }

    def is_healthy(self) -> bool:
        """Check if service is healthy (for liveness probe)."""
        return self.get_overall_status() != HealthStatus.UNHEALTHY

    def is_ready(self) -> bool:
        """Check if service is ready (for readiness probe)."""
        return self.get_overall_status() == HealthStatus.HEALTHY


class HealthHandler(BaseHTTPRequestHandler):
    """HTTP handler for health endpoints."""

    checker: Optional[HealthChecker] = None

    def do_GET(self) -> None:
        """Handle GET requests."""
        if self.path == "/health" or self.path == "/healthz":
            self._handle_health()
        elif self.path == "/ready" or self.path == "/readyz":
            self._handle_ready()
        elif self.path == "/live" or self.path == "/livez":
            self._handle_live()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_health(self) -> None:
        """Full health check response."""
        if not self.checker:
            self.send_response(500)
            self.end_headers()
            return

        response = self.checker.get_health_response()
        status_code = 200 if self.checker.is_healthy() else 503

        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response, indent=2).encode())

    def _handle_ready(self) -> None:
        """Readiness probe."""
        if self.checker and self.checker.is_ready():
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ready")
        else:
            self.send_response(503)
            self.end_headers()

    def _handle_live(self) -> None:
        """Liveness probe."""
        if self.checker and self.checker.is_healthy():
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"alive")
        else:
            self.send_response(503)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress HTTP server logs."""
        pass


class HealthServer:
    """HTTP server for health endpoints."""

    def __init__(self, checker: HealthChecker, port: int = 8001):
        self.checker = checker
        self.port = port
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the health server."""
        HealthHandler.checker = self.checker
        self._server = HTTPServer(("0.0.0.0", self.port), HealthHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(f"Health server started on port {self.port}")

    def stop(self) -> None:
        """Stop the health server."""
        if self._server:
            self._server.shutdown()
            logger.info("Health server stopped")
