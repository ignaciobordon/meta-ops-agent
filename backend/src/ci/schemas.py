"""
CI Module — Pydantic schemas for normalization and API serialization.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Canonical normalized schemas ──────────────────────────────────────────────


class NormalizedAd(BaseModel):
    """Normalized representation of a competitor ad."""
    external_id: str
    competitor_id: UUID
    platform: str = "meta"
    headline: Optional[str] = None
    body_text: Optional[str] = None
    cta_text: Optional[str] = None
    image_urls: List[str] = Field(default_factory=list)
    video_url: Optional[str] = None
    landing_page_url: Optional[str] = None
    ad_format: Optional[str] = None  # image, video, carousel
    estimated_spend: Optional[float] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    is_active: bool = True
    raw_data: Dict[str, Any] = Field(default_factory=dict)


class NormalizedLandingPage(BaseModel):
    """Normalized representation of a competitor landing page."""
    external_id: str
    competitor_id: UUID
    url: str
    title: Optional[str] = None
    meta_description: Optional[str] = None
    h1_text: Optional[str] = None
    body_text: Optional[str] = None
    cta_texts: List[str] = Field(default_factory=list)
    form_fields: List[str] = Field(default_factory=list)
    tech_stack: List[str] = Field(default_factory=list)
    screenshot_url: Optional[str] = None
    raw_data: Dict[str, Any] = Field(default_factory=dict)


class NormalizedPost(BaseModel):
    """Normalized representation of a competitor social post."""
    external_id: str
    competitor_id: UUID
    platform: str  # instagram, tiktok, linkedin, x
    post_type: Optional[str] = None  # image, video, carousel, text
    caption: Optional[str] = None
    image_urls: List[str] = Field(default_factory=list)
    video_url: Optional[str] = None
    hashtags: List[str] = Field(default_factory=list)
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    engagement_rate: Optional[float] = None
    posted_at: Optional[datetime] = None
    raw_data: Dict[str, Any] = Field(default_factory=dict)


class NormalizedOffer(BaseModel):
    """Normalized representation of a competitor offer/promo."""
    external_id: str
    competitor_id: UUID
    offer_type: Optional[str] = None  # discount, free_trial, bundle, lead_magnet
    headline: Optional[str] = None
    description: Optional[str] = None
    discount_value: Optional[str] = None  # "20%", "$10 off", "Free"
    url: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    raw_data: Dict[str, Any] = Field(default_factory=dict)


# ── API Request/Response schemas ──────────────────────────────────────────────


class CompetitorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    website_url: Optional[str] = None
    logo_url: Optional[str] = None
    notes: Optional[str] = None
    domains: List["DomainCreate"] = Field(default_factory=list)


class DomainCreate(BaseModel):
    domain: str = Field(..., min_length=1, max_length=512)
    domain_type: str = "website"  # ad_library, website, social, marketplace


class CompetitorUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    website_url: Optional[str] = None
    logo_url: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None


class CompetitorResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    website_url: Optional[str]
    logo_url: Optional[str]
    notes: Optional[str]
    status: str
    meta_json: Dict[str, Any]
    domains: List["DomainResponse"]
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


class DomainResponse(BaseModel):
    id: UUID
    domain: str
    domain_type: str
    verified: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SourceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    source_type: str  # meta_ad_library, manual, scraper, api
    config_json: Dict[str, Any] = Field(default_factory=dict)


class SourceResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    source_type: str
    config_json: Dict[str, Any]
    enabled: int
    last_run_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class CanonicalItemCreate(BaseModel):
    competitor_id: UUID
    source_id: Optional[UUID] = None
    item_type: str  # ad, landing_page, post, offer
    external_id: Optional[str] = None
    title: Optional[str] = None
    body_text: Optional[str] = None
    url: Optional[str] = None
    image_urls: List[str] = Field(default_factory=list)
    canonical_json: Dict[str, Any] = Field(default_factory=dict)
    raw_json: Dict[str, Any] = Field(default_factory=dict)


class CanonicalItemResponse(BaseModel):
    id: UUID
    org_id: UUID
    competitor_id: UUID
    source_id: Optional[UUID]
    item_type: str
    external_id: Optional[str]
    title: Optional[str]
    body_text: Optional[str]
    url: Optional[str]
    image_urls_json: Any
    canonical_json: Dict[str, Any]
    embedding_id: Optional[str]
    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    item_types: List[str] = Field(default_factory=list)  # Filter by ad/post/etc.
    competitor_ids: List[UUID] = Field(default_factory=list)
    n_results: int = Field(default=10, ge=1, le=100)


class SimilarRequest(BaseModel):
    item_id: UUID
    n_results: int = Field(default=5, ge=1, le=50)


class SearchResultItem(BaseModel):
    item: CanonicalItemResponse
    score: float  # Similarity score (0-1, higher = more similar)


class IngestRunResponse(BaseModel):
    id: UUID
    org_id: UUID
    source_id: UUID
    status: str
    items_fetched: int
    items_upserted: int
    items_skipped: int
    error_count: int
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    duration_ms: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}
