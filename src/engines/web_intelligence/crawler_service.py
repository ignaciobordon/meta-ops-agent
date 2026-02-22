"""Core async crawler — BFS crawl with politeness, dedup, budget, retries."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse, parse_qs, urlencode

import httpx
from bs4 import BeautifulSoup

from .config import CrawlerConfig, DEFAULT_CONFIG
from .extractors import extract_all
from .fingerprint import content_hash, page_fingerprint
from .models import CrawlReport, CrawlResult, ExtractedPageData
from .politeness import DomainThrottle, RobotsChecker, random_headers

# ── URL normalization ────────────────────────────────────────────────────────

# Query params to strip (tracking, session, cache busters)
_STRIP_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "fbclid", "gclid", "gclsrc", "_ga", "_gl", "mc_cid", "mc_eid",
    "ref", "source", "sessionid", "session_id", "sid", "PHPSESSID",
    "jsessionid", "_ke", "ck_subscriber_id", "wickedid",
}


def normalize_url(url: str) -> str:
    """Canonicalize a URL: lowercase host, strip tracking params, remove fragment."""
    parsed = urlparse(url)
    # Lowercase scheme and host
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    # Strip tracking query params
    qs = parse_qs(parsed.query, keep_blank_values=False)
    filtered = {k: v for k, v in qs.items() if k.lower() not in _STRIP_PARAMS}
    query = urlencode(filtered, doseq=True) if filtered else ""
    # Remove fragment
    return urlunparse((scheme, netloc, path, parsed.params, query, ""))


def extract_links(html: str, base_url: str) -> list[str]:
    """Extract and normalize all <a href> links from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(base_url, href)
        normalized = normalize_url(absolute)
        links.append(normalized)
    return links


def _is_same_domain(url: str, domain: str) -> bool:
    """Check if url belongs to the target domain."""
    host = urlparse(url).netloc.lower()
    return host == domain or host.endswith(f".{domain}")


# ── Fetch with retries ───────────────────────────────────────────────────────


async def fetch(
    url: str,
    client: httpx.AsyncClient,
    config: CrawlerConfig,
    attempt: int = 0,
) -> tuple[str | None, int, str | None]:
    """
    Fetch a URL. Returns (html, status_code, error).
    Retries on transient errors.
    """
    try:
        headers = random_headers(config)
        resp = await client.get(
            url,
            headers=headers,
            timeout=config.request_timeout,
            follow_redirects=True,
        )

        # Check content type
        ct = resp.headers.get("content-type", "")
        if not any(allowed in ct for allowed in config.allowed_content_types):
            return None, resp.status_code, f"Skipped content-type: {ct}"

        # Check size
        if len(resp.content) > config.max_response_bytes:
            return None, resp.status_code, "Response too large"

        if resp.status_code >= 400:
            # Retry on 5xx
            if resp.status_code >= 500 and attempt < config.max_retries:
                await asyncio.sleep(config.retry_backoff * (attempt + 1))
                return await fetch(url, client, config, attempt + 1)
            return None, resp.status_code, f"HTTP {resp.status_code}"

        return resp.text, resp.status_code, None

    except httpx.TimeoutException:
        if attempt < config.max_retries:
            await asyncio.sleep(config.retry_backoff * (attempt + 1))
            return await fetch(url, client, config, attempt + 1)
        return None, 0, "Timeout"

    except httpx.RequestError as e:
        if attempt < config.max_retries:
            await asyncio.sleep(config.retry_backoff * (attempt + 1))
            return await fetch(url, client, config, attempt + 1)
        return None, 0, str(e)


# ── BFS Crawl ────────────────────────────────────────────────────────────────


async def crawl_domain(
    domain: str,
    depth: int = 3,
    config: CrawlerConfig | None = None,
    storage=None,
) -> tuple[dict[str, CrawlResult], dict[str, ExtractedPageData], dict[str, str], CrawlReport]:
    """
    BFS crawl a domain up to `depth` levels.

    Returns:
        results: url -> CrawlResult
        extracted: url -> ExtractedPageData
        html_store: url -> raw HTML
        report: CrawlReport telemetry
    """
    config = config or DEFAULT_CONFIG
    max_pages = config.max_pages_per_domain
    max_d = min(depth, config.max_depth)

    robots = RobotsChecker(config)
    throttle = DomainThrottle(config)

    start_url = f"https://{domain}" if not domain.startswith("http") else domain
    start_url = normalize_url(start_url)
    parsed_domain = urlparse(start_url).netloc.lower()

    # BFS state
    queue: deque[tuple[str, int]] = deque([(start_url, 0)])
    visited: set[str] = set()
    results: dict[str, CrawlResult] = {}
    extracted: dict[str, ExtractedPageData] = {}
    html_store: dict[str, str] = {}

    report = CrawlReport(domain=parsed_domain, started_at=datetime.utcnow())
    t0 = time.monotonic()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        while queue and report.pages_crawled < max_pages:
            url, current_depth = queue.popleft()

            # Dedupe
            canonical = normalize_url(url)
            if canonical in visited:
                report.pages_skipped += 1
                continue
            visited.add(canonical)

            # Domain lock
            if not _is_same_domain(canonical, parsed_domain):
                report.pages_skipped += 1
                continue

            # Depth limit
            if current_depth > max_d:
                report.pages_skipped += 1
                continue

            # Robots check
            if not await robots.is_allowed(canonical):
                report.pages_skipped += 1
                continue

            # Throttle
            robots_delay = robots.get_crawl_delay(parsed_domain)
            await throttle.acquire(parsed_domain, robots_delay)

            try:
                html, status_code, error = await fetch(canonical, client, config)

                if error or html is None:
                    results[canonical] = CrawlResult(
                        url=canonical,
                        status_code=status_code,
                        content_hash="",
                        content_length=0,
                        error=error,
                    )
                    report.errors += 1
                    continue

                # Content hash
                c_hash = content_hash(html)

                # Extract title
                soup = BeautifulSoup(html, "html.parser")
                title = ""
                title_tag = soup.find("title")
                if title_tag:
                    title = title_tag.get_text(strip=True)

                # Extract links for BFS
                links = extract_links(html, canonical)

                # Store result
                results[canonical] = CrawlResult(
                    url=canonical,
                    status_code=status_code,
                    content_hash=c_hash,
                    content_length=len(html),
                    title=title,
                    links_found=len(links),
                )
                html_store[canonical] = html

                # Extract structured data
                data = extract_all(html, canonical)
                extracted[canonical] = ExtractedPageData(
                    url=canonical,
                    content_hash=c_hash,
                    title=title,
                    **{k: v for k, v in data.items() if k not in ("url", "content_hash")},
                )

                report.pages_crawled += 1

                # Persist if storage provided
                if storage:
                    storage.store_page(canonical, html, extracted[canonical])

                # Enqueue child links
                for link in links:
                    norm_link = normalize_url(link)
                    if norm_link not in visited and _is_same_domain(norm_link, parsed_domain):
                        queue.append((norm_link, current_depth + 1))

            finally:
                throttle.release(parsed_domain)

    report.duration_seconds = round(time.monotonic() - t0, 2)
    report.finished_at = datetime.utcnow()

    return results, extracted, html_store, report
