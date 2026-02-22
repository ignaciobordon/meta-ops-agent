"""Meta Ads Library collector — Graph API + HTML fallback parser."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .base import BaseAdsCollector
from ..core.anti_block import RateLimiter, RetryPolicy, api_headers, jittered_delay, random_headers
from ..core.config import AdsConfig, DEFAULT_CONFIG
from ..core.models import AdCanonical, AdPlatform, CollectorTarget
from ..core.normalizer import AdsNormalizer
from ..core.storage import InMemoryAdsStore
from ..core.validators import AdValidator

logger = logging.getLogger(__name__)

# Meta Ad Library API (Graph API v18.0)
_GRAPH_API_BASE = "https://graph.facebook.com/v18.0"
_AD_LIBRARY_ENDPOINT = f"{_GRAPH_API_BASE}/ads_archive"

# Public Ad Library web search (fallback)
_AD_LIBRARY_WEB = "https://www.facebook.com/ads/library/"


class MetaAdsCollector(BaseAdsCollector):
    """Collect ads from Meta Ad Library (Facebook/Instagram)."""

    def __init__(self, config: AdsConfig | None = None, storage: Any = None):
        self.config = config or DEFAULT_CONFIG
        self.platform_config = self.config.meta
        self.storage = storage or InMemoryAdsStore()
        self._rate_limiter = RateLimiter(self.platform_config.rate_limit_rpm)
        self._retry = RetryPolicy(
            max_retries=self.platform_config.max_retries,
            base_backoff=self.platform_config.retry_backoff,
        )

    async def discover_targets(
        self, query: str = "", country: str = "US",
    ) -> list[CollectorTarget]:
        """Build collection targets from query + configured countries."""
        countries = [country] if country else self.platform_config.countries
        targets: list[CollectorTarget] = []
        for c in countries:
            targets.append(CollectorTarget(
                platform=AdPlatform.META,
                query=query,
                country=c,
                metadata={"source": "meta_ad_library"},
            ))
        return targets

    async def collect(self, target: CollectorTarget) -> list[dict]:
        """
        Fetch ads from Meta Ad Library API.
        Falls back to HTML parsing if no API key is configured.
        """
        if self.platform_config.api_key:
            return await self._collect_via_api(target)
        return await self._collect_via_html(target)

    async def _collect_via_api(self, target: CollectorTarget) -> list[dict]:
        """Collect via official Graph API."""
        params = {
            "access_token": self.platform_config.api_key,
            "search_terms": target.query,
            "ad_reached_countries": target.country,
            "ad_active_status": "ALL",
            "fields": ",".join([
                "id", "page_name", "ad_creative_body",
                "ad_creative_link_title", "ad_creative_link_caption",
                "ad_creative_link_url", "ad_delivery_start_time",
                "ad_delivery_stop_time", "publisher_platform",
                "ad_creative_image_url",
            ]),
            "limit": min(self.platform_config.max_ads_per_query, 50),
        }

        ads: list[dict] = []
        async with httpx.AsyncClient(timeout=self.platform_config.request_timeout) as client:
            for attempt in range(self._retry.max_retries + 1):
                await self._rate_limiter.acquire()
                try:
                    resp = await client.get(
                        _AD_LIBRARY_ENDPOINT,
                        params=params,
                        headers=api_headers(),
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        ads = data.get("data", [])
                        for ad in ads:
                            ad["country"] = target.country
                        logger.info("META_API_OK | query=%s | country=%s | ads=%d",
                                    target.query, target.country, len(ads))
                        return ads

                    if self._retry.should_retry(attempt, resp.status_code):
                        delay = self._retry.get_delay(attempt)
                        logger.warning("META_API_RETRY | status=%d | attempt=%d | delay=%.1f",
                                       resp.status_code, attempt, delay)
                        await asyncio.sleep(delay)
                        continue

                    logger.error("META_API_ERROR | status=%d | body=%s",
                                 resp.status_code, resp.text[:300])
                    return []

                except (httpx.TimeoutException, httpx.RequestError) as e:
                    if self._retry.should_retry(attempt, 0):
                        delay = self._retry.get_delay(attempt)
                        logger.warning("META_API_NETWORK_ERROR | error=%s | attempt=%d", str(e)[:100], attempt)
                        await asyncio.sleep(delay)
                        continue
                    logger.error("META_API_FAILED | error=%s", str(e)[:200])
                    return []

        return ads

    async def _collect_via_html(self, target: CollectorTarget) -> list[dict]:
        """Fallback: parse Meta Ad Library public HTML."""
        params = {
            "active_status": "all",
            "ad_type": "all",
            "country": target.country,
            "q": target.query,
            "media_type": "all",
        }
        ads: list[dict] = []
        async with httpx.AsyncClient(
            timeout=self.platform_config.request_timeout,
            follow_redirects=True,
        ) as client:
            await self._rate_limiter.acquire()
            await jittered_delay(self.config.min_delay, self.config.max_delay)
            try:
                resp = await client.get(_AD_LIBRARY_WEB, params=params, headers=random_headers())
                if resp.status_code != 200:
                    logger.warning("META_HTML_STATUS | status=%d", resp.status_code)
                    return []

                ads = self._parse_ad_library_html(resp.text, target.country)
                logger.info("META_HTML_OK | query=%s | country=%s | ads=%d",
                            target.query, target.country, len(ads))
            except (httpx.TimeoutException, httpx.RequestError) as e:
                logger.error("META_HTML_ERROR | error=%s", str(e)[:200])

        return ads

    @staticmethod
    def _parse_ad_library_html(html: str, country: str = "") -> list[dict]:
        """Parse ads from Meta Ad Library HTML page."""
        soup = BeautifulSoup(html, "html.parser")
        ads: list[dict] = []

        # Ad Library renders ads in divs with specific data attributes
        # The actual HTML structure varies; this parses common patterns
        for container in soup.select("[data-ad-preview], .x1dr75xp, ._7jyg"):
            ad: dict[str, Any] = {"country": country}

            # Page name / advertiser
            page_el = container.select_one("a[href*='/ads/library/'], .x8t9es0, ._7jyr")
            if page_el:
                ad["page_name"] = page_el.get_text(strip=True)

            # Ad body text
            body_el = container.select_one(".x1iorvi4, ._7jys, [data-ad-preview-text]")
            if body_el:
                ad["ad_creative_body"] = body_el.get_text(strip=True)

            # Link title
            title_el = container.select_one(".x1heor9g, ._7jyt, [data-ad-preview-title]")
            if title_el:
                ad["ad_creative_link_title"] = title_el.get_text(strip=True)

            # Image
            img_el = container.select_one("img[src*='scontent'], img[src*='fbcdn']")
            if img_el:
                ad["ad_creative_image_url"] = img_el.get("src", "")

            # Link
            link_el = container.select_one("a[href*='l.facebook.com'], a[data-lynx-uri]")
            if link_el:
                ad["ad_creative_link_url"] = link_el.get("href", "")

            # Only keep if we got at least a body or title
            if ad.get("ad_creative_body") or ad.get("ad_creative_link_title"):
                ads.append(ad)

        return ads

    def normalize(self, raw: dict) -> AdCanonical:
        return AdsNormalizer.normalize_meta(raw)

    def validate(self, ad: AdCanonical) -> bool:
        return AdValidator.is_valid(ad)

    def persist(self, ad: AdCanonical) -> None:
        self.storage.store_ad(ad)
