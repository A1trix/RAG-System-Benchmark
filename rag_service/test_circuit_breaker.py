"""Tests for circuit breaker implementation."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
import time

from rag_service.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitBreakerOpenError,
    get_embedding_circuit,
    get_llm_circuit,
    reset_circuits,
)


class TestCircuitBreaker:
    """Test circuit breaker functionality."""
    
    def test_initial_state_is_closed(self):
        """Circuit breaker starts in CLOSED state."""
        cb = CircuitBreaker(fail_max=5, reset_timeout=30)
        assert cb.state == CircuitState.CLOSED
        assert cb.fail_count == 0
    
    def test_success_does_not_change_state(self):
        """Successful calls keep circuit CLOSED."""
        cb = CircuitBreaker(fail_max=5, reset_timeout=30)
        
        async def success():
            return "success"
        
        result = asyncio.run(cb.call(success))
        assert result == "success"
        assert cb.state == CircuitState.CLOSED
        assert cb.fail_count == 0
    
    def test_failures_increment_count(self):
        """Failed calls increment failure count."""
        cb = CircuitBreaker(fail_max=5, reset_timeout=30)
        
        async def fail():
            raise ValueError("test error")
        
        # First failure
        with pytest.raises(ValueError):
            asyncio.run(cb.call(fail))
        
        assert cb.fail_count == 1
        assert cb.state == CircuitState.CLOSED  # Still closed, not at threshold
    
    def test_circuit_opens_after_max_failures(self):
        """Circuit opens after fail_max consecutive failures."""
        cb = CircuitBreaker(fail_max=3, reset_timeout=30)
        
        async def fail():
            raise ValueError("test error")
        
        # Three failures should open the circuit
        for i in range(3):
            with pytest.raises(ValueError):
                asyncio.run(cb.call(fail))
        
        assert cb.state == CircuitState.OPEN
        assert cb.fail_count == 3
    
    def test_open_circuit_raises_circuit_breaker_error(self):
        """Calls to open circuit raise CircuitBreakerOpenError."""
        cb = CircuitBreaker(fail_max=2, reset_timeout=30)
        
        async def fail():
            raise ValueError("test error")
        
        # Open the circuit
        for i in range(2):
            with pytest.raises(ValueError):
                asyncio.run(cb.call(fail))
        
        assert cb.state == CircuitState.OPEN
        
        # Next call should raise CircuitBreakerOpenError immediately
        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            asyncio.run(cb.call(fail))
        
        assert "Circuit breaker" in str(exc_info.value)
        assert "OPEN" in str(exc_info.value)
    
    def test_circuit_half_opens_after_timeout(self):
        """Circuit transitions to HALF_OPEN after reset_timeout."""
        cb = CircuitBreaker(fail_max=2, reset_timeout=0.1)  # 100ms timeout
        
        async def fail():
            raise ValueError("test error")
        
        # Open the circuit
        for i in range(2):
            with pytest.raises(ValueError):
                asyncio.run(cb.call(fail))
        
        assert cb.state == CircuitState.OPEN
        
        # Wait for timeout
        time.sleep(0.15)
        
        # Circuit should be HALF_OPEN now
        assert cb.can_execute()  # Should allow one test request
        assert cb.state == CircuitState.HALF_OPEN
    
    def test_success_in_half_open_closes_circuit(self):
        """Successful call in HALF_OPEN state closes the circuit."""
        cb = CircuitBreaker(fail_max=2, reset_timeout=0.1)
        
        async def fail():
            raise ValueError("test error")
        
        async def success():
            return "success"
        
        # Open the circuit
        for i in range(2):
            with pytest.raises(ValueError):
                asyncio.run(cb.call(fail))
        
        # Wait for timeout
        time.sleep(0.15)
        
        # Successful call in HALF_OPEN should close the circuit
        result = asyncio.run(cb.call(success))
        
        assert result == "success"
        assert cb.state == CircuitState.CLOSED
        assert cb.fail_count == 0
    
    def test_failure_in_half_open_reopens_circuit(self):
        """Failed call in HALF_OPEN state reopens the circuit."""
        cb = CircuitBreaker(fail_max=2, reset_timeout=0.1)
        
        async def fail():
            raise ValueError("test error")
        
        # Open the circuit
        for i in range(2):
            with pytest.raises(ValueError):
                asyncio.run(cb.call(fail))
        
        # Wait for timeout
        time.sleep(0.15)
        
        # Failed call in HALF_OPEN should reopen the circuit
        with pytest.raises(ValueError):
            asyncio.run(cb.call(fail))
        
        assert cb.state == CircuitState.OPEN
    
    def test_global_circuits_have_different_instances(self):
        """Global embedding and LLM circuits are separate."""
        reset_circuits()
        
        embedding_cb = get_embedding_circuit()
        llm_cb = get_llm_circuit()
        
        assert embedding_cb.name == "openai_embeddings"
        assert llm_cb.name == "openai_llm"
        assert embedding_cb is not llm_cb
    
    def test_reset_circuits_clears_all(self):
        """reset_circuits() resets all circuits to CLOSED."""
        cb = CircuitBreaker(fail_max=2, reset_timeout=30)
        
        async def fail():
            raise ValueError("test error")
        
        # Open the circuit
        for i in range(2):
            with pytest.raises(ValueError):
                asyncio.run(cb.call(fail))
        
        assert cb.state == CircuitState.OPEN
        
        # Reset all global circuits (doesn't affect local instances)
        reset_circuits()
        
        # Check that global circuits are reset
        assert get_embedding_circuit().state == CircuitState.CLOSED
        assert get_llm_circuit().state == CircuitState.CLOSED


class TestCircuitBreakerDecorator:
    """Test circuit breaker decorator functionality."""
    
    def test_decorator_wraps_function(self):
        """Decorator successfully wraps async function."""
        cb = CircuitBreaker(fail_max=3, reset_timeout=30)
        
        from rag_service.circuit_breaker import circuit_breaker
        
        @circuit_breaker(cb)
        async def my_api_call(arg1: str, arg2: int = 0) -> str:
            return f"result: {arg1}, {arg2}"
        
        result = asyncio.run(my_api_call("test", arg2=42))
        assert result == "result: test, 42"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
