"""
Sprint 7 -- BLOQUE 6: Persistent Circuit Breaker Tests
Tests for PersistentCircuitBreaker with Redis-backed state storage.
Covers state transitions, failure thresholds, cooldown, half-open probing,
and degraded mode when Redis is unavailable.
"""
import os
import pytest
from uuid import uuid4, UUID
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.src.providers.circuit_breaker import PersistentCircuitBreaker
from backend.src.infra.fake_redis import FakeRedis


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def fake_redis():
    """Fresh FakeRedis instance for each test."""
    return FakeRedis()


@pytest.fixture()
def patch_redis(fake_redis):
    """Patch get_redis to return the FakeRedis instance."""
    with patch(
        "backend.src.infra.redis_client.get_redis", return_value=fake_redis
    ):
        yield fake_redis


@pytest.fixture()
def org_id():
    return uuid4()


@pytest.fixture()
def breaker(patch_redis, org_id):
    """Standard breaker with default threshold=5 and cooldown=60."""
    return PersistentCircuitBreaker(
        provider="meta", org_id=org_id, failure_threshold=5, cooldown_seconds=60
    )


# ── Tests ────────────────────────────────────────────────────────────────────


class TestPersistentCircuitBreaker:

    # 1. New breaker starts in closed state
    def test_initial_state_closed(self, breaker):
        """A freshly created breaker must start in 'closed' state."""
        assert breaker.state == "closed"

    # 2. allow_request returns True when closed
    def test_allow_request_closed(self, breaker):
        """When the circuit is closed, allow_request() must return True."""
        assert breaker.allow_request() is True

    # 3. Recording 5 failures opens the circuit
    def test_record_failures_opens_circuit(self, breaker):
        """After reaching failure_threshold (5), state must become 'open'."""
        for _ in range(5):
            breaker.record_failure()

        assert breaker.state == "open"

    # 4. Open circuit blocks requests
    def test_open_blocks_requests(self, breaker):
        """Once open, allow_request() must return False."""
        for _ in range(5):
            breaker.record_failure()

        assert breaker.state == "open"
        assert breaker.allow_request() is False

    # 5. record_success resets to closed with failure_count=0
    def test_record_success_resets(self, breaker):
        """After accumulating failures, record_success() resets to closed."""
        # Accumulate some failures (but not enough to open)
        for _ in range(3):
            breaker.record_failure()

        breaker.record_success()

        assert breaker.state == "closed"
        status = breaker.get_status()
        assert status["failure_count"] == 0

    # 6. After cooldown elapses, open transitions to half_open
    def test_half_open_after_cooldown(self, patch_redis, org_id):
        """With cooldown_seconds=0, an open breaker transitions to half_open immediately."""
        cb = PersistentCircuitBreaker(
            provider="meta",
            org_id=org_id,
            failure_threshold=5,
            cooldown_seconds=0,
        )

        for _ in range(5):
            cb.record_failure()

        assert cb.state == "half_open"

    # 7. half_open state allows a probe request
    def test_half_open_allows_probe(self, patch_redis, org_id):
        """In half_open state, allow_request() must return True to permit a probe."""
        cb = PersistentCircuitBreaker(
            provider="meta",
            org_id=org_id,
            failure_threshold=5,
            cooldown_seconds=0,
        )

        for _ in range(5):
            cb.record_failure()

        # Should be half_open because cooldown=0
        assert cb.state == "half_open"
        assert cb.allow_request() is True

    # 8. When Redis is unavailable, defaults to closed / allows requests
    def test_no_redis_defaults_closed(self, org_id):
        """When get_redis returns None, the breaker degrades to closed state."""
        with patch(
            "backend.src.infra.redis_client.get_redis", return_value=None
        ):
            cb = PersistentCircuitBreaker(
                provider="meta",
                org_id=org_id,
                failure_threshold=5,
                cooldown_seconds=60,
            )

            assert cb.state == "closed"
            assert cb.allow_request() is True

            # Even after recording failures, state stays closed (writes are no-ops)
            for _ in range(10):
                cb.record_failure()

            assert cb.state == "closed"
            assert cb.allow_request() is True
