"""
Circuit Breaker pattern implementation.

Prevents cascading failures by stopping requests to a failing service
and allowing it to recover.
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Callable, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""
    failure_threshold: int = 5  # Failures before opening
    recovery_timeout: float = 30.0  # Seconds before trying half-open
    half_open_requests: int = 3  # Successful requests to close
    failure_window: float = 60.0  # Window for counting failures


@dataclass
class CircuitStats:
    """Circuit breaker statistics."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    state_changes: int = 0
    current_failures: int = 0
    half_open_successes: int = 0


class CircuitBreaker:
    """
    Circuit breaker for protecting against cascading failures.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Service failing, requests rejected immediately
    - HALF_OPEN: Testing recovery, limited requests allowed

    Usage:
        breaker = CircuitBreaker("my-service")

        async def call_service():
            return await breaker.call(actual_service_call)
    """

    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
    ):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._failure_times: list[float] = []
        self._opened_at: Optional[float] = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    @property
    def stats(self) -> CircuitStats:
        """Get circuit statistics."""
        return self._stats

    async def call(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Execute a function through the circuit breaker.

        Raises:
            CircuitOpenError: If circuit is open
            Exception: Any exception from the wrapped function
        """
        async with self._lock:
            self._stats.total_calls += 1

            # Check if we should transition from OPEN to HALF_OPEN
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._transition_to(CircuitState.HALF_OPEN)
                else:
                    self._stats.rejected_calls += 1
                    raise CircuitOpenError(
                        f"Circuit {self.name} is open. "
                        f"Will retry after {self._time_until_reset():.1f}s"
                    )

        # Execute the function
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            await self._record_success()
            return result

        except Exception as e:
            await self._record_failure(e)
            raise

    async def _record_success(self) -> None:
        """Record a successful call."""
        async with self._lock:
            self._stats.successful_calls += 1
            self._stats.last_success_time = datetime.now(timezone.utc)

            if self._state == CircuitState.HALF_OPEN:
                self._stats.half_open_successes += 1
                if self._stats.half_open_successes >= self.config.half_open_requests:
                    self._transition_to(CircuitState.CLOSED)
            elif self._state == CircuitState.CLOSED:
                # Clear failure count on success
                self._stats.current_failures = 0

    async def _record_failure(self, error: Exception) -> None:
        """Record a failed call."""
        async with self._lock:
            self._stats.failed_calls += 1
            self._stats.last_failure_time = datetime.now(timezone.utc)
            self._stats.current_failures += 1

            # Track failure time for windowed counting
            now = time.time()
            self._failure_times.append(now)
            self._cleanup_old_failures(now)

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open goes back to open
                self._transition_to(CircuitState.OPEN)
            elif self._state == CircuitState.CLOSED:
                # Check if we've exceeded threshold in window
                if len(self._failure_times) >= self.config.failure_threshold:
                    self._transition_to(CircuitState.OPEN)

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state."""
        old_state = self._state
        self._state = new_state
        self._stats.state_changes += 1

        logger.info(f"Circuit {self.name}: {old_state.value} -> {new_state.value}")

        if new_state == CircuitState.OPEN:
            self._opened_at = time.time()
        elif new_state == CircuitState.HALF_OPEN:
            self._stats.half_open_successes = 0
        elif new_state == CircuitState.CLOSED:
            self._stats.current_failures = 0
            self._failure_times.clear()

    def _should_attempt_reset(self) -> bool:
        """Check if we should try to reset the circuit."""
        if self._opened_at is None:
            return True
        return time.time() - self._opened_at >= self.config.recovery_timeout

    def _time_until_reset(self) -> float:
        """Get time until circuit will attempt reset."""
        if self._opened_at is None:
            return 0.0
        elapsed = time.time() - self._opened_at
        return max(0.0, self.config.recovery_timeout - elapsed)

    def _cleanup_old_failures(self, now: float) -> None:
        """Remove failures outside the window."""
        cutoff = now - self.config.failure_window
        self._failure_times = [t for t in self._failure_times if t > cutoff]

    def force_open(self) -> None:
        """Manually open the circuit."""
        self._transition_to(CircuitState.OPEN)

    def force_close(self) -> None:
        """Manually close the circuit."""
        self._transition_to(CircuitState.CLOSED)

    def get_status(self) -> dict:
        """Get circuit breaker status."""
        return {
            "name": self.name,
            "state": self._state.value,
            "stats": {
                "total_calls": self._stats.total_calls,
                "successful_calls": self._stats.successful_calls,
                "failed_calls": self._stats.failed_calls,
                "rejected_calls": self._stats.rejected_calls,
                "current_failures": self._stats.current_failures,
                "state_changes": self._stats.state_changes,
            },
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "recovery_timeout": self.config.recovery_timeout,
                "half_open_requests": self.config.half_open_requests,
            },
            "time_until_reset": self._time_until_reset() if self._state == CircuitState.OPEN else None,
        }


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass
