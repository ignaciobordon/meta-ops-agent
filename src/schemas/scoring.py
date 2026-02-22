from __future__ import annotations
from pydantic import BaseModel, Field


class DimensionScore(BaseModel):
    score: float = Field(ge=0.0, le=10.0)
    reasoning: str = ""


class EvaluationScore(BaseModel):
    # Rubric dimensions
    hook_strength: DimensionScore
    brand_alignment: DimensionScore
    clarity: DimensionScore
    audience_fit: DimensionScore
    cta_quality: DimensionScore

    # Weighted composite (computed after LLM response, not by LLM)
    overall_score: float = Field(ge=0.0, le=10.0)
    overall_reasoning: str = ""

    # Reference fields for traceability
    asset_snippet: str = ""
    brand_map_hash: str = ""

    # Weights used for the overall_score calculation
    WEIGHTS: dict = Field(
        default={
            "hook_strength": 0.25,
            "brand_alignment": 0.20,
            "clarity": 0.20,
            "audience_fit": 0.20,
            "cta_quality": 0.15,
        },
        exclude=True,
    )
