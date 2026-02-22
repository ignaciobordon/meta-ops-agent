"""
CI Module — Schema Normalizer.

Transforms raw source data into canonical NormalizedAd/LandingPage/Post/Offer schemas.
Each normalize_* function accepts a raw dict and returns a Pydantic model.
"""
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from backend.src.ci.schemas import (
    NormalizedAd,
    NormalizedLandingPage,
    NormalizedOffer,
    NormalizedPost,
)


def normalize_ad(raw: Dict[str, Any], competitor_id: UUID) -> NormalizedAd:
    """Normalize a raw ad payload into a NormalizedAd.

    Handles Meta Ad Library format and generic format.
    """
    # Meta Ad Library format
    if "ad_archive_id" in raw or "page_id" in raw:
        return _normalize_meta_ad(raw, competitor_id)

    # Generic format
    return NormalizedAd(
        external_id=str(raw.get("id", raw.get("external_id", ""))),
        competitor_id=competitor_id,
        platform=raw.get("platform", "unknown"),
        headline=raw.get("headline"),
        body_text=raw.get("body_text", raw.get("body", raw.get("text"))),
        cta_text=raw.get("cta_text", raw.get("cta")),
        image_urls=_extract_list(raw, "image_urls", "images"),
        video_url=raw.get("video_url"),
        landing_page_url=raw.get("landing_page_url", raw.get("link", raw.get("url"))),
        ad_format=raw.get("ad_format", raw.get("format")),
        estimated_spend=_safe_float(raw.get("estimated_spend", raw.get("spend"))),
        started_at=_safe_datetime(raw.get("started_at", raw.get("start_date"))),
        ended_at=_safe_datetime(raw.get("ended_at", raw.get("end_date"))),
        is_active=raw.get("is_active", True),
        raw_data=raw,
    )


def _normalize_meta_ad(raw: Dict[str, Any], competitor_id: UUID) -> NormalizedAd:
    """Normalize Meta Ad Library specific format."""
    ad_creative = raw.get("ad_creative_bodies", [])
    body_text = ad_creative[0] if ad_creative else raw.get("body_text")

    link_titles = raw.get("ad_creative_link_titles", [])
    headline = link_titles[0] if link_titles else raw.get("headline")

    link_descriptions = raw.get("ad_creative_link_descriptions", [])
    cta_text = link_descriptions[0] if link_descriptions else None

    return NormalizedAd(
        external_id=str(raw.get("ad_archive_id", raw.get("id", ""))),
        competitor_id=competitor_id,
        platform="meta",
        headline=headline,
        body_text=body_text,
        cta_text=cta_text,
        image_urls=_extract_list(raw, "image_urls", "images"),
        video_url=raw.get("video_url"),
        landing_page_url=raw.get("ad_creative_link_captions", [None])[0]
        if raw.get("ad_creative_link_captions")
        else raw.get("landing_page_url"),
        ad_format=raw.get("ad_format", "image"),
        estimated_spend=_safe_float(raw.get("spend_lower_bound")),
        started_at=_safe_datetime(raw.get("ad_delivery_start_time")),
        ended_at=_safe_datetime(raw.get("ad_delivery_stop_time")),
        is_active=raw.get("is_active", raw.get("ad_delivery_stop_time") is None),
        raw_data=raw,
    )


def normalize_landing_page(raw: Dict[str, Any], competitor_id: UUID) -> NormalizedLandingPage:
    """Normalize a raw landing page payload."""
    return NormalizedLandingPage(
        external_id=str(raw.get("id", raw.get("external_id", raw.get("url", "")))),
        competitor_id=competitor_id,
        url=raw.get("url", ""),
        title=raw.get("title"),
        meta_description=raw.get("meta_description"),
        h1_text=raw.get("h1_text", raw.get("h1")),
        body_text=raw.get("body_text", raw.get("text")),
        cta_texts=_extract_list(raw, "cta_texts", "ctas"),
        form_fields=_extract_list(raw, "form_fields", "fields"),
        tech_stack=_extract_list(raw, "tech_stack", "technologies"),
        screenshot_url=raw.get("screenshot_url"),
        raw_data=raw,
    )


def normalize_post(raw: Dict[str, Any], competitor_id: UUID) -> NormalizedPost:
    """Normalize a raw social post payload."""
    return NormalizedPost(
        external_id=str(raw.get("id", raw.get("external_id", ""))),
        competitor_id=competitor_id,
        platform=raw.get("platform", "unknown"),
        post_type=raw.get("post_type", raw.get("type")),
        caption=raw.get("caption", raw.get("text", raw.get("body"))),
        image_urls=_extract_list(raw, "image_urls", "images"),
        video_url=raw.get("video_url"),
        hashtags=_extract_list(raw, "hashtags", "tags"),
        likes=_safe_int(raw.get("likes", raw.get("like_count"))),
        comments=_safe_int(raw.get("comments", raw.get("comment_count"))),
        shares=_safe_int(raw.get("shares", raw.get("share_count"))),
        engagement_rate=_safe_float(raw.get("engagement_rate")),
        posted_at=_safe_datetime(raw.get("posted_at", raw.get("created_at", raw.get("timestamp")))),
        raw_data=raw,
    )


def normalize_offer(raw: Dict[str, Any], competitor_id: UUID) -> NormalizedOffer:
    """Normalize a raw offer/promo payload."""
    return NormalizedOffer(
        external_id=str(raw.get("id", raw.get("external_id", ""))),
        competitor_id=competitor_id,
        offer_type=raw.get("offer_type", raw.get("type")),
        headline=raw.get("headline", raw.get("title")),
        description=raw.get("description", raw.get("body")),
        discount_value=raw.get("discount_value", raw.get("discount")),
        url=raw.get("url", raw.get("link")),
        valid_from=_safe_datetime(raw.get("valid_from", raw.get("start_date"))),
        valid_until=_safe_datetime(raw.get("valid_until", raw.get("end_date"))),
        raw_data=raw,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_list(raw: Dict, primary_key: str, fallback_key: str) -> list:
    """Extract a list from raw dict, trying primary key then fallback."""
    val = raw.get(primary_key) or raw.get(fallback_key) or []
    if isinstance(val, list):
        return val
    return [val] if val else []


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _safe_datetime(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%f"):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
    return None
