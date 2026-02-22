"""Anti-blocking utilities — UA rotation, jitter, rate limiting, retry policy."""
from __future__ import annotations

import asyncio
import random
import time

# ── User-Agent pool ──────────────────────────────────────────────────────────

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]

_ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-US,en;q=0.9,es;q=0.8",
    "en-GB,en;q=0.9",
    "es-ES,es;q=0.9,en;q=0.8",
    "es-AR,es;q=0.9,en;q=0.8",
    "pt-BR,pt;q=0.9,en;q=0.8",
    "en-US,en;q=0.8",
]


def random_headers() -> dict[str, str]:
    """Generate randomized browser-like headers."""
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": random.choice(_ACCEPT_LANGUAGES),
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }


def api_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Headers tuned for JSON API calls (lighter fingerprint)."""
    h = {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": random.choice(_ACCEPT_LANGUAGES),
        "Accept-Encoding": "gzip, deflate, br",
    }
    if extra:
        h.update(extra)
    return h


async def jittered_delay(min_s: float = 1.0, max_s: float = 5.0) -> None:
    """Sleep for a random duration in [min_s, max_s]."""
    await asyncio.sleep(random.uniform(min_s, max_s))


# ── Rate limiter ─────────────────────────────────────────────────────────────

class RateLimiter:
    """Token-bucket rate limiter (per-platform)."""

    def __init__(self, rpm: int = 30):
        self._interval = 60.0 / max(rpm, 1)
        self._last_request: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request
            if elapsed < self._interval:
                await asyncio.sleep(self._interval - elapsed)
            self._last_request = time.monotonic()


# ── Retry policy ─────────────────────────────────────────────────────────────

class RetryPolicy:
    """Exponential backoff with jitter."""

    def __init__(
        self,
        max_retries: int = 3,
        base_backoff: float = 2.0,
        max_backoff: float = 60.0,
    ):
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff

    def get_delay(self, attempt: int) -> float:
        delay = self.base_backoff * (2 ** attempt)
        delay = min(delay, self.max_backoff)
        jitter = delay * random.uniform(-0.25, 0.25)
        return max(0.1, delay + jitter)

    def should_retry(self, attempt: int, status_code: int = 0) -> bool:
        if attempt >= self.max_retries:
            return False
        # Retry on rate-limit, server errors, and connection failures
        return status_code == 0 or status_code == 429 or status_code >= 500
