"""
Sprint 7 -- BLOQUE 5: Provider-Level Rate Limiter.
Redis token bucket per provider+org.
Key pattern: rl:{provider}:{org_id}
"""
from typing import Optional
from uuid import UUID

from src.utils.logging_config import logger

# Defaults: tokens per window per org
PROVIDER_LIMITS = {
    "meta":      {"rate": 10, "window": 1},     # 10 req/sec
    "anthropic": {"rate": 5, "window": 60},      # 5 req/min
    "openai":    {"rate": 5, "window": 60},      # 5 req/min
}


class ProviderRateLimiter:
    """Redis-backed rate limiter for external provider calls."""

    def __init__(self, provider: str, org_id):
        self.provider = provider
        self.org_id = str(org_id)
        self.key = f"rl:{provider}:{org_id}"
        limits = PROVIDER_LIMITS.get(provider, {"rate": 10, "window": 1})
        self.rate = limits["rate"]
        self.window = limits["window"]

    def _get_redis(self):
        try:
            from backend.src.infra.redis_client import get_redis
            return get_redis()
        except Exception:
            return None

    def acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens. Returns True if granted.
        Uses Redis INCR with EXPIRE for simplicity.
        """
        redis = self._get_redis()
        if redis is None:
            return True  # Degraded mode: allow

        try:
            current = redis.incr(self.key)
            if current == 1:
                redis.expire(self.key, self.window)

            if current <= self.rate:
                return True

            logger.warning(
                "PROVIDER_RATE_LIMITED | provider={} | org={} | current={} | limit={}",
                self.provider, self.org_id, current, self.rate,
            )
            return False
        except Exception as e:
            logger.warning("RATE_LIMITER_ERROR | {} | {}", self.key, str(e))
            return True  # Degraded: allow on error

    def tokens_remaining(self) -> int:
        """Get remaining tokens in current window."""
        redis = self._get_redis()
        if redis is None:
            return self.rate
        try:
            current = int(redis.get(self.key) or 0)
            return max(0, self.rate - current)
        except Exception:
            return self.rate
