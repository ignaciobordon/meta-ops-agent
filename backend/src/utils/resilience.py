"""
Sprint 3 – BLOQUE 5: Resilience Patterns
safe_call with timeout, exponential backoff retry, and circuit breaker.
Wrap all external calls (Meta API, Anthropic LLM) with these patterns.
"""
import asyncio
import time
import threading
from functools import wraps
from typing import Callable, Any, Optional

from src.utils.logging_config import logger, get_trace_id


class CircuitBreakerOpen(Exception):
    """Raised when the circuit breaker is open and rejecting calls."""
    pass


class CircuitBreaker:
    """
    Simple circuit breaker: opens after N consecutive failures,
    transitions to half-open after cooldown, closes on success.
    Thread-safe.
    """

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 60):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._state = "closed"  # closed | open | half_open
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == "open":
                # Check if cooldown has elapsed → transition to half_open
                if self._last_failure_time and (
                    time.time() - self._last_failure_time >= self.cooldown_seconds
                ):
                    self._state = "half_open"
            return self._state

    def record_success(self):
        with self._lock:
            self._failure_count = 0
            self._state = "closed"

    def record_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self.failure_threshold:
                self._state = "open"

    def allow_request(self) -> bool:
        state = self.state
        if state == "closed":
            return True
        if state == "half_open":
            return True  # Allow one probe request
        return False  # open


async def safe_call(
    func: Callable,
    *args,
    timeout_seconds: float = 30,
    max_retries: int = 3,
    backoff_base: float = 1.0,
    circuit_breaker: Optional[CircuitBreaker] = None,
    **kwargs,
) -> Any:
    """
    Execute an external call with timeout + exponential backoff retry + circuit breaker.

    Args:
        func: The async or sync callable to execute.
        timeout_seconds: Max time per attempt.
        max_retries: Number of retry attempts after initial failure.
        backoff_base: Base delay in seconds (multiplied by 2^attempt).
        circuit_breaker: Optional CircuitBreaker instance.
    """
    trace_id = get_trace_id()

    if circuit_breaker and not circuit_breaker.allow_request():
        raise CircuitBreakerOpen(
            f"Circuit breaker is open, rejecting call to {func.__name__}"
        )

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            if asyncio.iscoroutinefunction(func):
                result = await asyncio.wait_for(
                    func(*args, **kwargs), timeout=timeout_seconds
                )
            else:
                # Run sync function in thread pool with timeout
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: func(*args, **kwargs)),
                    timeout=timeout_seconds,
                )

            # Success
            if circuit_breaker:
                circuit_breaker.record_success()
            return result

        except asyncio.TimeoutError:
            last_error = TimeoutError(
                f"{func.__name__} timed out after {timeout_seconds}s"
            )
            logger.bind(trace_id=trace_id).warning(
                "SAFE_CALL_TIMEOUT | func={} | attempt={}/{} | timeout={}s",
                func.__name__, attempt + 1, max_retries + 1, timeout_seconds,
            )
        except CircuitBreakerOpen:
            raise
        except Exception as e:
            last_error = e
            logger.bind(trace_id=trace_id).warning(
                "SAFE_CALL_ERROR | func={} | attempt={}/{} | error={}",
                func.__name__, attempt + 1, max_retries + 1, str(e),
            )

        # Record failure
        if circuit_breaker:
            circuit_breaker.record_failure()

        # Exponential backoff (skip on last attempt)
        if attempt < max_retries:
            delay = backoff_base * (2 ** attempt)
            await asyncio.sleep(delay)

    # All retries exhausted
    raise last_error


def safe_call_sync(
    func: Callable,
    *args,
    timeout_seconds: float = 30,
    max_retries: int = 3,
    backoff_base: float = 1.0,
    circuit_breaker: Optional[CircuitBreaker] = None,
    **kwargs,
) -> Any:
    """
    Synchronous version of safe_call for use in non-async contexts.
    Uses threading for timeout.
    """
    trace_id = get_trace_id()

    if circuit_breaker and not circuit_breaker.allow_request():
        raise CircuitBreakerOpen(
            f"Circuit breaker is open, rejecting call to {func.__name__}"
        )

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            result = [None]
            error = [None]

            def target():
                try:
                    result[0] = func(*args, **kwargs)
                except Exception as e:
                    error[0] = e

            thread = threading.Thread(target=target)
            thread.start()
            thread.join(timeout=timeout_seconds)

            if thread.is_alive():
                raise TimeoutError(
                    f"{func.__name__} timed out after {timeout_seconds}s"
                )

            if error[0]:
                raise error[0]

            # Success
            if circuit_breaker:
                circuit_breaker.record_success()
            return result[0]

        except CircuitBreakerOpen:
            raise
        except Exception as e:
            last_error = e
            logger.bind(trace_id=trace_id).warning(
                "SAFE_CALL_SYNC_ERROR | func={} | attempt={}/{} | error={}",
                func.__name__, attempt + 1, max_retries + 1, str(e),
            )

        # Record failure
        if circuit_breaker:
            circuit_breaker.record_failure()

        # Exponential backoff (skip on last attempt)
        if attempt < max_retries:
            delay = backoff_base * (2 ** attempt)
            time.sleep(delay)

    raise last_error
