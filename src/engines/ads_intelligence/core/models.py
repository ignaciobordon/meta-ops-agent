"""Canonical models for the Ads Intelligence Engine."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class AdPlatform(str, Enum):
    META = "meta"
    GOOGLE = "google"
    TIKTOK = "tiktok"


class AdFormat(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    CAROUSEL = "carousel"
    TEXT = "text"
    UNKNOWN = "unknown"


class AdCanonical(BaseModel):  # noqa: W0622
    """Canonical ad schema — every collector must produce this."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    platform: AdPlatform
    advertiser: str
    headline: str = ""
    copy: str = ""  # ad copy text (shadows BaseModel.copy, use model_copy() instead)
    cta: str = ""
    format: AdFormat = AdFormat.UNKNOWN
    platform_position: str = ""
    country: str = ""
    landing_url: str = ""
    media_url: str = ""
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)
    fingerprint: str = ""


class SignalType(str, Enum):
    NEW_AD = "new_ad"
    ANGLE_TREND = "angle_trend"
    FORMAT_SHIFT = "format_shift"


class SignalEvent(BaseModel):
    """A detected intelligence signal."""
    type: SignalType
    platform: str
    entity: str
    previous_value: Any = None
    new_value: Any = None
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    confidence_score: float = 0.0


class CollectorTarget(BaseModel):
    """A target to collect ads from."""
    advertiser_id: str = ""
    advertiser_name: str = ""
    platform: AdPlatform
    country: str = "US"
    query: str = ""
    metadata: dict = Field(default_factory=dict)


class AdsRunReport(BaseModel):
    """Telemetry for a single collection run."""
    source: str
    targets_scanned: int = 0
    ads_collected: int = 0
    ads_new: int = 0
    signals_detected: int = 0
    duration: float = 0.0
    errors: int = 0
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
