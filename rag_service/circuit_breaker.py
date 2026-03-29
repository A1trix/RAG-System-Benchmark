"""Circuit breaker pattern for OpenAI API calls.

Implements the circuit breaker pattern to prevent cascading failures
when OpenAI API is slow or failing. Matches n8n's error handling approach.
"""

from enum import Enum
from time import monotonic
from typing import Any, Callable, TypeVar
from functools import wraps
import asyncio

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation - requests pass through
    OPEN = "open"          # Failing - requests fail fast
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open (API unavailable)."""
    pass


class CircuitBreaker:
    """Circuit breaker for protecting external API calls.
    
    State transitions:
    - CLOSED -> OPEN: fail_count reaches fail_max
    - OPEN -> HALF_OPEN: reset_timeout seconds elapsed since last failure
    - HALF_OPEN -> CLOSED: successful request
    - HALF_OPEN -> OPEN: request fails
    
    Args:
        fail_max: Maximum consecutive failures before opening circuit
        reset_timeout: Seconds to wait before attempting recovery
        name: Identifier for this circuit breaker (for logging/metrics)
    """
    
    def __init__(self, fail_max: int = 5, reset_timeout: float = 30.0, name: str = "default"):
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout
        self.name = name
        self._state = CircuitState.CLOSED
        self._fail_count = 0
        self._last_failure_time: float | None = None
    
    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._state
    
    @property
    def fail_count(self) -> int:
        """Current consecutive failure count."""
        return self._fail_count
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to try recovery."""
        if self._last_failure_time is None:
            return True
        return (monotonic() - self._last_failure_time) >= self.reset_timeout
    
    def _on_success(self) -> None:
        """Handle successful request."""
        if self._state == CircuitState.HALF_OPEN:
            # Recovery successful - close the circuit
            self._state = CircuitState.CLOSED
            self._fail_count = 0
            self._last_failure_time = None
        elif self._state == CircuitState.CLOSED:
            # Reset failure count on success in closed state
            self._fail_count = 0
    
    def _on_failure(self) -> None:
        """Handle failed request."""
        self._fail_count += 1
        self._last_failure_time = monotonic()
        
        if self._state == CircuitState.HALF_OPEN:
            # Recovery failed - open the circuit again
            self._state = CircuitState.OPEN
        elif self._state == CircuitState.CLOSED and self._fail_count >= self.fail_max:
            # Too many failures - open the circuit
            self._state = CircuitState.OPEN
    
    def can_execute(self) -> bool:
        """Check if request can be executed.
        
        Returns:
            True if request should proceed, False if circuit is open
        """
        if self._state == CircuitState.CLOSED:
            return True
        
        if self._state == CircuitState.OPEN:
            if self._should_attempt_reset():
                # Try to move to half-open state
                self._state = CircuitState.HALF_OPEN
                return True
            return False
        
        # HALF_OPEN - allow one test request
        return True
    
    async def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute function with circuit breaker protection.
        
        Args:
            func: Async function to call
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
            
        Returns:
            Result from func
            
        Raises:
            CircuitBreakerOpenError: If circuit is open and not ready for retry
            Exception: Any exception raised by func (tracked for circuit state)
        """
        if not self.can_execute():
            raise CircuitBreakerOpenError(
                f"Circuit breaker '{self.name}' is OPEN - OpenAI API unavailable"
            )
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise


def circuit_breaker(cb: CircuitBreaker):
    """Decorator to wrap async functions with circuit breaker.
    
    Args:
        cb: CircuitBreaker instance to use
        
    Example:
        >>> cb = CircuitBreaker(fail_max=5, reset_timeout=30)
        >>> @circuit_breaker(cb)
        ... async def api_call():
        ...     return await client.embeddings.create(...)
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await cb.call(func, *args, **kwargs)
        return wrapper
    return decorator


# Global circuit breakers for OpenAI services
_embedding_circuit = CircuitBreaker(fail_max=5, reset_timeout=30.0, name="openai_embeddings")
_llm_circuit = CircuitBreaker(fail_max=5, reset_timeout=30.0, name="openai_llm")


def get_embedding_circuit() -> CircuitBreaker:
    """Get the global embedding circuit breaker."""
    return _embedding_circuit


def get_llm_circuit() -> CircuitBreaker:
    """Get the global LLM circuit breaker."""
    return _llm_circuit


def reset_circuits() -> None:
    """Reset all circuit breakers to CLOSED state (for testing)."""
    _embedding_circuit._state = CircuitState.CLOSED
    _embedding_circuit._fail_count = 0
    _embedding_circuit._last_failure_time = None
    _llm_circuit._state = CircuitState.CLOSED
    _llm_circuit._fail_count = 0
    _llm_circuit._last_failure_time = None
