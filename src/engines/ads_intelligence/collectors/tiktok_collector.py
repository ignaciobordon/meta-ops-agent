"""TikTok Creative Center collector — public Top Ads API."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .base import BaseAdsCollector
from ..core.anti_block import RateLimiter, RetryPolicy, api_headers, jittered_delay
from ..core.config import AdsConfig, DEFAULT_CONFIG
from ..core.models import AdCanonical, AdPlatform, CollectorTarget
from ..core.normalizer import AdsNormalizer
from ..core.storage import InMemoryAdsStore
from ..core.validators import AdValidator

logger = logging.getLogger(__name__)

# TikTok Creative Center public API
_CREATIVE_CENTER_API = "https://ads.tiktok.com/creative_radar_api/v1/top_ads/list"


class TikTokCollector(BaseAdsCollector):
    """Collect ads from TikTok Creative Center (public endpoints)."""

    def __init__(self, config: AdsConfig | None = None, storage: Any = None):
        self.config = config or DEFAULT_CONFIG
        self.platform_config = self.config.tiktok
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
                platform=AdPlatform.TIKTOK,
                query=query,
                country=c,
                metadata={"source": "tiktok_creative_center"},
            ))
        return targets

    async def collect(self, target: CollectorTarget) -> list[dict]:
        """Fetch top ads from TikTok Creative Center API."""
        ads: list[dict] = []

        # Map country code to TikTok region code
        country_map = {
            "US": "US", "AR": "AR", "ES": "ES", "MX": "MX", "BR": "BR",
            "GB": "GB", "DE": "DE", "FR": "FR", "IT": "IT", "JP": "JP",
        }
        region = country_map.get(target.country.upper(), target.country.upper())

        payload = {
            "page": 1,
            "limit": min(self.platform_config.max_ads_per_query, 50),
            "period": 30,  # last 30 days
            "country_code": region,
            "order_field": "like",
            "order_type": "desc",
        }

        if target.query:
            payload["search_value"] = target.query

        async with httpx.AsyncClient(
            timeout=self.platform_config.request_timeout,
            follow_redirects=True,
        ) as client:
            for attempt in range(self._retry.max_retries + 1):
                await self._rate_limiter.acquire()
                await jittered_delay(self.config.min_delay, self.config.max_delay)

                try:
                    headers = api_headers({
                        "Origin": "https://ads.tiktok.com",
                        "Referer": "https://ads.tiktok.com/business/creativecenter/inspiration/topads/pc/en",
                    })
                    resp = await client.get(
                        _CREATIVE_CENTER_API,
                        params=payload,
                        headers=headers,
                    )

                    if resp.status_code == 200:
                        data = resp.json()
                        raw_ads = data.get("data", {}).get("materials", [])
                        # Enrich each with country
                        for ad in raw_ads:
                            ad["country_code"] = target.country
                        ads = raw_ads
                        logger.info(
                            "TIKTOK_API_OK | query=%s | country=%s | ads=%d",
                            target.query, target.country, len(ads),
                        )
                        return ads

                    if self._retry.should_retry(attempt, resp.status_code):
                        delay = self._retry.get_delay(attempt)
                        logger.warning(
                            "TIKTOK_RETRY | status=%d | attempt=%d",
                            resp.status_code, attempt,
                        )
                        await asyncio.sleep(delay)
                        continue

                    logger.error("TIKTOK_ERROR | status=%d | body=%s",
                                 resp.status_code, resp.text[:300])
                    return []

                except (httpx.TimeoutException, httpx.RequestError) as e:
                    if self._retry.should_retry(attempt, 0):
                        delay = self._retry.get_delay(attempt)
                        logger.warning("TIKTOK_NETWORK_ERROR | error=%s | attempt=%d",
                                       str(e)[:100], attempt)
                        await asyncio.sleep(delay)
                        continue
                    logger.error("TIKTOK_FAILED | error=%s", str(e)[:200])
                    return []

        return ads

    def normalize(self, raw: dict) -> AdCanonical:
        return AdsNormalizer.normalize_tiktok(raw)

    def validate(self, ad: AdCanonical) -> bool:
        return AdValidator.is_valid(ad)

    def persist(self, ad: AdCanonical) -> None:
        self.storage.store_ad(ad)
