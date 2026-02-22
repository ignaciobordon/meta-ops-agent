"""Google Ads Transparency Center collector — public page parser."""
from __future__ import annotations

import asyncio
import json
import logging
import re
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

# Google Ads Transparency Center
_TRANSPARENCY_URL = "https://adstransparency.google.com"
_TRANSPARENCY_SEARCH = f"{_TRANSPARENCY_URL}/anji/_/rpc/SearchService/SearchCreatives"


class GoogleAdsCollector(BaseAdsCollector):
    """Collect ads from Google Ads Transparency Center."""

    def __init__(self, config: AdsConfig | None = None, storage: Any = None):
        self.config = config or DEFAULT_CONFIG
        self.platform_config = self.config.google
        self.storage = storage or InMemoryAdsStore()
        self._rate_limiter = RateLimiter(self.platform_config.rate_limit_rpm)
        self._retry = RetryPolicy(
            max_retries=self.platform_config.max_retries,
            base_backoff=self.platform_config.retry_backoff,
        )

    async def discover_targets(
        self, query: str = "", country: str = "US",
    ) -> list[CollectorTarget]:
        countries = [country] if country else self.platform_config.countries
        targets: list[CollectorTarget] = []
        for c in countries:
            targets.append(CollectorTarget(
                platform=AdPlatform.GOOGLE,
                query=query,
                country=c,
                metadata={"source": "google_transparency"},
            ))
        return targets

    async def collect(self, target: CollectorTarget) -> list[dict]:
        """Fetch ads from Google Ads Transparency Center."""
        return await self._collect_via_search(target)

    async def _collect_via_search(self, target: CollectorTarget) -> list[dict]:
        """Query the Transparency Center search endpoint."""
        ads: list[dict] = []

        # Google Transparency Center uses an internal RPC protocol
        # We attempt the public search page + extract embedded data
        search_url = f"{_TRANSPARENCY_URL}/advertiser"
        params = {
            "query": target.query,
            "region": target.country,
        }

        async with httpx.AsyncClient(
            timeout=self.platform_config.request_timeout,
            follow_redirects=True,
        ) as client:
            for attempt in range(self._retry.max_retries + 1):
                await self._rate_limiter.acquire()
                await jittered_delay(self.config.min_delay, self.config.max_delay)

                try:
                    resp = await client.get(search_url, params=params, headers=random_headers())

                    if resp.status_code == 200:
                        ads = self._parse_transparency_html(resp.text, target.country)
                        logger.info(
                            "GOOGLE_HTML_OK | query=%s | country=%s | ads=%d",
                            target.query, target.country, len(ads),
                        )
                        return ads

                    if self._retry.should_retry(attempt, resp.status_code):
                        delay = self._retry.get_delay(attempt)
                        logger.warning(
                            "GOOGLE_RETRY | status=%d | attempt=%d",
                            resp.status_code, attempt,
                        )
                        await asyncio.sleep(delay)
                        continue

                    logger.error("GOOGLE_ERROR | status=%d", resp.status_code)
                    return []

                except (httpx.TimeoutException, httpx.RequestError) as e:
                    if self._retry.should_retry(attempt, 0):
                        delay = self._retry.get_delay(attempt)
                        logger.warning("GOOGLE_NETWORK_ERROR | error=%s | attempt=%d", str(e)[:100], attempt)
                        await asyncio.sleep(delay)
                        continue
                    logger.error("GOOGLE_FAILED | error=%s", str(e)[:200])
                    return []

        return ads

    @staticmethod
    def _parse_transparency_html(html: str, country: str = "") -> list[dict]:
        """Extract ad data from Google Ads Transparency Center HTML."""
        soup = BeautifulSoup(html, "html.parser")
        ads: list[dict] = []

        # Try to extract embedded JSON data (AF_initDataCallback)
        for script in soup.find_all("script"):
            text = script.string or ""
            if "AF_initDataCallback" in text or "creative-preview" in text:
                # Attempt to extract JSON arrays from the script
                for match in re.finditer(r'\{[^{}]*"headline"[^{}]*\}', text):
                    try:
                        data = json.loads(match.group())
                        data["country"] = country
                        ads.append(data)
                    except json.JSONDecodeError:
                        continue

        # Fallback: parse visible ad containers
        for container in soup.select(
            "[data-creative-id], .creative-preview, .ad-container, "
            "[class*='creative'], [class*='ad-preview']"
        ):
            ad: dict[str, Any] = {"country": country}

            # Advertiser name
            advertiser_el = container.select_one(
                "[class*='advertiser'], [class*='brand'], h2, h3"
            )
            if advertiser_el:
                ad["advertiser_name"] = advertiser_el.get_text(strip=True)

            # Headline
            headline_el = container.select_one(
                "[class*='headline'], [class*='title'], h4, [role='heading']"
            )
            if headline_el:
                ad["headline"] = headline_el.get_text(strip=True)

            # Description
            desc_el = container.select_one(
                "[class*='description'], [class*='body'], p"
            )
            if desc_el:
                ad["description"] = desc_el.get_text(strip=True)

            # Image
            img_el = container.select_one("img[src]")
            if img_el:
                ad["image_url"] = img_el.get("src", "")

            # Destination URL
            link_el = container.select_one("a[href]")
            if link_el:
                href = link_el.get("href", "")
                if href and not href.startswith("#"):
                    ad["destination_url"] = href

            if ad.get("headline") or ad.get("description"):
                ads.append(ad)

        return ads

    def normalize(self, raw: dict) -> AdCanonical:
        return AdsNormalizer.normalize_google(raw)

    def validate(self, ad: AdCanonical) -> bool:
        return AdValidator.is_valid(ad)

    def persist(self, ad: AdCanonical) -> None:
        self.storage.store_ad(ad)
