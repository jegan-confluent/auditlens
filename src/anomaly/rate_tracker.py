"""
Rate-based Anomaly Detection for Confluent Audit Log Intelligence System.

This module tracks event rates per principal and IP address to detect:
- Brute force attacks (rapid authentication failures)
- Activity spikes (unusual burst of operations)
- Unusual patterns (operations at odd hours, from new IPs)
"""

import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Dict, Any, Optional, List, Callable, Tuple

from cachetools import LRUCache

logger = logging.getLogger(__name__)


class AnomalyType(str, Enum):
    """Types of detected anomalies."""
    AUTH_FAILURE_SPIKE = "auth_failure_spike"
    ACTIVITY_SPIKE = "activity_spike"
    NEW_SOURCE_IP = "new_source_ip"
    UNUSUAL_HOUR = "unusual_hour"
    RAPID_DELETIONS = "rapid_deletions"
    API_KEY_ABUSE = "api_key_abuse"


@dataclass
class AnomalyAlert:
    """An anomaly detection alert."""
    anomaly_type: AnomalyType
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    principal: Optional[str]
    source_ip: Optional[str]
    rate: float  # events per minute
    threshold: float
    window_seconds: int
    timestamp: datetime
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'anomaly_type': self.anomaly_type.value,
            'severity': self.severity,
            'principal': self.principal,
            'source_ip': self.source_ip,
            'rate': self.rate,
            'threshold': self.threshold,
            'window_seconds': self.window_seconds,
            'timestamp': self.timestamp.isoformat(),
            'details': self.details,
        }


@dataclass
class RateTrackerConfig:
    """Configuration for rate-based anomaly detection."""

    # Time window for rate calculation (seconds)
    window_seconds: int = 60

    # Auth failure thresholds (per principal per window)
    auth_failure_threshold: int = 10  # 10 failures per minute = likely brute force

    # Activity spike thresholds (per principal per window)
    activity_spike_threshold: int = 100  # 100+ events per minute = unusual

    # Deletion rate thresholds (per principal per window)
    deletion_threshold: int = 5  # 5+ deletions per minute = concerning

    # API key operation thresholds
    api_key_threshold: int = 10  # 10+ API key ops per minute

    # Enable/disable specific detection types
    enable_auth_failure_detection: bool = True
    enable_activity_spike_detection: bool = True
    enable_deletion_detection: bool = True
    enable_api_key_detection: bool = True

    # Cleanup old data after this many seconds
    data_retention_seconds: int = 3600  # 1 hour

    # Principals to skip anomaly detection for entirely (e.g. trusted Flink /
    # Tableflow service accounts that legitimately spike at 100+ ev/s).
    whitelist_principals: tuple = ()

    @classmethod
    def from_env(cls) -> 'RateTrackerConfig':
        """Create configuration from environment variables."""
        # ANOMALY_SPIKE_THRESHOLD is the primary knob (default 500 to avoid
        # alerting on legitimate high-volume service accounts). The legacy
        # ANOMALY_ACTIVITY_SPIKE_THRESHOLD is honored as a fallback.
        spike_env = os.getenv('ANOMALY_SPIKE_THRESHOLD')
        if spike_env is None:
            spike_env = os.getenv('ANOMALY_ACTIVITY_SPIKE_THRESHOLD', '500')
        whitelist_raw = os.getenv('ANOMALY_WHITELIST_PRINCIPALS', '')
        whitelist = tuple(p.strip() for p in whitelist_raw.split(',') if p.strip())
        return cls(
            window_seconds=int(os.getenv('ANOMALY_WINDOW_SECONDS', '60')),
            auth_failure_threshold=int(os.getenv('ANOMALY_AUTH_FAILURE_THRESHOLD', '10')),
            activity_spike_threshold=int(spike_env),
            deletion_threshold=int(os.getenv('ANOMALY_DELETION_THRESHOLD', '5')),
            api_key_threshold=int(os.getenv('ANOMALY_API_KEY_THRESHOLD', '10')),
            enable_auth_failure_detection=os.getenv('ANOMALY_ENABLE_AUTH', 'true').lower() == 'true',
            enable_activity_spike_detection=os.getenv('ANOMALY_ENABLE_ACTIVITY', 'true').lower() == 'true',
            enable_deletion_detection=os.getenv('ANOMALY_ENABLE_DELETION', 'true').lower() == 'true',
            enable_api_key_detection=os.getenv('ANOMALY_ENABLE_API_KEY', 'true').lower() == 'true',
            whitelist_principals=whitelist,
        )


