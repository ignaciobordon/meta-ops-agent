"""Normalizer — map platform-specific fields → AdCanonical, clean, dedup, fingerprint."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

from .models import AdCanonical, AdFormat, AdPlatform

# ── Text utilities ───────────────────────────────────────────────────────────

_WHITESPACE_RE = re.compile(r"\s+")
_URL_TRACKING_RE = re.compile(r"[?&](utm_\w+|fbclid|gclid|gclsrc|ref|source|_ga|_gl)=[^&]*")

_CTA_PATTERNS = [
    "shop now", "buy now", "learn more", "sign up", "get started",
    "download", "install now", "book now", "subscribe", "try free",
    "get offer", "apply now", "contact us", "watch more", "see more",
    "order now", "claim offer", "start free trial", "join now",
    "comprar ahora", "ver más", "registrarse", "descargar",
    "más información", "obtener oferta", "suscribirse",
]

# Simple language detection word lists
_LANG_WORDS = {
    "en": {"the", "and", "is", "in", "to", "of", "for", "with", "on", "at", "this", "that", "you", "your"},
    "es": {"de", "el", "la", "en", "los", "las", "un", "una", "por", "para", "con", "que", "del", "tu", "su"},
    "pt": {"de", "o", "a", "em", "os", "as", "um", "uma", "por", "para", "com", "que", "do", "seu", "sua"},
}


def clean_text(text: str) -> str:
    """Strip and collapse whitespace."""
    if not text:
        return ""
    return _WHITESPACE_RE.sub(" ", text.strip())


def clean_url(url: str) -> str:
    """Strip tracking params from URLs."""
    if not url:
        return ""
    url = url.strip()
    url = _URL_TRACKING_RE.sub("", url)
    return url.rstrip("?&")


def detect_language(text: str) -> str:
    """Heuristic language detection based on common words."""
    if not text:
        return "unknown"
    words = set(text.lower().split())
    scores = {lang: len(words & ws) for lang, ws in _LANG_WORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


def detect_cta(text: str) -> str:
    """Extract first matching CTA phrase from text."""
    if not text:
        return ""
    lower = text.lower()
    for cta in _CTA_PATTERNS:
        if cta in lower:
            return cta
    return ""


def detect_format_from_media(media_url: str, metadata: dict | None = None) -> AdFormat:
    """Infer ad format from media URL or metadata."""
    if not media_url:
        return AdFormat.TEXT
    lower = media_url.lower()
    if any(ext in lower for ext in (".mp4", ".mov", ".avi", ".webm", "/video")):
        return AdFormat.VIDEO
    if any(ext in lower for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")):
        return AdFormat.IMAGE
    if metadata and metadata.get("format") == "carousel":
        return AdFormat.CAROUSEL
    return AdFormat.UNKNOWN


def generate_fingerprint(ad: AdCanonical) -> str:
    """Stable fingerprint for dedup: hash of platform + advertiser + headline + copy prefix."""
    parts = [
        ad.platform.value if isinstance(ad.platform, AdPlatform) else str(ad.platform),
        ad.advertiser.lower().strip(),
        clean_text(ad.headline).lower(),
        clean_text(ad.copy).lower()[:200],
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ── Platform normalizers ─────────────────────────────────────────────────────

class AdsNormalizer:
    """Normalize raw platform data → AdCanonical."""

    @classmethod
    def normalize_meta(cls, raw: dict) -> AdCanonical:
        ad = AdCanonical(
            platform=AdPlatform.META,
            advertiser=raw.get("page_name", raw.get("advertiser_name", "")),
            headline=clean_text(raw.get("ad_creative_link_title", "")),
            copy=clean_text(raw.get("ad_creative_body", raw.get("body", ""))),
            cta=raw.get("ad_creative_link_caption", ""),
            landing_url=clean_url(raw.get("ad_creative_link_url", raw.get("link_url", ""))),
            media_url=raw.get("ad_creative_image_url", raw.get("image_url", "")),
            country=raw.get("country", ""),
            platform_position=raw.get("publisher_platform", "feed"),
            metadata=raw,
        )
        if not ad.cta:
            ad.cta = detect_cta(ad.copy) or detect_cta(ad.headline)
        ad.format = detect_format_from_media(ad.media_url, raw)
        ad.fingerprint = generate_fingerprint(ad)
        # Parse dates
        for field_name, attr in [("ad_delivery_start_time", "first_seen"), ("ad_delivery_stop_time", "last_seen")]:
            val = raw.get(field_name)
            if val:
                try:
                    setattr(ad, attr, datetime.fromisoformat(str(val).replace("Z", "+00:00")))
                except (ValueError, AttributeError):
                    pass
        ad.metadata["language"] = detect_language(f"{ad.headline} {ad.copy}")
        return ad

    @classmethod
    def normalize_google(cls, raw: dict) -> AdCanonical:
        ad = AdCanonical(
            platform=AdPlatform.GOOGLE,
            advertiser=raw.get("advertiser_name", raw.get("advertiser", "")),
            headline=clean_text(raw.get("headline", raw.get("title", ""))),
            copy=clean_text(raw.get("description", raw.get("body_text", ""))),
            cta=raw.get("cta", ""),
            landing_url=clean_url(raw.get("destination_url", raw.get("landing_page", ""))),
            media_url=raw.get("image_url", raw.get("creative_url", "")),
            country=raw.get("country", raw.get("region", "")),
            platform_position=raw.get("ad_type", "search"),
            metadata=raw,
        )
        if not ad.cta:
            ad.cta = detect_cta(ad.copy) or detect_cta(ad.headline)
        ad.format = detect_format_from_media(ad.media_url, raw)
        ad.fingerprint = generate_fingerprint(ad)
        ad.metadata["language"] = detect_language(f"{ad.headline} {ad.copy}")
        return ad

    @classmethod
    def normalize_tiktok(cls, raw: dict) -> AdCanonical:
        ad = AdCanonical(
            platform=AdPlatform.TIKTOK,
            advertiser=raw.get("brand_name", raw.get("advertiser_name", "")),
            headline=clean_text(raw.get("title", raw.get("ad_title", ""))),
            copy=clean_text(raw.get("caption", raw.get("ad_text", ""))),
            cta=raw.get("cta", raw.get("call_to_action", "")),
            landing_url=clean_url(raw.get("landing_page_url", "")),
            media_url=raw.get("video_url", raw.get("cover_url", "")),
            country=raw.get("country_code", raw.get("country", "")),
            platform_position="feed",
            metadata=raw,
        )
        if not ad.cta:
            ad.cta = detect_cta(ad.copy) or detect_cta(ad.headline)
        ad.format = detect_format_from_media(ad.media_url, raw)
        if ad.media_url and ".mp4" in ad.media_url.lower():
            ad.format = AdFormat.VIDEO
        ad.fingerprint = generate_fingerprint(ad)
        ad.metadata["language"] = detect_language(f"{ad.headline} {ad.copy}")
        return ad

    @classmethod
    def normalize(cls, platform: str, raw: dict) -> AdCanonical:
        """Route to the correct platform normalizer."""
        dispatch = {
            "meta": cls.normalize_meta,
            "google": cls.normalize_google,
            "tiktok": cls.normalize_tiktok,
        }
        fn = dispatch.get(platform)
        if not fn:
            raise ValueError(f"Unknown platform: {platform}")
        return fn(raw)

    @classmethod
    def deduplicate(
        cls,
        ads: list[AdCanonical],
        existing_fingerprints: set[str] | None = None,
    ) -> list[AdCanonical]:
        """Remove duplicate ads by fingerprint."""
        existing = existing_fingerprints or set()
        seen: set[str] = set()
        unique: list[AdCanonical] = []
        for ad in ads:
            fp = ad.fingerprint or generate_fingerprint(ad)
            if fp not in seen and fp not in existing:
                seen.add(fp)
                unique.append(ad)
        return unique
