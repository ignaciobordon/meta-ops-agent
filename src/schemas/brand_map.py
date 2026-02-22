from __future__ import annotations
import hashlib
from datetime import datetime
from typing import Any, List
from pydantic import BaseModel, Field, BeforeValidator
from typing import Annotated


def _coerce_str(v: Any) -> str:
    """Convert any LLM output quirk to a string."""
    if v is None:
        return ""
    if isinstance(v, dict):
        parts = [str(x) for x in v.values() if x is not None]
        return " ".join(parts) if parts else ""
    if isinstance(v, list):
        return ", ".join(str(i) for i in v if i is not None)
    return str(v)


def _coerce_str_list(v: Any) -> List[str]:
    """Convert any LLM output quirk to a list of strings."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v else []
    if isinstance(v, list):
        return [_coerce_str(item) for item in v if item is not None]
    return [str(v)]


# Annotated types that auto-coerce LLM outputs
LLMStr = Annotated[str, BeforeValidator(_coerce_str)]
LLMStrList = Annotated[List[str], BeforeValidator(_coerce_str_list)]


class CoreIdentity(BaseModel):
    mission: LLMStr = ""
    values: LLMStrList = Field(default_factory=list)
    tone_voice: LLMStr = ""
    personality_traits: LLMStrList = Field(default_factory=list)


class OfferLayer(BaseModel):
    main_product: LLMStr = ""
    upsells: LLMStrList = Field(default_factory=list)
    pricing_psychology: LLMStr = ""
    risk_reversal: LLMStr = ""


class AudienceAvatar(BaseModel):
    avatar_name: LLMStr = ""
    demographics: LLMStr = ""
    psychographics: LLMStr = ""
    pains: LLMStrList = Field(default_factory=list)
    desires: LLMStrList = Field(default_factory=list)
    triggers: LLMStrList = Field(default_factory=list)


class DifferentiationLayer(BaseModel):
    usp: LLMStr = ""
    competitive_moat: LLMStr = ""
    proof_points: LLMStrList = Field(default_factory=list)


class NarrativeAssets(BaseModel):
    lore: LLMStr = ""
    story_hooks: LLMStrList = Field(default_factory=list)
    core_myths: LLMStrList = Field(default_factory=list)


class CreativeDNA(BaseModel):
    color_palette: LLMStrList = Field(default_factory=list)
    typography_intent: LLMStr = ""
    visual_constraints: LLMStrList = Field(default_factory=list)


class MarketContext(BaseModel):
    seasonal_factors: LLMStrList = Field(default_factory=list)
    current_trends: LLMStrList = Field(default_factory=list)


class Competitor(BaseModel):
    name: LLMStr = ""
    strategy_type: LLMStr = ""
    weak_points: LLMStrList = Field(default_factory=list)


class Opportunity(BaseModel):
    gap_id: LLMStr = ""
    strategy_recommendation: LLMStr = ""
    estimated_impact: float = 0.0
    impact_reasoning: LLMStr = ""


class BrandMapMetadata(BaseModel):
    version: str = "2.0"
    hash: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BrandMap(BaseModel):
    core_identity: CoreIdentity = Field(default_factory=CoreIdentity)
    offer_layer: OfferLayer = Field(default_factory=OfferLayer)
    audience_model: List[AudienceAvatar] = Field(default_factory=list)
    differentiation_layer: DifferentiationLayer = Field(default_factory=DifferentiationLayer)
    narrative_assets: NarrativeAssets = Field(default_factory=NarrativeAssets)
    creative_dna: CreativeDNA = Field(default_factory=CreativeDNA)
    market_context: MarketContext = Field(default_factory=MarketContext)
    competitor_map: List[Competitor] = Field(default_factory=list)
    opportunity_map: List[Opportunity] = Field(default_factory=list)
    metadata: BrandMapMetadata

    @classmethod
    def content_hash(cls, raw_text: str) -> str:
        return hashlib.sha256(raw_text.encode()).hexdigest()[:16]
