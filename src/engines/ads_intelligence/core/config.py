"""Configuration for Ads Intelligence Engine."""
from __future__ import annotations

from pydantic import BaseModel, Field


class PlatformConfig(BaseModel):
    """Per-platform settings."""
    enabled: bool = True
    api_key: str = ""
    rate_limit_rpm: int = 30
    max_ads_per_query: int = 50
    countries: list[str] = Field(default_factory=lambda: ["US", "AR", "ES", "MX", "BR"])
    request_timeout: float = 30.0
    max_retries: int = 3
    retry_backoff: float = 2.0


class AdsConfig(BaseModel):
    """Global ads intelligence configuration."""
    meta: PlatformConfig = Field(default_factory=PlatformConfig)
    google: PlatformConfig = Field(default_factory=PlatformConfig)
    tiktok: PlatformConfig = Field(default_factory=PlatformConfig)
    min_delay: float = 1.0
    max_delay: float = 5.0
    dedup_window_days: int = 90


DEFAULT_CONFIG = AdsConfig()
