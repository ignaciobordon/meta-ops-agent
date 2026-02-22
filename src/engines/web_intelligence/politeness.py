"""Politeness layer — robots.txt, crawl delay, UA rotation, anti-blocking."""
from __future__ import annotations

import asyncio
import random
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from .config import CrawlerConfig, DEFAULT_CONFIG

# ── User-Agent rotation pool ──────────────────────────────────────────────────

_UA_POOL: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
    "Mozilla/5.0 (compatible; MetaOpsBot/1.0; +https://metaops.dev/bot)",
]

_ACCEPT_LANGUAGE_POOL: list[str] = [
    "en-US,en;q=0.9",
    "en-GB,en;q=0.8",
    "es-ES,es;q=0.9,en;q=0.7",
    "en-US,en;q=0.9,es;q=0.5",
]


def random_headers(config: CrawlerConfig | None = None) -> dict[str, str]:
    """Generate randomized request headers to reduce fingerprint signature."""
    ua = random.choice(_UA_POOL)
    lang = random.choice(_ACCEPT_LANGUAGE_POOL)
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": lang,
        # Do NOT set Accept-Encoding — httpx handles gzip/deflate/br
        # decompression automatically. Setting it explicitly disables auto-decompress.
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }


# ── Robots.txt compliance ────────────────────────────────────────────────────


class RobotsChecker:
    """Async-friendly robots.txt parser with caching."""

    def __init__(self, config: CrawlerConfig | None = None):
        self._config = config or DEFAULT_CONFIG
        self._cache: dict[str, RobotFileParser] = {}
        self._cache_ttl: dict[str, float] = {}
        self._ttl = 3600  # 1 hour cache

    async def is_allowed(self, url: str) -> bool:
        """Check if url is allowed by the domain's robots.txt."""
        if not self._config.respect_robots:
            return True

        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        # Check cache freshness
        now = time.monotonic()
        if origin in self._cache and (now - self._cache_ttl.get(origin, 0)) < self._ttl:
            rp = self._cache[origin]
            return rp.can_fetch(self._config.default_user_agent, url)

        # Fetch robots.txt
        robots_url = f"{origin}/robots.txt"
        rp = RobotFileParser()
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(robots_url)
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                else:
                    # No robots.txt → allow all
                    rp.allow_all = True
        except Exception:
            rp.allow_all = True

        self._cache[origin] = rp
        self._cache_ttl[origin] = now
        return rp.can_fetch(self._config.default_user_agent, url)

    def get_crawl_delay(self, domain: str) -> float | None:
        """Return crawl-delay from robots.txt if cached."""
        for origin, rp in self._cache.items():
            if domain in origin:
                delay = rp.crawl_delay(self._config.default_user_agent)
                return float(delay) if delay else None
        return None


# ── Rate limiter (per-domain) ─────────────────────────────────────────────────


class DomainThrottle:
    """Per-domain rate limiter with randomized delays."""

    def __init__(self, config: CrawlerConfig | None = None):
        self._config = config or DEFAULT_CONFIG
        self._last_request: dict[str, float] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    def _get_semaphore(self, domain: str) -> asyncio.Semaphore:
        if domain not in self._semaphores:
            self._semaphores[domain] = asyncio.Semaphore(
                self._config.concurrency_per_domain
            )
        return self._semaphores[domain]

    async def acquire(self, domain: str, robots_delay: float | None = None):
        """Wait for the appropriate delay, then acquire the domain semaphore."""
        sem = self._get_semaphore(domain)
        await sem.acquire()

        now = time.monotonic()
        last = self._last_request.get(domain, 0)

        # Use robots.txt delay if available, otherwise config range
        if robots_delay and robots_delay > 0:
            min_wait = robots_delay
        else:
            min_wait = random.uniform(self._config.min_delay, self._config.max_delay)

        elapsed = now - last
        if elapsed < min_wait:
            await asyncio.sleep(min_wait - elapsed)

        self._last_request[domain] = time.monotonic()

    def release(self, domain: str):
        sem = self._semaphores.get(domain)
        if sem:
            sem.release()
