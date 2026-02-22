"""
Sprint 7 -- BLOQUE 5: Provider Rate Limiter Tests
Tests for ProviderRateLimiter: acquire, tokens_remaining,
per-org isolation, per-provider isolation, and degraded mode (no Redis).
"""
import os
import pytest
from uuid import uuid4, UUID
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.src.providers.rate_limiter import ProviderRateLimiter, PROVIDER_LIMITS
from backend.src.infra.fake_redis import FakeRedis


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def fake_redis():
    """Provide a fresh FakeRedis instance for each test."""
    return FakeRedis()


@pytest.fixture(autouse=True)
def _patch_redis(fake_redis):
    """Patch _get_redis on ProviderRateLimiter to return FakeRedis by default."""
    with patch.object(ProviderRateLimiter, "_get_redis", return_value=fake_redis):
        yield


# ── Tests ────────────────────────────────────────────────────────────────────


class TestProviderRateLimiter:

    # 1. acquire within limit
    def test_acquire_within_limit(self):
        """Acquiring fewer tokens than the limit should always succeed."""
        org_id = uuid4()
        limiter = ProviderRateLimiter("meta", org_id)

        # meta limit is 10; acquire 5 times
        results = [limiter.acquire() for _ in range(5)]
        assert all(results), "All 5 acquires should return True (limit is 10)"

    # 2. acquire exceeds limit
    def test_acquire_exceeds_limit(self):
        """After exhausting the rate, the next acquire must be denied."""
        org_id = uuid4()
        limiter = ProviderRateLimiter("meta", org_id)

        # meta limit is 10; first 10 should succeed
        for i in range(10):
            assert limiter.acquire() is True, f"Acquire #{i+1} should succeed"

        # 11th must fail
        assert limiter.acquire() is False, "11th acquire should be denied (limit 10)"

    # 3. tokens_remaining
    def test_tokens_remaining(self):
        """tokens_remaining should reflect how many tokens are left."""
        org_id = uuid4()
        limiter = ProviderRateLimiter("meta", org_id)

        # Initially all tokens available
        assert limiter.tokens_remaining() == 10

        # Consume 3 tokens
        for _ in range(3):
            limiter.acquire()

        assert limiter.tokens_remaining() == 7

    # 4. independent orgs
    def test_independent_orgs(self):
        """Each org_id gets its own independent rate window."""
        org_a = uuid4()
        org_b = uuid4()
        limiter_a = ProviderRateLimiter("meta", org_a)
        limiter_b = ProviderRateLimiter("meta", org_b)

        # Exhaust all tokens for org_a
        for _ in range(10):
            limiter_a.acquire()

        # org_a is now depleted
        assert limiter_a.acquire() is False

        # org_b should still have all its tokens
        assert limiter_b.acquire() is True
        assert limiter_b.tokens_remaining() == 9

    # 5. independent providers
    def test_independent_providers(self):
        """Different providers maintain separate rate counters for the same org."""
        org_id = uuid4()
        meta_limiter = ProviderRateLimiter("meta", org_id)
        anthropic_limiter = ProviderRateLimiter("anthropic", org_id)

        # Exhaust meta (limit 10)
        for _ in range(10):
            meta_limiter.acquire()
        assert meta_limiter.acquire() is False

        # anthropic (limit 5) should still be fully available
        assert anthropic_limiter.acquire() is True
        assert anthropic_limiter.tokens_remaining() == 4

    # 6. no Redis allows all (degraded mode)
    def test_no_redis_allows_all(self):
        """When Redis is unavailable, acquire must always return True."""
        org_id = uuid4()
        limiter = ProviderRateLimiter("meta", org_id)

        with patch.object(ProviderRateLimiter, "_get_redis", return_value=None):
            # Even beyond the limit, every call should succeed
            results = [limiter.acquire() for _ in range(20)]
            assert all(results), "All acquires should succeed when Redis is None"

            # tokens_remaining returns the full rate when there is no Redis
            assert limiter.tokens_remaining() == limiter.rate
