"""
Retry patterns with exponential backoff.

Provides configurable retry policies for transient failures.
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Callable, Any, Optional, Type, Tuple
from functools import wraps

logger = logging.getLogger(__name__)


@dataclass
class RetryPolicy:
    """Configuration for retry behavior."""
    max_retries: int = 3
    base_delay: float = 1.0  # Initial delay in seconds
    max_delay: float = 60.0  # Maximum delay between retries
    exponential_base: float = 2.0  # Multiplier for exponential backoff
    jitter: bool = True  # Add randomness to delays
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,)

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for a given attempt number."""
        delay = self.base_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)

        if self.jitter:
            # Add up to 25% jitter
            jitter_range = delay * 0.25
            delay += random.uniform(-jitter_range, jitter_range)

        return max(0, delay)


class RetryExhaustedError(Exception):
    """Raised when all retry attempts are exhausted."""

    def __init__(self, message: str, last_exception: Exception):
        super().__init__(message)
        self.last_exception = last_exception


async def retry_with_backoff(
    func: Callable[..., Any],
    *args: Any,
    policy: Optional[RetryPolicy] = None,
    on_retry: Optional[Callable[[int, Exception, float], None]] = None,
    **kwargs: Any,
) -> Any:
    """
    Execute a function with retry and exponential backoff.

    Args:
        func: Function to execute (sync or async)
        *args: Positional arguments for func
        policy: RetryPolicy configuration
        on_retry: Callback called before each retry (attempt, exception, delay)
        **kwargs: Keyword arguments for func

    Returns:
        Result from successful function execution

    Raises:
        RetryExhaustedError: If all retries are exhausted
    """
    policy = policy or RetryPolicy()
    last_exception: Optional[Exception] = None

    for attempt in range(policy.max_retries + 1):
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)

        except policy.retryable_exceptions as e:
            last_exception = e

            if attempt >= policy.max_retries:
                logger.error(f"Retry exhausted after {attempt + 1} attempts: {e}")
                raise RetryExhaustedError(
                    f"Failed after {attempt + 1} attempts",
                    last_exception,
                )

            delay = policy.get_delay(attempt)

            if on_retry:
                on_retry(attempt, e, delay)

            logger.warning(
                f"Attempt {attempt + 1} failed: {e}. "
                f"Retrying in {delay:.2f}s ({policy.max_retries - attempt} retries left)"
            )

            await asyncio.sleep(delay)


def with_retry(
    policy: Optional[RetryPolicy] = None,
    on_retry: Optional[Callable[[int, Exception, float], None]] = None,
):
    """
    Decorator to add retry behavior to a function.

    Usage:
        @with_retry(RetryPolicy(max_retries=3))
        async def my_function():
            ...
    """
    policy = policy or RetryPolicy()

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await retry_with_backoff(
                func, *args, policy=policy, on_retry=on_retry, **kwargs
            )

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            return asyncio.get_event_loop().run_until_complete(
                retry_with_backoff(func, *args, policy=policy, on_retry=on_retry, **kwargs)
            )

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


class RetryBudget:
    """
    Token bucket for rate-limiting retries across multiple callers.

    Prevents retry storms by limiting total retry attempts.
    """

    def __init__(
        self,
        max_retries_per_second: float = 10.0,
        bucket_size: int = 100,
    ):
        self.max_retries_per_second = max_retries_per_second
        self.bucket_size = bucket_size
        self._tokens = bucket_size
        self._last_refill = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        """
        Try to acquire a retry token.

        Returns True if retry is allowed, False otherwise.
        """
        async with self._lock:
            self._refill()

            if self._tokens >= 1:
                self._tokens -= 1
                return True
            return False

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self._last_refill
        tokens_to_add = elapsed * self.max_retries_per_second

        self._tokens = min(self.bucket_size, self._tokens + tokens_to_add)
        self._last_refill = now

    def get_status(self) -> dict:
        """Get retry budget status."""
        return {
            "available_tokens": self._tokens,
            "bucket_size": self.bucket_size,
            "refill_rate_per_second": self.max_retries_per_second,
        }
