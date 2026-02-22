"""
Tests for CI module — Models and Normalizer.
"""
import pytest
from datetime import datetime
from uuid import uuid4, UUID

from backend.src.ci.models import (
    CICanonicalItem,
    CICompetitor,
    CICompetitorDomain,
    CICompetitorStatus,
    CIDomainType,
    CIIngestRun,
    CIIngestStatus,
    CIItemType,
    CISource,
    CISourceType,
)
from backend.src.ci.normalizer import (
    normalize_ad,
    normalize_landing_page,
    normalize_offer,
    normalize_post,
    _safe_float,
    _safe_int,
    _safe_datetime,
    _extract_list,
)
from backend.src.ci.schemas import (
    NormalizedAd,
    NormalizedLandingPage,
    NormalizedOffer,
    NormalizedPost,
    CompetitorCreate,
    CanonicalItemCreate,
    SearchRequest,
)


# ── Enum tests ────────────────────────────────────────────────────────────────────


class TestCIEnums:
    def test_competitor_status_values(self):
        assert CICompetitorStatus.ACTIVE == "active"
        assert CICompetitorStatus.PAUSED == "paused"
        assert CICompetitorStatus.ARCHIVED == "archived"

    def test_domain_type_values(self):
        assert CIDomainType.AD_LIBRARY == "ad_library"
        assert CIDomainType.WEBSITE == "website"
        assert CIDomainType.SOCIAL == "social"
        assert CIDomainType.MARKETPLACE == "marketplace"

    def test_source_type_values(self):
        assert CISourceType.META_AD_LIBRARY == "meta_ad_library"
        assert CISourceType.MANUAL == "manual"
        assert CISourceType.SCRAPER == "scraper"
        assert CISourceType.API == "api"

    def test_ingest_status_values(self):
        assert CIIngestStatus.QUEUED == "queued"
        assert CIIngestStatus.RUNNING == "running"
        assert CIIngestStatus.SUCCEEDED == "succeeded"
        assert CIIngestStatus.PARTIAL == "partial"
        assert CIIngestStatus.FAILED == "failed"

    def test_item_type_values(self):
        assert CIItemType.AD == "ad"
        assert CIItemType.LANDING_PAGE == "landing_page"
        assert CIItemType.POST == "post"
        assert CIItemType.OFFER == "offer"


# ── Model instantiation tests ──────────────────────────────────────────────────────


class TestCIModels:
    def test_ci_competitor_defaults(self):
        c = CICompetitor(
            org_id=uuid4(),
            name="Acme Corp",
            status=CICompetitorStatus.ACTIVE,
        )
        assert c.name == "Acme Corp"
        assert c.status == CICompetitorStatus.ACTIVE

    def test_ci_competitor_domain(self):
        org_id = uuid4()
        comp_id = uuid4()
        d = CICompetitorDomain(
            org_id=org_id,
            competitor_id=comp_id,
            domain="acme.com",
            domain_type=CIDomainType.WEBSITE,
        )
        assert d.domain == "acme.com"
        assert d.domain_type == CIDomainType.WEBSITE

    def test_ci_source_fields(self):
        s = CISource(
            org_id=uuid4(),
            name="Meta Ad Library",
            source_type=CISourceType.META_AD_LIBRARY,
            enabled=1,
        )
        assert s.name == "Meta Ad Library"
        assert s.enabled == 1

    def test_ci_ingest_run_fields(self):
        r = CIIngestRun(
            org_id=uuid4(),
            source_id=uuid4(),
            status=CIIngestStatus.QUEUED,
            items_fetched=0,
        )
        assert r.status == CIIngestStatus.QUEUED
        assert r.items_fetched == 0

    def test_ci_canonical_item_fields(self):
        item = CICanonicalItem(
            org_id=uuid4(),
            competitor_id=uuid4(),
            item_type=CIItemType.AD,
            external_id="ad_123",
            title="Best Product Ever",
            body_text="Buy now!",
        )
        assert item.item_type == CIItemType.AD
        assert item.external_id == "ad_123"


# ── Normalizer tests ───────────────────────────────────────────────────────────


