"""
Sprint 7 -- BLOQUE 1: Fake Redis for test environments.
In-memory dict-based implementation of the Redis methods we use.
"""
import time
from typing import Optional, Dict, Any


class FakeRedis:
    """Minimal Redis mock for tests. Supports the subset of Redis commands
    used by rate_limiter, circuit_breaker, and idempotency modules."""

    def __init__(self):
        self._store: Dict[str, Any] = {}
        self._expiry: Dict[str, float] = {}

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> Optional[str]:
        self._evict(key)
        return self._store.get(key)

    def set(self, key: str, value: Any, ex: Optional[int] = None,
            px: Optional[int] = None, nx: bool = False) -> bool:
        self._evict(key)
        if nx and key in self._store:
            return False
        self._store[key] = str(value)
        if ex:
            self._expiry[key] = time.time() + ex
        elif px:
            self._expiry[key] = time.time() + px / 1000.0
        return True

    def setnx(self, key: str, value: Any) -> bool:
        return self.set(key, value, nx=True)

    def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                self._expiry.pop(key, None)
                count += 1
        return count

    def exists(self, key: str) -> bool:
        self._evict(key)
        return key in self._store

    def incr(self, key: str) -> int:
        self._evict(key)
        val = int(self._store.get(key, 0)) + 1
        self._store[key] = str(val)
        return val

    def decr(self, key: str) -> int:
        self._evict(key)
        val = int(self._store.get(key, 0)) - 1
        self._store[key] = str(val)
        return val

    def expire(self, key: str, seconds: int) -> bool:
        if key in self._store:
            self._expiry[key] = time.time() + seconds
            return True
        return False

    def ttl(self, key: str) -> int:
        if key not in self._expiry:
            return -1
        remaining = self._expiry[key] - time.time()
        if remaining <= 0:
            self._evict(key)
            return -2
        return max(0, int(remaining))

    def keys(self, pattern: str = "*") -> list:
        """Simplified keys matching. Only supports exact match or '*' prefix/suffix."""
        self._evict_all()
        if pattern == "*":
            return list(self._store.keys())
        # Simple prefix match for patterns like "rl:*"
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return [k for k in self._store.keys() if k.startswith(prefix)]
        return [k for k in self._store.keys() if k == pattern]

    def _evict(self, key: str):
        if key in self._expiry and time.time() > self._expiry[key]:
            self._store.pop(key, None)
            self._expiry.pop(key, None)

    def _evict_all(self):
        now = time.time()
        expired = [k for k, exp in self._expiry.items() if now > exp]
        for k in expired:
            self._store.pop(k, None)
            self._expiry.pop(k, None)

    def pipeline(self):
        return FakePipeline(self)

    def flushall(self):
        self._store.clear()
        self._expiry.clear()


class FakePipeline:
    def __init__(self, redis_instance: FakeRedis):
        self._redis = redis_instance
        self._commands = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self):
        results = []
        for cmd, args, kwargs in self._commands:
            results.append(getattr(self._redis, cmd)(*args, **kwargs))
        self._commands.clear()
        return results

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self._commands.append((name, args, kwargs))
            return self
        return method
