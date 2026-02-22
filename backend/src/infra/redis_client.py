"""
Sprint 7 -- BLOQUE 1: Redis Connection Manager.
Provides a singleton Redis client. Returns None if Redis is unavailable
(used by degraded mode checks).
"""
from typing import Optional

from src.utils.logging_config import logger

_redis_client = None
_redis_checked = False


def get_redis():
    """Get or create the Redis client singleton. Returns None if unavailable."""
    global _redis_client, _redis_checked

    if _redis_checked:
        return _redis_client

    try:
        import redis
        from backend.src.config import settings

        _redis_client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        _redis_client.ping()
        _redis_checked = True
        logger.info("REDIS_CONNECTED | url={}",
                     settings.REDIS_URL.split("@")[-1] if "@" in settings.REDIS_URL else settings.REDIS_URL)
    except Exception as e:
        _redis_client = None
        _redis_checked = True
        logger.warning("REDIS_UNAVAILABLE | error={}", str(e))

    return _redis_client


def redis_available() -> bool:
    """Check if Redis is currently reachable."""
    client = get_redis()
    if client is None:
        return False
    try:
        return client.ping()
    except Exception:
        return False


def reset_redis():
    """Reset the singleton (for tests)."""
    global _redis_client, _redis_checked
    _redis_client = None
    _redis_checked = False
