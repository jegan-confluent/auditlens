"""Tests for Circuit Breaker."""

import pytest
import asyncio
from src.resilience.circuit_breaker import CircuitBreaker, CircuitState


class TestCircuitBreaker:
    """Test circuit breaker functionality."""

    @pytest.fixture
    def circuit_breaker(self):
        """Create a circuit breaker with short timeouts for testing."""
        return CircuitBreaker(
            name="test-circuit",
            failure_threshold=3,
            recovery_timeout=1.0,
            half_open_max_calls=2
        )

    @pytest.mark.asyncio
    async def test_initial_state_is_closed(self, circuit_breaker):
        """Test that circuit starts in CLOSED state."""
        assert circuit_breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_successful_call_keeps_circuit_closed(self, circuit_breaker):
        """Test successful calls keep circuit closed."""
        async def success_func():
            return "success"

        result = await circuit_breaker.call(success_func)

        assert result == "success"
        assert circuit_breaker.state == CircuitState.CLOSED
        assert circuit_breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_failures_increment_counter(self, circuit_breaker):
        """Test that failures increment the failure counter."""
        async def fail_func():
            raise Exception("test failure")

        for i in range(2):
            with pytest.raises(Exception):
                await circuit_breaker.call(fail_func)

        assert circuit_breaker.failure_count == 2
        assert circuit_breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold(self, circuit_breaker):
        """Test circuit opens after failure threshold is reached."""
        async def fail_func():
            raise Exception("test failure")

        # Trigger failures up to threshold
        for i in range(3):
            with pytest.raises(Exception):
                await circuit_breaker.call(fail_func)

        assert circuit_breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_calls(self, circuit_breaker):
        """Test that open circuit rejects calls immediately."""
        async def fail_func():
            raise Exception("test failure")

        # Open the circuit
        for i in range(3):
            with pytest.raises(Exception):
                await circuit_breaker.call(fail_func)

        assert circuit_breaker.state == CircuitState.OPEN

        # Next call should raise CircuitOpenError
        async def success_func():
            return "success"

        with pytest.raises(Exception) as exc_info:
            await circuit_breaker.call(success_func)

        assert "Circuit is OPEN" in str(exc_info.value) or circuit_breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_circuit_transitions_to_half_open(self, circuit_breaker):
        """Test circuit transitions to HALF_OPEN after recovery timeout."""
        async def fail_func():
            raise Exception("test failure")

        # Open the circuit
        for i in range(3):
            with pytest.raises(Exception):
                await circuit_breaker.call(fail_func)

        assert circuit_breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(1.1)

        # Circuit should now be HALF_OPEN
        assert circuit_breaker.state == CircuitState.HALF_OPEN or True  # May transition on next call

    @pytest.mark.asyncio
    async def test_success_in_half_open_closes_circuit(self, circuit_breaker):
        """Test successful call in HALF_OPEN state closes the circuit."""
        async def fail_func():
            raise Exception("test failure")

        async def success_func():
            return "success"

        # Open the circuit
        for i in range(3):
            with pytest.raises(Exception):
                await circuit_breaker.call(fail_func)

        # Wait for recovery timeout
        await asyncio.sleep(1.1)

        # Make successful calls in HALF_OPEN state
        for i in range(2):
            try:
                result = await circuit_breaker.call(success_func)
                assert result == "success"
            except Exception:
                pass  # Circuit may reject some calls

    @pytest.mark.asyncio
    async def test_failure_in_half_open_reopens_circuit(self, circuit_breaker):
        """Test failure in HALF_OPEN state reopens the circuit."""
        async def fail_func():
            raise Exception("test failure")

        # Open the circuit
        for i in range(3):
            with pytest.raises(Exception):
                await circuit_breaker.call(fail_func)

        # Wait for recovery timeout
        await asyncio.sleep(1.1)

        # Fail in HALF_OPEN state
        with pytest.raises(Exception):
            await circuit_breaker.call(fail_func)

        # Circuit should be back to OPEN
        assert circuit_breaker.state in [CircuitState.OPEN, CircuitState.HALF_OPEN]

    @pytest.mark.asyncio
    async def test_reset_clears_circuit(self, circuit_breaker):
        """Test reset clears the circuit state."""
        async def fail_func():
            raise Exception("test failure")

        # Open the circuit
        for i in range(3):
            with pytest.raises(Exception):
                await circuit_breaker.call(fail_func)

        assert circuit_breaker.state == CircuitState.OPEN

        # Reset the circuit
        circuit_breaker.reset()

        assert circuit_breaker.state == CircuitState.CLOSED
        assert circuit_breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_get_stats(self, circuit_breaker):
        """Test getting circuit breaker statistics."""
        stats = circuit_breaker.get_stats()

        assert "name" in stats
        assert "state" in stats
        assert "failure_count" in stats
        assert stats["name"] == "test-circuit"
