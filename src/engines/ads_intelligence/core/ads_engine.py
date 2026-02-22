"""Core orchestrator — run collectors, normalize, detect signals, persist."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from .config import AdsConfig, DEFAULT_CONFIG
from .models import AdCanonical, AdsRunReport, CollectorTarget, SignalEvent
from .normalizer import AdsNormalizer
from .signals import AngleTrendDetector, CreativeFormatShiftDetector, NewAdDetector
from .storage import InMemoryAdsStore
from .validators import AdValidator
from ..collectors.base import BaseAdsCollector
from ..collectors.google_ads_collector import GoogleAdsCollector
from ..collectors.meta_ads_collector import MetaAdsCollector
from ..collectors.tiktok_collector import TikTokCollector

logger = logging.getLogger(__name__)


class AdsIntelligenceEngine:
    """
    Main entry point for the Ads Intelligence Engine.

    Supports:
        - Execution by platform (run_source)
        - Full execution (run_all)
        - Incremental execution (dedup via fingerprint)
        - Execution by country (pass country param)
        - Querying collected data (get_ads, get_signals)
    """

    def __init__(
        self,
        config: AdsConfig | None = None,
        storage: Any = None,
    ):
        self.config = config or DEFAULT_CONFIG
        self.storage = storage or InMemoryAdsStore()
        self._collectors: dict[str, BaseAdsCollector] = {
            "meta": MetaAdsCollector(self.config, self.storage),
            "google": GoogleAdsCollector(self.config, self.storage),
            "tiktok": TikTokCollector(self.config, self.storage),
        }
        # Keep track of previous run's ads for signal comparison
        self._previous_ads: dict[str, list[AdCanonical]] = {}

    async def run_source(
        self,
        source_name: str,
        query: str = "",
        country: str = "US",
    ) -> AdsRunReport:
        """Run a single platform collector end-to-end."""
        report = AdsRunReport(source=source_name, started_at=datetime.utcnow())
        t0 = time.monotonic()

        collector = self._collectors.get(source_name)
        if not collector:
            report.errors = 1
            report.duration = round(time.monotonic() - t0, 2)
            report.finished_at = datetime.utcnow()
            logger.error("UNKNOWN_SOURCE | source=%s", source_name)
            return report

        # Check if platform is enabled
        platform_config = getattr(self.config, source_name, None)
        if platform_config and not platform_config.enabled:
            report.duration = round(time.monotonic() - t0, 2)
            report.finished_at = datetime.utcnow()
            logger.info("SOURCE_DISABLED | source=%s", source_name)
            return report

        try:
            # 1. Discover targets
            targets = await collector.discover_targets(query=query, country=country)
            report.targets_scanned = len(targets)

            # 2. Get existing fingerprints for dedup
            existing_fps = self.storage.get_existing_fingerprints(source_name)

            # 3. Collect + normalize + validate + persist
            all_normalized: list[AdCanonical] = []
            for target in targets:
                try:
                    raw_ads = await collector.collect(target)
                    for raw in raw_ads:
                        try:
                            ad = collector.normalize(raw)
                            valid, errors = AdValidator.validate(ad)
                            if not valid:
                                logger.debug("AD_INVALID | errors=%s", errors)
                                continue
                            all_normalized.append(ad)
                        except Exception as e:
                            logger.warning("NORMALIZE_ERROR | error=%s", str(e)[:200])
                            report.errors += 1
                except Exception as e:
                    logger.error("COLLECT_ERROR | target=%s | error=%s",
                                 target.query, str(e)[:200])
                    report.errors += 1

            # 4. Dedup
            unique_ads = AdsNormalizer.deduplicate(all_normalized, existing_fps)
            report.ads_collected = len(all_normalized)
            report.ads_new = len(unique_ads)

            # 5. Persist
            for ad in unique_ads:
                collector.persist(ad)

            # 6. Detect signals
            signals = self._detect_signals(source_name, unique_ads)
            report.signals_detected = len(signals)
            for sig in signals:
                self.storage.store_signal(sig)

            # 7. Save current ads as "previous" for next run
            self._previous_ads[source_name] = all_normalized

        except Exception as e:
            logger.error("RUN_SOURCE_ERROR | source=%s | error=%s", source_name, str(e)[:300])
            report.errors += 1

        report.duration = round(time.monotonic() - t0, 2)
        report.finished_at = datetime.utcnow()
        logger.info(
            "RUN_COMPLETE | source=%s | scanned=%d | collected=%d | new=%d | signals=%d | errors=%d | duration=%.2fs",
            source_name, report.targets_scanned, report.ads_collected,
            report.ads_new, report.signals_detected, report.errors, report.duration,
        )
        return report

    async def run_all(
        self,
        query: str = "",
        country: str = "US",
    ) -> list[AdsRunReport]:
        """Run all enabled collectors sequentially."""
        reports: list[AdsRunReport] = []
        for source_name in self._collectors:
            platform_config = getattr(self.config, source_name, None)
            if platform_config and not platform_config.enabled:
                continue
            report = await self.run_source(source_name, query=query, country=country)
            reports.append(report)
        return reports

    def get_ads(
        self,
        platform: str | None = None,
        advertiser: str | None = None,
        country: str | None = None,
    ) -> list[AdCanonical]:
        """Query collected ads with optional filters."""
        return self.storage.get_ads(platform=platform, advertiser=advertiser, country=country)

    def get_signals(self, platform: str | None = None) -> list[SignalEvent]:
        """Query detected signals."""
        return self.storage.get_signals(platform=platform)

    def _detect_signals(
        self, source_name: str, new_ads: list[AdCanonical],
    ) -> list[SignalEvent]:
        """Run all signal detectors."""
        signals: list[SignalEvent] = []
        existing_fps = self.storage.get_existing_fingerprints(source_name)

        # New Ad signals
        signals.extend(NewAdDetector.detect(new_ads, existing_fps))

        # Trend & format signals (need previous run data)
        previous = self._previous_ads.get(source_name, [])
        if previous:
            signals.extend(AngleTrendDetector.detect(new_ads, previous))
            signals.extend(CreativeFormatShiftDetector.detect(new_ads, previous))

        return signals
