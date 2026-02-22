from __future__ import annotations
from datetime import date, datetime
from typing import List, Literal
from pydantic import BaseModel, Field

RecommendationType = Literal["keep", "monitor", "refresh", "kill"]


class CreativeSaturation(BaseModel):
    ad_name: str

    # Composite score 0-100 (higher = more saturated)
    saturation_score: float = Field(ge=0.0, le=100.0)

    # Component scores 0-100
    frequency_score: float = Field(ge=0.0, le=100.0)
    ctr_decay_score: float = Field(ge=0.0, le=100.0)
    cpm_inflation_score: float = Field(ge=0.0, le=100.0)

    # Context
    spend_share_pct: float = Field(ge=0.0, le=100.0)
    total_spend: float
    total_impressions: int
    days_active: int

    # Raw trend metrics
    avg_frequency_recent: float
    ctr_recent: float
    ctr_peak: float
    cpm_recent: float
    cpm_baseline: float

    recommendation: RecommendationType


class OpportunityGap(BaseModel):
    rank: int
    ad_name: str
    saturation_score: float
    rationale: str


class SaturationReport(BaseModel):
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    date_range_start: date
    date_range_end: date
    total_spend_analyzed: float
    total_impressions_analyzed: int
    creatives: List[CreativeSaturation]
    opportunity_gaps: List[OpportunityGap]  # top 3 lowest-saturation creatives
    most_saturated: str  # ad_name of highest saturation_score
