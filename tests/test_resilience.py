"""
Sprint 3 – BLOQUE 5: Resilience Tests
Tests for safe_call timeout, retry, backoff, and circuit breaker.
"""
import asyncio
import time
import pytest

from backend.src.utils.resilience import (
    safe_call, safe_call_sync, CircuitBreaker, CircuitBreakerOpen,
)


# ── 1. safe_call timeout ────────────────────────────────────────────────────

def test_safe_call_timeout():
    """safe_call should raise TimeoutError when the function exceeds timeout."""

    async def slow_func():
        await asyncio.sleep(5)

    async def _run():
        await safe_call(slow_func, timeout_seconds=0.1, max_retries=0)

    with pytest.raises(TimeoutError):
        asyncio.run(_run())


# ── 2. safe_call retry on failure ────────────────────────────────────────────

def test_safe_call_retry_on_failure():
    """safe_call should retry up to max_retries times. Total = 1 + max_retries."""

    call_count = 0

    async def flaky_func():
        nonlocal call_count
        call_count += 1
        raise ValueError("boom")

    async def _run():
        await safe_call(flaky_func, max_retries=2, backoff_base=0.01)

    with pytest.raises(ValueError, match="boom"):
        asyncio.run(_run())

    assert call_count == 3  # 1 initial + 2 retries


# ── 3. safe_call success ────────────────────────────────────────────────────

def test_safe_call_success():
    """safe_call should return the value from a successful async function."""

    async def ok_func():
        return "ok"

    async def _run():
        return await safe_call(ok_func)

    result = asyncio.run(_run())
    assert result == "ok"


# ── 4. CircuitBreaker opens after threshold ──────────────────────────────────

def test_circuit_breaker_opens_after_threshold():
    """After failure_threshold consecutive failures, breaker opens and rejects."""

    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)

    assert cb.state == "closed"
    assert cb.allow_request() is True

    for _ in range(3):
        cb.record_failure()

    assert cb.state == "open"
    assert cb.allow_request() is False


# ── 5. CircuitBreaker half-open recovery ─────────────────────────────────────

def test_circuit_breaker_half_open_recovery():
    """After cooldown, breaker transitions to half_open, then closes on success."""

    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)

    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"

    time.sleep(0.15)

    assert cb.state == "half_open"
    assert cb.allow_request() is True

    cb.record_success()
    assert cb.state == "closed"
