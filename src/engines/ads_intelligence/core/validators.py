"""Validation layer — reject corrupt or incomplete ads."""
from __future__ import annotations

import re

from .models import AdCanonical

_URL_RE = re.compile(r"^https?://.+\..+")

_VALID_PLATFORMS = {"meta", "google", "tiktok"}


class AdValidator:
    """Validate AdCanonical objects before persistence."""

    MAX_HEADLINE_LENGTH = 500
    MAX_COPY_LENGTH = 5000

    @classmethod
    def validate(cls, ad: AdCanonical) -> tuple[bool, list[str]]:
        """Return (is_valid, error_list)."""
        errors: list[str] = []

        # Platform
        platform_val = ad.platform.value if hasattr(ad.platform, "value") else str(ad.platform)
        if platform_val not in _VALID_PLATFORMS:
            errors.append(f"Invalid platform: {platform_val}")

        # Advertiser required
        if not ad.advertiser or not ad.advertiser.strip():
            errors.append("Advertiser is required")

        # Headline length
        if len(ad.headline) > cls.MAX_HEADLINE_LENGTH:
            errors.append(f"Headline too long: {len(ad.headline)} > {cls.MAX_HEADLINE_LENGTH}")

        # Copy length
        if len(ad.copy) > cls.MAX_COPY_LENGTH:
            errors.append(f"Copy too long: {len(ad.copy)} > {cls.MAX_COPY_LENGTH}")

        # Landing URL format
        if ad.landing_url and not _URL_RE.match(ad.landing_url):
            errors.append(f"Invalid landing URL: {ad.landing_url}")

        # Media URL format
        if ad.media_url and not _URL_RE.match(ad.media_url):
            errors.append(f"Invalid media URL: {ad.media_url}")

        # Must have at least headline or copy
        if not ad.headline.strip() and not ad.copy.strip():
            errors.append("Ad must have at least headline or copy")

        # Fingerprint
        if not ad.fingerprint:
            errors.append("Fingerprint is required")

        return len(errors) == 0, errors

    @classmethod
    def is_valid(cls, ad: AdCanonical) -> bool:
        valid, _ = cls.validate(ad)
        return valid
