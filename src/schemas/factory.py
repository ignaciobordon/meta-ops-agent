from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

Framework = Literal["AIDA", "PAS", "PSF"]


class AdScript(BaseModel):
    """A generated ad creative script ready for production."""

    script_id: str
    angle: str  # L2 tag or custom angle description
    hook: str  # Opening line (first 1-2 sentences)
    body: str  # Main copy (2-4 sentences)
    cta: str  # Call to action (final sentence)
    framework: Framework  # Copywriting structure used
    target_avatar: str  # Which audience persona this targets
    visual_brief: str  # Guidance for designer/video team
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    brand_map_hash: str = ""  # Which BrandMap version informed this script


class ScriptGenerationRequest(BaseModel):
    """Input params for Factory.generate_scripts()."""

    target_angles: list[str]  # L2 Driver tags to generate scripts for
    num_variants_per_angle: int = Field(default=3, ge=1, le=10)
    framework_preference: Framework = "PAS"  # Default to Problem-Agitate-Solve