class TestNormalizer:
    def test_normalize_ad_generic(self):
        raw = {
            "id": "ext_001",
            "headline": "Big Sale",
            "body_text": "50% off everything",
            "cta": "Shop Now",
            "image_urls": ["https://img.example.com/1.jpg"],
            "url": "https://example.com/sale",
            "platform": "meta",
        }
        comp_id = uuid4()
        result = normalize_ad(raw, comp_id)
        assert isinstance(result, NormalizedAd)
        assert result.external_id == "ext_001"
        assert result.headline == "Big Sale"
        assert result.body_text == "50% off everything"
        assert result.cta_text == "Shop Now"
        assert result.competitor_id == comp_id
        assert result.platform == "meta"
        assert len(result.image_urls) == 1

    def test_normalize_ad_meta_format(self):
        raw = {
            "ad_archive_id": "meta_123",
            "page_id": "page_456",
            "ad_creative_bodies": ["Amazing product for you"],
            "ad_creative_link_titles": ["Click Here"],
            "ad_delivery_start_time": "2025-01-15",
        }
        comp_id = uuid4()
        result = normalize_ad(raw, comp_id)
        assert result.external_id == "meta_123"
        assert result.platform == "meta"
        assert result.headline == "Click Here"
        assert result.body_text == "Amazing product for you"

    def test_normalize_landing_page(self):
        raw = {
            "url": "https://example.com/landing",
            "title": "Landing Page Title",
            "h1": "Welcome",
            "body_text": "Sign up today",
            "cta_texts": ["Get Started", "Learn More"],
        }
        comp_id = uuid4()
        result = normalize_landing_page(raw, comp_id)
        assert isinstance(result, NormalizedLandingPage)
        assert result.url == "https://example.com/landing"
        assert result.title == "Landing Page Title"
        assert result.h1_text == "Welcome"
        assert len(result.cta_texts) == 2

    def test_normalize_post(self):
        raw = {
            "id": "post_789",
            "platform": "instagram",
            "caption": "Check out our new product!",
            "hashtags": ["fitness", "health"],
            "likes": 1500,
            "comments": "42",
            "posted_at": "2025-03-01T12:00:00",
        }
        comp_id = uuid4()
        result = normalize_post(raw, comp_id)
        assert isinstance(result, NormalizedPost)
        assert result.platform == "instagram"
        assert result.caption == "Check out our new product!"
        assert result.likes == 1500
        assert result.comments == 42
        assert len(result.hashtags) == 2

    def test_normalize_offer(self):
        raw = {
            "id": "offer_001",
            "type": "discount",
            "title": "Summer Sale",
            "description": "20% off all items",
            "discount": "20%",
            "url": "https://example.com/offer",
            "start_date": "2025-06-01",
            "end_date": "2025-06-30",
        }
        comp_id = uuid4()
        result = normalize_offer(raw, comp_id)
        assert isinstance(result, NormalizedOffer)
        assert result.offer_type == "discount"
        assert result.headline == "Summer Sale"
        assert result.discount_value == "20%"


# ── Helper tests ──────────────────────────────────────────────────────────────


class TestNormalizerHelpers:
    def test_safe_float_valid(self):
        assert _safe_float(3.14) == 3.14
        assert _safe_float("2.5") == 2.5
        assert _safe_float(10) == 10.0

    def test_safe_float_invalid(self):
        assert _safe_float(None) is None
        assert _safe_float("abc") is None
        assert _safe_float([]) is None

    def test_safe_int_valid(self):
        assert _safe_int(42) == 42
        assert _safe_int("100") == 100

    def test_safe_int_invalid(self):
        assert _safe_int(None) is None
        assert _safe_int("abc") is None

    def test_safe_datetime_string(self):
        dt = _safe_datetime("2025-01-15")
        assert isinstance(dt, datetime)
        assert dt.year == 2025

    def test_safe_datetime_iso(self):
        dt = _safe_datetime("2025-01-15T10:30:00")
        assert isinstance(dt, datetime)
        assert dt.hour == 10

    def test_safe_datetime_none(self):
        assert _safe_datetime(None) is None

    def test_safe_datetime_invalid(self):
        assert _safe_datetime("not-a-date") is None

    def test_safe_datetime_object(self):
        now = datetime.utcnow()
        assert _safe_datetime(now) is now

    def test_extract_list_primary(self):
        raw = {"images": ["a.jpg", "b.jpg"]}
        assert _extract_list(raw, "image_urls", "images") == ["a.jpg", "b.jpg"]

    def test_extract_list_fallback(self):
        raw = {"imgs": ["c.jpg"]}
        assert _extract_list(raw, "images", "imgs") == ["c.jpg"]

    def test_extract_list_empty(self):
        assert _extract_list({}, "a", "b") == []

    def test_extract_list_single_value(self):
        raw = {"image_urls": "single.jpg"}
        result = _extract_list(raw, "image_urls", "images")
        assert result == ["single.jpg"]


# ── Pydantic schema tests ──────────────────────────────────────────────────────


class TestPydanticSchemas:
    def test_competitor_create_valid(self):
        c = CompetitorCreate(name="Competitor A")
        assert c.name == "Competitor A"
        assert c.domains == []

    def test_competitor_create_with_domains(self):
        c = CompetitorCreate(
            name="B Corp",
            website_url="https://bcorp.com",
            domains=[{"domain": "bcorp.com", "domain_type": "website"}],
        )
        assert len(c.domains) == 1
        assert c.domains[0].domain == "bcorp.com"

    def test_canonical_item_create(self):
        ci = CanonicalItemCreate(
            competitor_id=uuid4(),
            item_type="ad",
            external_id="ext_1",
            title="Test Ad",
        )
        assert ci.item_type == "ad"

    def test_search_request_defaults(self):
        sr = SearchRequest(query="fitness ads")
        assert sr.n_results == 10
        assert sr.item_types == []
        assert sr.competitor_ids == []
