"""
Content Studio — Output Validation Schemas per channel.
Pydantic models for LLM output validation.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


# ── Per-Channel Output Schemas ────────────────────────────────────────────────

class IGReelOutput(BaseModel):
    hook: str = ""
    script: str = ""
    cta: str = ""
    hashtags: List[str] = []
    music_suggestion: str = ""
    shot_list: List[str] = []


class IGPostOutput(BaseModel):
    caption: str = ""
    cta: str = ""
    hashtags: List[str] = []
    visual_description: str = ""


class IGCarouselSlide(BaseModel):
    slide_number: int = 0
    copy: str = ""
    visual_direction: str = ""
    type: str = ""

    class Config:
        extra = "allow"


class IGCarouselOutput(BaseModel):
    slides: List[Any] = []  # Accept both str and dict slides from LLM
    caption: str = ""
    cta: str = ""
    hashtags: List[str] = []


class IGStoryOutput(BaseModel):
    frames: List[str] = []
    cta: str = ""
    sticker_suggestions: List[str] = []


class TikTokShortOutput(BaseModel):
    hook: str = ""
    script: str = ""
    cta: str = ""
    hashtags: List[str] = []
    sound_suggestion: str = ""
    text_overlays: List[str] = []


class YTShortOutput(BaseModel):
    hook: str = ""
    script: str = ""
    cta: str = ""
    title: str = ""
    description: str = ""


class YTLongOutput(BaseModel):
    title: str = ""
    description: str = ""
    script_outline: str = ""
    hook: str = ""
    cta: str = ""
    tags: List[str] = []
    chapters: List[str] = []


class FBFeedOutput(BaseModel):
    copy: str = ""
    headline: str = ""
    cta: str = ""
    visual_description: str = ""


class FBAdCopyOutput(BaseModel):
    primary_text: str = ""
    headline: str = ""
    description: str = ""
    cta_button: str = ""
    link_description: str = ""


class XPostOutput(BaseModel):
    text: str = ""
    cta: str = ""
    hashtags: List[str] = []


class XThreadOutput(BaseModel):
    tweets: List[str] = []
    hook_tweet: str = ""
    cta_tweet: str = ""


class LinkedInPostOutput(BaseModel):
    text: str = ""
    hook: str = ""
    cta: str = ""
    hashtags: List[str] = []


class EmailNewsletterOutput(BaseModel):
    subject_line: str = ""
    preview_text: str = ""
    body_html: str = ""
    cta_text: str = ""
    cta_url_placeholder: str = ""


# ── Channel → Schema mapping ─────────────────────────────────────────────────

CHANNEL_OUTPUT_SCHEMAS: Dict[str, type] = {
    "ig_reel": IGReelOutput,
    "ig_post": IGPostOutput,
    "ig_carousel": IGCarouselOutput,
    "ig_story": IGStoryOutput,
    "tiktok_short": TikTokShortOutput,
    "yt_short": YTShortOutput,
    "yt_long": YTLongOutput,
    "fb_feed": FBFeedOutput,
    "fb_ad_copy": FBAdCopyOutput,
    "x_post": XPostOutput,
    "x_thread": XThreadOutput,
    "linkedin_post": LinkedInPostOutput,
    "email_newsletter": EmailNewsletterOutput,
}


def validate_channel_output(channel_key: str, output: dict) -> BaseModel:
    """Validate output dict against the channel's schema. Returns parsed model."""
    schema_cls = CHANNEL_OUTPUT_SCHEMAS.get(channel_key)
    if not schema_cls:
        raise ValueError(f"No schema for channel: {channel_key}")
    return schema_cls(**output)


# ── Score Breakdown ───────────────────────────────────────────────────────────

@dataclass
class VariantScoreBreakdown:
    hook_strength: float = 0.0      # 0-25
    clarity: float = 0.0            # 0-15
    cta_fit: float = 0.0            # 0-10
    channel_fit: float = 0.0        # 0-15
    brand_voice_match: float = 0.0  # 0-15
    goal_alignment: float = 0.0     # 0-10
    novelty: float = 0.0            # 0-10

    @property
    def total(self) -> float:
        return (
            self.hook_strength
            + self.clarity
            + self.cta_fit
            + self.channel_fit
            + self.brand_voice_match
            + self.goal_alignment
            + self.novelty
        )
