"""Models for the Opportunity Detection Engine."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Input model ──────────────────────────────────────────────────────────────

class CanonicalItem(BaseModel):
    """Universal input item — represents an ad, page, offer, or signal."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str = ""            # "ads_intelligence", "web_intelligence"
    platform: str = ""          # "meta", "google", "tiktok", "web"
    competitor: str = ""        # advertiser or domain name
    item_type: str = "ad"       # "ad", "page", "offer", "signal"
    headline: str = ""
    body: str = ""              # ad copy / page text
    cta: str = ""
    format: str = ""            # "image", "video", "carousel", "text"
    country: str = ""
    url: str = ""
    price: Optional[float] = None
    discount: str = ""
    guarantee: str = ""
    keywords: list[str] = Field(default_factory=list)
    fingerprint: str = ""
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


# ── Opportunity output ───────────────────────────────────────────────────────

class OpportunityType(str, Enum):
    NEW_ADS_SPIKE = "new_ads_spike"
    ANGLE_TREND_RISE = "angle_trend_rise"
    COMPETITOR_OFFER_CHANGE = "competitor_offer_change"
    FORMAT_DOMINANCE_SHIFT = "format_dominance_shift"
    KEYWORD_EMERGENCE = "keyword_emergence"


class Opportunity(BaseModel):
    """A detected strategic opportunity."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: OpportunityType
    title: str
    description: str
    confidence_score: float = 0.0      # 0–1
    impact_score: float = 0.0          # 0–1
    priority_score: float = 0.0        # 0–1 (computed)
    evidence_ids: list[str] = Field(default_factory=list)
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    suggested_actions: list[str] = Field(default_factory=list)
    rationale: str = ""
    version: int = 1


# ── Telemetry ────────────────────────────────────────────────────────────────

class OpportunityRunReport(BaseModel):
    """Telemetry for a detection run."""
    detectors_executed: int = 0
    opportunities_found: int = 0
    opportunities_new: int = 0
    opportunities_deduped: int = 0
    duration: float = 0.0
    errors: int = 0
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
