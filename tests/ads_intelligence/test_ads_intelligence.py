"""Tests for the Ads Intelligence Engine — 40+ tests covering all blocks."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import pytest

from src.engines.ads_intelligence.core.models import (
    AdCanonical, AdFormat, AdPlatform, AdsRunReport,
    CollectorTarget, SignalEvent, SignalType,
)
from src.engines.ads_intelligence.core.config import AdsConfig, PlatformConfig, DEFAULT_CONFIG
from src.engines.ads_intelligence.core.normalizer import (
    AdsNormalizer, clean_text, clean_url, detect_cta,
    detect_format_from_media, detect_language, generate_fingerprint,
)
from src.engines.ads_intelligence.core.validators import AdValidator
from src.engines.ads_intelligence.core.storage import InMemoryAdsStore
from src.engines.ads_intelligence.core.signals import (
    AngleTrendDetector, CreativeFormatShiftDetector, NewAdDetector,
)
from src.engines.ads_intelligence.core.anti_block import (
    RateLimiter, RetryPolicy, random_headers, api_headers,
)
from src.engines.ads_intelligence.core.ads_engine import AdsIntelligenceEngine
from src.engines.ads_intelligence.collectors.meta_ads_collector import MetaAdsCollector
from src.engines.ads_intelligence.collectors.google_ads_collector import GoogleAdsCollector
from src.engines.ads_intelligence.collectors.tiktok_collector import TikTokCollector


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_ad(
    platform: AdPlatform = AdPlatform.META,
    advertiser: str = "TestBrand",
    headline: str = "Buy Now",
    copy: str = "Get the best deal today",
    cta: str = "shop now",
    fmt: AdFormat = AdFormat.IMAGE,
    country: str = "US",
    landing_url: str = "https://example.com/product",
    media_url: str = "https://cdn.example.com/img.jpg",
) -> AdCanonical:
    ad = AdCanonical(
        platform=platform,
        advertiser=advertiser,
        headline=headline,
        copy=copy,
        cta=cta,
        format=fmt,
        country=country,
        landing_url=landing_url,
        media_url=media_url,
    )
    ad.fingerprint = generate_fingerprint(ad)
    return ad


# ══════════════════════════════════════════════════════════════════════════════
# 1. NORMALIZER TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestNormalizerUtils:

    def test_clean_text_collapses_whitespace(self):
        assert clean_text("  hello   world  ") == "hello world"

    def test_clean_text_empty(self):
        assert clean_text("") == ""
        assert clean_text(None) == ""

    def test_clean_url_strips_tracking(self):
        url = "https://example.com/page?utm_source=fb&utm_medium=cpc&real=1"
        cleaned = clean_url(url)
        assert "utm_source" not in cleaned
        assert "utm_medium" not in cleaned
        assert "real=1" in cleaned

    def test_clean_url_strips_fbclid(self):
        url = "https://example.com/?fbclid=abc123&foo=bar"
        cleaned = clean_url(url)
        assert "fbclid" not in cleaned
        assert "foo=bar" in cleaned

    def test_detect_language_english(self):
        assert detect_language("The best product for your needs") == "en"

    def test_detect_language_spanish(self):
        assert detect_language("El mejor producto para tu hogar") == "es"

    def test_detect_language_unknown(self):
        assert detect_language("") == "unknown"

    def test_detect_cta_found(self):
        assert detect_cta("Click here to shop now!") == "shop now"

    def test_detect_cta_spanish(self):
        assert detect_cta("Haz clic para comprar ahora") == "comprar ahora"

    def test_detect_cta_none(self):
        assert detect_cta("No action phrase here") == ""

    def test_detect_format_video(self):
        assert detect_format_from_media("https://cdn.com/video.mp4") == AdFormat.VIDEO

    def test_detect_format_image(self):
        assert detect_format_from_media("https://cdn.com/img.jpg") == AdFormat.IMAGE

    def test_detect_format_carousel(self):
        assert detect_format_from_media("https://cdn.com/x", {"format": "carousel"}) == AdFormat.CAROUSEL

    def test_detect_format_text_no_media(self):
        assert detect_format_from_media("") == AdFormat.TEXT


class TestNormalizerPlatforms:

    def test_normalize_meta(self):
        raw = {
            "page_name": "CoolBrand",
            "ad_creative_body": "Amazing product, shop now!",
            "ad_creative_link_title": "Best Deal",
            "ad_creative_link_url": "https://coolbrand.com?utm_source=fb",
            "ad_creative_image_url": "https://cdn.fb.com/img.png",
            "country": "US",
            "publisher_platform": "facebook",
        }
        ad = AdsNormalizer.normalize_meta(raw)
        assert ad.platform == AdPlatform.META
        assert ad.advertiser == "CoolBrand"
        assert ad.headline == "Best Deal"
        assert "shop now" in ad.cta
        assert ad.format == AdFormat.IMAGE
        assert ad.fingerprint
        assert len(ad.fingerprint) == 16
        assert "utm_source" not in ad.landing_url

    def test_normalize_google(self):
        raw = {
            "advertiser_name": "GoogleBrand",
            "headline": "Search the best",
            "description": "Find what you need today",
            "destination_url": "https://googlebrand.com",
            "image_url": "https://cdn.google.com/img.webp",
            "country": "US",
        }
        ad = AdsNormalizer.normalize_google(raw)
        assert ad.platform == AdPlatform.GOOGLE
        assert ad.advertiser == "GoogleBrand"
        assert ad.headline == "Search the best"
        assert ad.fingerprint

    def test_normalize_tiktok(self):
        raw = {
            "brand_name": "TikTokBrand",
            "title": "Viral product",
            "caption": "Everyone is buying this now",
            "video_url": "https://cdn.tiktok.com/vid.mp4",
            "country_code": "US",
        }
        ad = AdsNormalizer.normalize_tiktok(raw)
        assert ad.platform == AdPlatform.TIKTOK
        assert ad.advertiser == "TikTokBrand"
        assert ad.format == AdFormat.VIDEO
        assert ad.fingerprint

    def test_normalize_dispatch(self):
        raw = {"page_name": "Test", "ad_creative_body": "Hello world"}
        ad = AdsNormalizer.normalize("meta", raw)
        assert ad.platform == AdPlatform.META

    def test_normalize_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown platform"):
            AdsNormalizer.normalize("pinterest", {})


class TestDeduplication:

    def test_dedup_removes_duplicates(self):
        ad1 = _make_ad(headline="Same headline", copy="Same copy")
        ad2 = _make_ad(headline="Same headline", copy="Same copy")
        unique = AdsNormalizer.deduplicate([ad1, ad2])
        assert len(unique) == 1

    def test_dedup_keeps_different(self):
        ad1 = _make_ad(headline="Headline A")
        ad2 = _make_ad(headline="Headline B")
        unique = AdsNormalizer.deduplicate([ad1, ad2])
        assert len(unique) == 2

    def test_dedup_respects_existing_fingerprints(self):
        ad = _make_ad(headline="Existing ad")
        existing = {ad.fingerprint}
        unique = AdsNormalizer.deduplicate([ad], existing)
        assert len(unique) == 0


# ══════════════════════════════════════════════════════════════════════════════
# 2. FINGERPRINT TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestFingerprint:

    def test_deterministic(self):
        ad = _make_ad()
        fp1 = generate_fingerprint(ad)
        fp2 = generate_fingerprint(ad)
        assert fp1 == fp2

    def test_different_headline_different_fp(self):
        ad1 = _make_ad(headline="Buy Now")
        ad2 = _make_ad(headline="Get Started")
        assert generate_fingerprint(ad1) != generate_fingerprint(ad2)

    def test_different_platform_different_fp(self):
        ad1 = _make_ad(platform=AdPlatform.META)
        ad2 = _make_ad(platform=AdPlatform.GOOGLE)
        assert generate_fingerprint(ad1) != generate_fingerprint(ad2)

    def test_whitespace_insensitive(self):
        ad1 = _make_ad(headline="Buy   Now")
        ad2 = _make_ad(headline="Buy Now")
        assert generate_fingerprint(ad1) == generate_fingerprint(ad2)

    def test_case_insensitive(self):
        ad1 = _make_ad(headline="BUY NOW")
        ad2 = _make_ad(headline="buy now")
        assert generate_fingerprint(ad1) == generate_fingerprint(ad2)


# ══════════════════════════════════════════════════════════════════════════════
# 3. VALIDATOR TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestValidator:

    def test_valid_ad_passes(self):
        ad = _make_ad()
        valid, errors = AdValidator.validate(ad)
        assert valid
        assert errors == []

    def test_missing_advertiser(self):
        ad = _make_ad(advertiser="")
        valid, errors = AdValidator.validate(ad)
        assert not valid
        assert any("Advertiser" in e for e in errors)

    def test_headline_too_long(self):
        ad = _make_ad(headline="x" * 600)
        valid, errors = AdValidator.validate(ad)
        assert not valid
        assert any("Headline too long" in e for e in errors)

    def test_copy_too_long(self):
        ad = _make_ad(copy="x" * 6000)
        valid, errors = AdValidator.validate(ad)
        assert not valid
        assert any("Copy too long" in e for e in errors)

    def test_invalid_landing_url(self):
        ad = _make_ad(landing_url="not-a-url")
        valid, errors = AdValidator.validate(ad)
        assert not valid
        assert any("Invalid landing URL" in e for e in errors)

    def test_no_content(self):
        ad = _make_ad(headline="", copy="")
        valid, errors = AdValidator.validate(ad)
        assert not valid
        assert any("at least headline or copy" in e for e in errors)

    def test_no_fingerprint(self):
        ad = _make_ad()
        ad.fingerprint = ""
        valid, errors = AdValidator.validate(ad)
        assert not valid
        assert any("Fingerprint" in e for e in errors)

    def test_is_valid_shorthand(self):
        ad = _make_ad()
        assert AdValidator.is_valid(ad)


# ══════════════════════════════════════════════════════════════════════════════
# 4. STORAGE TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestStorage:

    def test_store_and_retrieve(self):
        store = InMemoryAdsStore()
        ad = _make_ad()
        store.store_ad(ad)
        assert store.ad_count() == 1
        retrieved = store.get_ad(ad.fingerprint)
        assert retrieved is not None
        assert retrieved.advertiser == "TestBrand"

    def test_dedup_on_store(self):
        store = InMemoryAdsStore()
        ad1 = _make_ad()
        ad2 = _make_ad()  # same fingerprint
        store.store_ad(ad1)
        store.store_ad(ad2)
        assert store.ad_count() == 1  # not duplicated

    def test_existing_fingerprints(self):
        store = InMemoryAdsStore()
        store.store_ad(_make_ad(platform=AdPlatform.META))
        store.store_ad(_make_ad(platform=AdPlatform.GOOGLE, headline="Different"))
        assert len(store.get_existing_fingerprints()) == 2
        assert len(store.get_existing_fingerprints("meta")) == 1

    def test_store_and_get_signals(self):
        store = InMemoryAdsStore()
        sig = SignalEvent(
            type=SignalType.NEW_AD,
            platform="meta",
            entity="TestBrand",
            confidence_score=1.0,
        )
        store.store_signal(sig)
        assert store.signal_count() == 1
        assert len(store.get_signals("meta")) == 1
        assert len(store.get_signals("google")) == 0

    def test_filter_by_country(self):
        store = InMemoryAdsStore()
        store.store_ad(_make_ad(country="US", headline="US ad"))
        store.store_ad(_make_ad(country="AR", headline="AR ad"))
        us_ads = store.get_ads(country="US")
        assert len(us_ads) == 1
        assert us_ads[0].country == "US"

    def test_filter_by_advertiser(self):
        store = InMemoryAdsStore()
        store.store_ad(_make_ad(advertiser="BrandA", headline="A1"))
        store.store_ad(_make_ad(advertiser="BrandB", headline="B1"))
        results = store.get_ads(advertiser="BrandA")
        assert len(results) == 1


# ══════════════════════════════════════════════════════════════════════════════
# 5. SIGNAL DETECTOR TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestNewAdDetector:

    def test_detects_new_ads(self):
        ads = [_make_ad(headline="Brand new")]
        signals = NewAdDetector.detect(ads, existing_fingerprints=set())
        assert len(signals) == 1
        assert signals[0].type == SignalType.NEW_AD
        assert signals[0].confidence_score == 1.0

    def test_ignores_existing(self):
        ad = _make_ad()
        signals = NewAdDetector.detect([ad], existing_fingerprints={ad.fingerprint})
        assert len(signals) == 0


class TestAngleTrendDetector:

    def test_detects_increasing_hook(self):
        # Previous: 1/5 ads have "free"
        previous = [_make_ad(headline=f"Product {i}") for i in range(5)]
        previous[0].copy = "Get it free today"
        # Current: 4/5 ads have "free"
        current = [_make_ad(headline=f"Product {i}") for i in range(5)]
        for i in range(4):
            current[i].copy = "Free offer limited time"

        signals = AngleTrendDetector.detect(current, previous, min_frequency_increase=0.2)
        free_signals = [s for s in signals if "free" in s.entity]
        assert len(free_signals) >= 1

    def test_no_signals_if_no_previous(self):
        current = [_make_ad(copy="Free stuff")]
        signals = AngleTrendDetector.detect(current, [], min_frequency_increase=0.2)
        assert len(signals) == 0


class TestFormatShiftDetector:

    def test_detects_image_to_video_shift(self):
        previous = [_make_ad(fmt=AdFormat.IMAGE) for _ in range(5)]
        current = [_make_ad(fmt=AdFormat.VIDEO, headline=f"V{i}") for i in range(5)]
        signals = CreativeFormatShiftDetector.detect(current, previous, min_shift=0.15)
        format_signals = [s for s in signals if s.entity.startswith("format:")]
        assert len(format_signals) >= 1

    def test_detects_copy_length_shift(self):
        previous = [_make_ad(copy="short") for _ in range(5)]
        current = [_make_ad(copy="x" * 500, headline=f"Long{i}") for i in range(5)]
        signals = CreativeFormatShiftDetector.detect(current, previous, min_shift=0.15)
        length_signals = [s for s in signals if "copy_length" in s.entity]
        assert len(length_signals) >= 1

    def test_no_shift_when_empty(self):
        signals = CreativeFormatShiftDetector.detect([], [])
        assert len(signals) == 0


# ══════════════════════════════════════════════════════════════════════════════
# 6. ANTI-BLOCK TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestAntiBlock:

    def test_random_headers_has_ua(self):
        h = random_headers()
        assert "User-Agent" in h
        assert len(h["User-Agent"]) > 20

    def test_random_headers_vary(self):
        headers_set = {random_headers()["User-Agent"] for _ in range(50)}
        assert len(headers_set) > 1

    def test_api_headers_json(self):
        h = api_headers()
        assert "application/json" in h["Accept"]

    def test_api_headers_extra(self):
        h = api_headers({"X-Custom": "test"})
        assert h["X-Custom"] == "test"

    def test_retry_policy_should_retry_500(self):
        policy = RetryPolicy(max_retries=3)
        assert policy.should_retry(0, 500)
        assert policy.should_retry(2, 500)
        assert not policy.should_retry(3, 500)

    def test_retry_policy_should_retry_429(self):
        policy = RetryPolicy(max_retries=3)
        assert policy.should_retry(0, 429)

    def test_retry_policy_no_retry_404(self):
        policy = RetryPolicy(max_retries=3)
        assert not policy.should_retry(0, 404)

    def test_retry_backoff_increases(self):
        policy = RetryPolicy(base_backoff=1.0)
        d0 = policy.get_delay(0)
        d1 = policy.get_delay(1)
        d2 = policy.get_delay(2)
        # Exponential: each roughly doubles (with jitter)
        assert d1 > d0 * 0.5
        assert d2 > d1 * 0.5

    def test_rate_limiter_creation(self):
        rl = RateLimiter(rpm=60)
        assert rl._interval == pytest.approx(1.0)


# ══════════════════════════════════════════════════════════════════════════════
# 7. COLLECTOR TESTS (interface compliance)
# ══════════════════════════════════════════════════════════════════════════════

class TestCollectorInterface:

    def test_meta_collector_is_base(self):
        c = MetaAdsCollector()
        assert hasattr(c, "discover_targets")
        assert hasattr(c, "collect")
        assert hasattr(c, "normalize")
        assert hasattr(c, "validate")
        assert hasattr(c, "persist")

    def test_google_collector_is_base(self):
        c = GoogleAdsCollector()
        assert hasattr(c, "discover_targets")
        assert hasattr(c, "collect")

    def test_tiktok_collector_is_base(self):
        c = TikTokCollector()
        assert hasattr(c, "discover_targets")
        assert hasattr(c, "collect")

    def test_meta_discover_targets(self):
        c = MetaAdsCollector()
        targets = asyncio.get_event_loop().run_until_complete(
            c.discover_targets(query="nike", country="US")
        )
        assert len(targets) >= 1
        assert targets[0].platform == AdPlatform.META
        assert targets[0].query == "nike"

    def test_google_discover_targets(self):
        c = GoogleAdsCollector()
        targets = asyncio.get_event_loop().run_until_complete(
            c.discover_targets(query="adidas", country="US")
        )
        assert len(targets) >= 1
        assert targets[0].platform == AdPlatform.GOOGLE

    def test_tiktok_discover_targets(self):
        c = TikTokCollector()
        targets = asyncio.get_event_loop().run_until_complete(
            c.discover_targets(query="fashion", country="US")
        )
        assert len(targets) >= 1
        assert targets[0].platform == AdPlatform.TIKTOK

    def test_meta_normalize_and_validate(self):
        c = MetaAdsCollector()
        raw = {
            "page_name": "TestPage",
            "ad_creative_body": "Buy the best product",
            "ad_creative_link_title": "Best Product",
            "ad_creative_link_url": "https://example.com",
            "ad_creative_image_url": "https://cdn.example.com/img.jpg",
        }
        ad = c.normalize(raw)
        assert ad.platform == AdPlatform.META
        assert c.validate(ad)

    def test_meta_persist(self):
        store = InMemoryAdsStore()
        c = MetaAdsCollector(storage=store)
        ad = _make_ad()
        c.persist(ad)
        assert store.ad_count() == 1

    def test_meta_html_parser_empty(self):
        """Parser returns empty list for non-ad HTML."""
        result = MetaAdsCollector._parse_ad_library_html("<html><body>No ads here</body></html>")
        assert result == []

    def test_google_html_parser_empty(self):
        result = GoogleAdsCollector._parse_transparency_html("<html><body>Nothing</body></html>")
        assert result == []


# ══════════════════════════════════════════════════════════════════════════════
# 8. CONFIG TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestConfig:

    def test_default_config(self):
        config = DEFAULT_CONFIG
        assert config.meta.enabled
        assert config.google.enabled
        assert config.tiktok.enabled
        assert config.meta.max_retries == 3

    def test_custom_config(self):
        config = AdsConfig(
            meta=PlatformConfig(enabled=False, api_key="test_key"),
            google=PlatformConfig(rate_limit_rpm=10),
        )
        assert not config.meta.enabled
        assert config.meta.api_key == "test_key"
        assert config.google.rate_limit_rpm == 10


# ══════════════════════════════════════════════════════════════════════════════
# 9. MODEL SERIALIZATION TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestModels:

    def test_ad_canonical_json(self):
        ad = _make_ad()
        data = ad.model_dump()
        assert data["platform"] == "meta"
        assert data["advertiser"] == "TestBrand"
        # Round-trip
        restored = AdCanonical.model_validate(data)
        assert restored.fingerprint == ad.fingerprint

    def test_signal_event_json(self):
        sig = SignalEvent(
            type=SignalType.NEW_AD,
            platform="meta",
            entity="TestBrand",
            new_value={"headline": "test"},
            confidence_score=0.95,
        )
        data = sig.model_dump()
        assert data["type"] == "new_ad"
        assert data["confidence_score"] == 0.95

    def test_ads_run_report_json(self):
        report = AdsRunReport(
            source="meta",
            targets_scanned=3,
            ads_collected=25,
            ads_new=10,
            signals_detected=5,
            duration=2.34,
        )
        data = report.model_dump()
        assert data["source"] == "meta"
        assert data["ads_new"] == 10

    def test_collector_target_json(self):
        target = CollectorTarget(
            platform=AdPlatform.TIKTOK,
            query="fashion",
            country="AR",
        )
        data = target.model_dump()
        assert data["platform"] == "tiktok"
        assert data["country"] == "AR"


# ══════════════════════════════════════════════════════════════════════════════
# 10. ENGINE ORCHESTRATION TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestEngine:

    def test_engine_init(self):
        engine = AdsIntelligenceEngine()
        assert "meta" in engine._collectors
        assert "google" in engine._collectors
        assert "tiktok" in engine._collectors

    def test_engine_get_ads_empty(self):
        engine = AdsIntelligenceEngine()
        ads = engine.get_ads()
        assert ads == []

    def test_engine_get_signals_empty(self):
        engine = AdsIntelligenceEngine()
        signals = engine.get_signals()
        assert signals == []

    def test_engine_unknown_source(self):
        engine = AdsIntelligenceEngine()
        report = asyncio.get_event_loop().run_until_complete(
            engine.run_source("pinterest")
        )
        assert report.errors == 1

    def test_engine_disabled_source(self):
        config = AdsConfig(meta=PlatformConfig(enabled=False))
        engine = AdsIntelligenceEngine(config=config)
        report = asyncio.get_event_loop().run_until_complete(
            engine.run_source("meta")
        )
        assert report.ads_collected == 0
        assert report.errors == 0

    def test_engine_manual_ingest_and_query(self):
        """Simulate manual ingestion → query pipeline."""
        engine = AdsIntelligenceEngine()

        # Manually store ads (simulating a successful collect)
        ad1 = _make_ad(platform=AdPlatform.META, advertiser="Nike", headline="Just Do It", country="US")
        ad2 = _make_ad(platform=AdPlatform.GOOGLE, advertiser="Adidas", headline="Impossible Is Nothing", country="US")
        ad3 = _make_ad(platform=AdPlatform.META, advertiser="Nike", headline="Air Max Sale", country="AR")

        engine.storage.store_ad(ad1)
        engine.storage.store_ad(ad2)
        engine.storage.store_ad(ad3)

        # Query
        all_ads = engine.get_ads()
        assert len(all_ads) == 3

        meta_ads = engine.get_ads(platform="meta")
        assert len(meta_ads) == 2

        ar_ads = engine.get_ads(country="AR")
        assert len(ar_ads) == 1

        nike_ads = engine.get_ads(advertiser="Nike")
        assert len(nike_ads) == 2

    def test_engine_signals_pipeline(self):
        """Full signal detection pipeline with manual data."""
        engine = AdsIntelligenceEngine()

        # Store some ads as "existing"
        existing = _make_ad(headline="Old ad")
        engine.storage.store_ad(existing)

        # New ads to detect
        new_ads = [
            _make_ad(headline="Brand new ad 1"),
            _make_ad(headline="Brand new ad 2"),
        ]

        # Run new ad detection
        fps = engine.storage.get_existing_fingerprints()
        signals = NewAdDetector.detect(new_ads, fps)
        assert len(signals) == 2
        for sig in signals:
            engine.storage.store_signal(sig)

        assert engine.storage.signal_count() == 2
        assert len(engine.get_signals()) == 2
