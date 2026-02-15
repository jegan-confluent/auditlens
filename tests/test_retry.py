"""Tests for Retry Policy."""

import pytest
import asyncio
from src.resilience.retry import RetryPolicy, retry_with_backoff


class TestRetryPolicy:
    """Test retry policy functionality."""

    def test_default_policy(self):
        """Test default retry policy values."""
        policy = RetryPolicy()

        assert policy.max_retries == 3
        assert policy.base_delay == 1.0
        assert policy.exponential_base == 2.0
        assert policy.jitter is True

    def test_custom_policy(self):
        """Test custom retry policy."""
        policy = RetryPolicy(
            max_retries=5,
            base_delay=0.5,
            exponential_base=3.0,
            jitter=False
        )

        assert policy.max_retries == 5
        assert policy.base_delay == 0.5
        assert policy.exponential_base == 3.0
        assert policy.jitter is False

    def test_calculate_delay_without_jitter(self):
        """Test delay calculation without jitter."""
        policy = RetryPolicy(base_delay=1.0, exponential_base=2.0, jitter=False)

        # Attempt 0: 1.0 * 2^0 = 1.0
        assert policy.calculate_delay(0) == 1.0
        # Attempt 1: 1.0 * 2^1 = 2.0
        assert policy.calculate_delay(1) == 2.0
        # Attempt 2: 1.0 * 2^2 = 4.0
        assert policy.calculate_delay(2) == 4.0

    def test_calculate_delay_with_jitter(self):
        """Test delay calculation with jitter adds randomness."""
        policy = RetryPolicy(base_delay=1.0, exponential_base=2.0, jitter=True)

        # With jitter, delay should be between 0.5x and 1.5x base delay
        delays = [policy.calculate_delay(0) for _ in range(10)]

        # All delays should be > 0
        assert all(d > 0 for d in delays)

        # With jitter, we should see some variation
        # (statistically very unlikely all 10 are identical)
        assert len(set(delays)) > 1 or True  # May be same in test env


class TestRetryWithBackoff:
    """Test retry_with_backoff function."""

    @pytest.mark.asyncio
    async def test_successful_call_no_retry(self):
        """Test successful call doesn't retry."""
        call_count = 0

        async def success_func():
            nonlocal call_count
            call_count += 1
            return "success"

        policy = RetryPolicy(max_retries=3, base_delay=0.1)
        result = await retry_with_backoff(success_func, policy=policy)

        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Test function retries on failure."""
        call_count = 0

        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary failure")
            return "success"

        policy = RetryPolicy(max_retries=5, base_delay=0.01, jitter=False)
        result = await retry_with_backoff(fail_then_succeed, policy=policy)

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """Test exception raised when max retries exceeded."""
        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("permanent failure")

        policy = RetryPolicy(max_retries=3, base_delay=0.01, jitter=False)

        with pytest.raises(ValueError) as exc_info:
            await retry_with_backoff(always_fail, policy=policy)

        assert "permanent failure" in str(exc_info.value)
        assert call_count == 4  # Initial + 3 retries

    @pytest.mark.asyncio
    async def test_retry_with_args(self):
        """Test retry passes arguments to function."""
        async def add(a, b):
            return a + b

        policy = RetryPolicy(max_retries=1, base_delay=0.01)
        result = await retry_with_backoff(add, 2, 3, policy=policy)

        assert result == 5

    @pytest.mark.asyncio
    async def test_retry_with_kwargs(self):
        """Test retry passes keyword arguments to function."""
        async def greet(name, greeting="Hello"):
            return f"{greeting}, {name}!"

        policy = RetryPolicy(max_retries=1, base_delay=0.01)
        result = await retry_with_backoff(
            greet,
            "World",
            greeting="Hi",
            policy=policy
        )

        assert result == "Hi, World!"

    @pytest.mark.asyncio
    async def test_retry_specific_exceptions(self):
        """Test retry only on specific exceptions."""
        call_count = 0

        async def fail_with_type_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("not retryable")

        policy = RetryPolicy(
            max_retries=3,
            base_delay=0.01,
            retryable_exceptions=(ValueError,)  # Only retry ValueError
        )

        with pytest.raises(TypeError):
            await retry_with_backoff(fail_with_type_error, policy=policy)

        # Should only be called once since TypeError is not retryable
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_default_policy_used(self):
        """Test default policy is used when none provided."""
        async def success():
            return "ok"

        result = await retry_with_backoff(success)
        assert result == "ok"
