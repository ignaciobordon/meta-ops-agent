"""Configuration for the Opportunity Detection Engine."""
from __future__ import annotations

from pydantic import BaseModel, Field


class OpportunityConfig(BaseModel):
    """Tunable knobs for opportunity detection."""
    # Window sizes
    recent_window_days: int = 7
    baseline_window_days: int = 30
    # Spike detection
    spike_threshold: float = 2.0          # multiplier over baseline
    min_ads_for_spike: int = 3
    # Angle trend
    trend_min_frequency_increase: float = 0.20
    trend_min_occurrences: int = 2
    # Offer change
    offer_price_change_pct: float = 0.10  # 10% price change = significant
    # Format shift
    format_shift_min_delta: float = 0.15  # 15pp shift = significant
    # Keyword emergence
    keyword_min_frequency: int = 3
    keyword_max_stopword_len: int = 2
    # Scoring
    novelty_decay_count: int = 5          # after N similar opps, novelty → 0
    # Dedup
    dedup_window_hours: int = 48
    dedup_evidence_overlap_min: int = 1
    # Expiration
    default_expiry_days: int = 14


DEFAULT_CONFIG = OpportunityConfig()