class RateCounter:
    """Thread-safe sliding window rate counter."""

    def __init__(self, window_seconds: int = 60):
        self.window_seconds = window_seconds
        self.events: List[float] = []
        self.lock = Lock()

    def add_event(self, timestamp: Optional[float] = None):
        """Add an event at the given timestamp (or now)."""
        ts = timestamp or time.time()
        with self.lock:
            self.events.append(ts)
            self._cleanup()

    def get_rate(self) -> Tuple[int, float]:
        """Get count and rate (events per minute) in the current window."""
        with self.lock:
            self._cleanup()
            count = len(self.events)
            rate = (count / self.window_seconds) * 60  # per minute
            return count, rate

    def _cleanup(self):
        """Remove events outside the window."""
        cutoff = time.time() - self.window_seconds
        self.events = [ts for ts in self.events if ts > cutoff]


class RateTracker:
    """
    Tracks event rates and detects anomalies.

    Usage:
        config = RateTrackerConfig.from_env()
        tracker = RateTracker(config)

        for event in events:
            alerts = tracker.track_event(event)
            for alert in alerts:
                handle_alert(alert)
    """

    def __init__(
        self,
        config: Optional[RateTrackerConfig] = None,
        on_alert: Optional[Callable[[AnomalyAlert], None]] = None,
    ):
        """
        Initialize the rate tracker.

        Args:
            config: Rate tracker configuration
            on_alert: Optional callback for when anomalies are detected
        """
        self.config = config or RateTrackerConfig.from_env()
        self.on_alert = on_alert

        # Rate counters by principal
        self._principal_activity: Dict[str, RateCounter] = defaultdict(
            lambda: RateCounter(self.config.window_seconds)
        )
        self._principal_auth_failures: Dict[str, RateCounter] = defaultdict(
            lambda: RateCounter(self.config.window_seconds)
        )
        self._principal_deletions: Dict[str, RateCounter] = defaultdict(
            lambda: RateCounter(self.config.window_seconds)
        )
        self._principal_api_key_ops: Dict[str, RateCounter] = defaultdict(
            lambda: RateCounter(self.config.window_seconds)
        )

        # Rate counters by IP
        self._ip_activity: Dict[str, RateCounter] = defaultdict(
            lambda: RateCounter(self.config.window_seconds)
        )
        self._ip_auth_failures: Dict[str, RateCounter] = defaultdict(
            lambda: RateCounter(self.config.window_seconds)
        )

        # Track known IPs per principal (for new source detection)
        # Bounded to prevent memory leaks with high-cardinality principals
        self._known_ips: LRUCache = LRUCache(maxsize=50000)

        # Track alerts to prevent duplicate alerting
        self._recent_alerts: Dict[str, float] = {}
        self._alert_cooldown = 300  # 5 minutes between same alerts

        self._lock = Lock()

        logger.info(
            f"RateTracker initialized with window={self.config.window_seconds}s, "
            f"auth_threshold={self.config.auth_failure_threshold}, "
            f"activity_threshold={self.config.activity_spike_threshold}"
        )

    def track_event(self, event: Dict[str, Any]) -> List[AnomalyAlert]:
        """
        Track an event and check for anomalies.

        Args:
            event: The audit event to track

        Returns:
            List of anomaly alerts (may be empty)
        """
        alerts = []

        principal = event.get('principal', '')
        client_ip = event.get('clientIp', '')
        method_name = event.get('methodName', '')
        result_status = str(event.get('resultStatus', '')).upper()
        granted = event.get('granted')

        if not principal:
            return alerts

        if principal in self.config.whitelist_principals:
            return alerts

        # Track general activity
        self._principal_activity[principal].add_event()
        if client_ip:
            self._ip_activity[client_ip].add_event()

        # Check for activity spike
        if self.config.enable_activity_spike_detection:
            alert = self._check_activity_spike(principal, client_ip)
            if alert:
                alerts.append(alert)

        # Track auth failures
        is_auth_failure = (
            result_status in ('UNAUTHENTICATED', 'PERMISSION_DENIED', 'UNAUTHORIZED') or
            granted is False
        )
        if is_auth_failure:
            self._principal_auth_failures[principal].add_event()
            if client_ip:
                self._ip_auth_failures[client_ip].add_event()

            if self.config.enable_auth_failure_detection:
                alert = self._check_auth_failure_spike(principal, client_ip)
                if alert:
                    alerts.append(alert)

        # Track deletions
        is_deletion = 'delete' in method_name.lower()
        if is_deletion:
            self._principal_deletions[principal].add_event()

            if self.config.enable_deletion_detection:
                alert = self._check_deletion_spike(principal, client_ip)
                if alert:
                    alerts.append(alert)

        # Track API key operations
        is_api_key_op = 'apikey' in method_name.lower() or 'api_key' in method_name.lower()
        if is_api_key_op:
            self._principal_api_key_ops[principal].add_event()

            if self.config.enable_api_key_detection:
                alert = self._check_api_key_abuse(principal, client_ip)
                if alert:
                    alerts.append(alert)

        # Check for new source IP
        if client_ip and principal:
            known_ips_for_principal = self._known_ips.get(principal, set())
            if client_ip not in known_ips_for_principal:
                # First time seeing this IP for this principal
                if len(known_ips_for_principal) > 0:
                    # They have a history of IPs, this is a new one
                    alert = self._create_new_ip_alert(principal, client_ip, known_ips_for_principal)
                    if alert and self._should_alert(alert):
                        alerts.append(alert)
                # Update the set (create new if not exists)
                new_ips = known_ips_for_principal.copy() if known_ips_for_principal else set()
                new_ips.add(client_ip)
                # Limit IPs per principal to prevent memory issues
                if len(new_ips) > 100:
                    # Keep most recent 100 IPs (approximation - just trim)
                    new_ips = set(list(new_ips)[-100:])
                self._known_ips[principal] = new_ips

        # Trigger callbacks
        for alert in alerts:
            if self.on_alert:
                try:
                    self.on_alert(alert)
                except Exception as e:
                    logger.error(f"Error in alert callback: {e}")

        return alerts

    def _check_activity_spike(
        self, principal: str, client_ip: Optional[str]
    ) -> Optional[AnomalyAlert]:
        """Check for activity spike anomaly."""
        count, rate = self._principal_activity[principal].get_rate()

        if count >= self.config.activity_spike_threshold:
            alert = AnomalyAlert(
                anomaly_type=AnomalyType.ACTIVITY_SPIKE,
                severity='HIGH',
                principal=principal,
                source_ip=client_ip,
                rate=rate,
                threshold=self.config.activity_spike_threshold,
                window_seconds=self.config.window_seconds,
                timestamp=datetime.now(timezone.utc),
                details={'event_count': count},
            )
            if self._should_alert(alert):
                return alert
        return None

    def _check_auth_failure_spike(
        self, principal: str, client_ip: Optional[str]
    ) -> Optional[AnomalyAlert]:
        """Check for authentication failure spike (brute force)."""
        count, rate = self._principal_auth_failures[principal].get_rate()

        if count >= self.config.auth_failure_threshold:
            alert = AnomalyAlert(
                anomaly_type=AnomalyType.AUTH_FAILURE_SPIKE,
                severity='CRITICAL',
                principal=principal,
                source_ip=client_ip,
                rate=rate,
                threshold=self.config.auth_failure_threshold,
                window_seconds=self.config.window_seconds,
                timestamp=datetime.now(timezone.utc),
                details={'failure_count': count},
            )
            if self._should_alert(alert):
                return alert
        return None

    def _check_deletion_spike(
        self, principal: str, client_ip: Optional[str]
    ) -> Optional[AnomalyAlert]:
        """Check for rapid deletion anomaly."""
        count, rate = self._principal_deletions[principal].get_rate()

        if count >= self.config.deletion_threshold:
            alert = AnomalyAlert(
                anomaly_type=AnomalyType.RAPID_DELETIONS,
                severity='CRITICAL',
                principal=principal,
                source_ip=client_ip,
                rate=rate,
                threshold=self.config.deletion_threshold,
                window_seconds=self.config.window_seconds,
                timestamp=datetime.now(timezone.utc),
                details={'deletion_count': count},
            )
            if self._should_alert(alert):
                return alert
        return None

    def _check_api_key_abuse(
        self, principal: str, client_ip: Optional[str]
    ) -> Optional[AnomalyAlert]:
        """Check for excessive API key operations."""
        count, rate = self._principal_api_key_ops[principal].get_rate()

        if count >= self.config.api_key_threshold:
            alert = AnomalyAlert(
                anomaly_type=AnomalyType.API_KEY_ABUSE,
                severity='HIGH',
                principal=principal,
                source_ip=client_ip,
                rate=rate,
                threshold=self.config.api_key_threshold,
                window_seconds=self.config.window_seconds,
                timestamp=datetime.now(timezone.utc),
                details={'api_key_op_count': count},
            )
            if self._should_alert(alert):
                return alert
        return None

    def _create_new_ip_alert(
        self, principal: str, client_ip: str, known_ips: set
    ) -> AnomalyAlert:
        """Create an alert for a new source IP."""
        return AnomalyAlert(
            anomaly_type=AnomalyType.NEW_SOURCE_IP,
            severity='MEDIUM',
            principal=principal,
            source_ip=client_ip,
            rate=0,
            threshold=0,
            window_seconds=0,
            timestamp=datetime.now(timezone.utc),
            details={
                'known_ips': list(known_ips)[:10],  # Limit to 10 for alert payload
                'new_ip': client_ip,
            },
        )

    def _should_alert(self, alert: AnomalyAlert) -> bool:
        """Check if we should emit this alert (prevent spam)."""
        # Create a unique key for this alert type
        key = f"{alert.anomaly_type.value}:{alert.principal}:{alert.source_ip}"

        with self._lock:
            now = time.time()

            # Check if we recently alerted for this
            if key in self._recent_alerts:
                if now - self._recent_alerts[key] < self._alert_cooldown:
                    return False

            self._recent_alerts[key] = now

            # Cleanup old entries
            cutoff = now - self._alert_cooldown * 2
            self._recent_alerts = {
                k: v for k, v in self._recent_alerts.items() if v > cutoff
            }

            return True

    def get_stats(self) -> Dict[str, Any]:
        """Get current tracking statistics."""
        return {
            'tracked_principals': len(self._principal_activity),
            'tracked_ips': len(self._ip_activity),
            'known_ip_mappings': sum(len(ips) for ips in self._known_ips.values() if isinstance(ips, set)),
            'recent_alerts': len(self._recent_alerts),
        }

    def get_principal_rates(self, principal: str) -> Dict[str, float]:
        """Get current rates for a specific principal."""
        _, activity_rate = self._principal_activity[principal].get_rate()
        _, auth_failure_rate = self._principal_auth_failures[principal].get_rate()
        _, deletion_rate = self._principal_deletions[principal].get_rate()
        _, api_key_rate = self._principal_api_key_ops[principal].get_rate()

        return {
            'activity_rate': activity_rate,
            'auth_failure_rate': auth_failure_rate,
            'deletion_rate': deletion_rate,
            'api_key_rate': api_key_rate,
        }

    def cleanup(self):
        """Clean up old tracking data."""
        # This can be called periodically to free memory
        # The RateCounter automatically cleans up on access
        # Here we clean up principals/IPs with no recent activity

        now = time.time()
        cutoff = now - self.config.data_retention_seconds

        with self._lock:
            # Clean up empty counters
            for counters_dict in [
                self._principal_activity,
                self._principal_auth_failures,
                self._principal_deletions,
                self._principal_api_key_ops,
                self._ip_activity,
                self._ip_auth_failures,
            ]:
                empty_keys = []
                for key, counter in counters_dict.items():
                    count, _ = counter.get_rate()
                    if count == 0:
                        empty_keys.append(key)
                for key in empty_keys:
                    del counters_dict[key]
