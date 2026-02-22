"""Pydantic models for the Web Intelligence Engine. All JSON-serializable."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Crawl ──────────────────────────────────────────────────────────────────────


class CrawlTier(str, Enum):
    A = "A"  # daily
    B = "B"  # weekly
    C = "C"  # monthly


class CrawlTarget(BaseModel):
    domain: str
    tier: CrawlTier = CrawlTier.B
    max_depth: int = 3
    max_pages: int = 50
    tags: list[str] = Field(default_factory=list)
    last_crawl_at: datetime | None = None
    next_run_at: datetime | None = None


class CrawlResult(BaseModel):
    url: str
    status_code: int
    content_hash: str
    content_length: int
    title: str = ""
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    links_found: int = 0
    error: str | None = None


# ── Extraction ─────────────────────────────────────────────────────────────────


class ExtractedPageData(BaseModel):
    url: str
    content_hash: str
    title: str = ""
    headlines: list[str] = Field(default_factory=list)
    offers: list[str] = Field(default_factory=list)
    pricing_blocks: list[str] = Field(default_factory=list)
    cta_phrases: list[str] = Field(default_factory=list)
    guarantees: list[str] = Field(default_factory=list)
    product_names: list[str] = Field(default_factory=list)
    hero_sections: list[str] = Field(default_factory=list)
    structured_lists: list[list[str]] = Field(default_factory=list)
    semantic_keywords: list[str] = Field(default_factory=list)
    extracted_at: datetime = Field(default_factory=datetime.utcnow)


# ── Signals ────────────────────────────────────────────────────────────────────


class SignalType(str, Enum):
    NEW_PAGES = "new_pages"
    REMOVED_PAGES = "removed_pages"
    HEADLINE_CHANGES = "headline_changes"
    PRICING_CHANGES = "pricing_changes"
    NEW_OFFERS = "new_offers"
    CTA_CHANGES = "cta_changes"


class SignalEvent(BaseModel):
    type: SignalType
    url: str
    old_value: Any = None
    new_value: Any = None
    detected_at: datetime = Field(default_factory=datetime.utcnow)


# ── Telemetry ──────────────────────────────────────────────────────────────────


class CrawlReport(BaseModel):
    domain: str
    pages_crawled: int = 0
    pages_skipped: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    signals_detected: int = 0
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None
