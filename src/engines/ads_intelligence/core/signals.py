"""Signal detectors — new ads, angle trends, format shifts."""
from __future__ import annotations

from datetime import datetime

from .models import AdCanonical, AdFormat, SignalEvent, SignalType


# ── New Ad Detector ──────────────────────────────────────────────────────────

class NewAdDetector:
    """Detects ads not seen before (by fingerprint)."""

    @staticmethod
    def detect(ads: list[AdCanonical], existing_fingerprints: set[str]) -> list[SignalEvent]:
        signals: list[SignalEvent] = []
        now = datetime.utcnow()
        for ad in ads:
            if ad.fingerprint not in existing_fingerprints:
                signals.append(SignalEvent(
                    type=SignalType.NEW_AD,
                    platform=ad.platform.value if hasattr(ad.platform, "value") else str(ad.platform),
                    entity=ad.advertiser,
                    previous_value=None,
                    new_value={
                        "headline": ad.headline,
                        "copy": ad.copy[:100],
                        "format": ad.format.value if hasattr(ad.format, "value") else str(ad.format),
                        "fingerprint": ad.fingerprint,
                    },
                    detected_at=now,
                    confidence_score=1.0,
                ))
        return signals


# ── Angle Trend Detector ─────────────────────────────────────────────────────

class AngleTrendDetector:
    """Detects growing repetition of hooks, claims, urgency keywords."""

    TRACKED_PATTERNS: dict[str, list[str]] = {
        "hooks": [
            "free", "limited time", "exclusive", "save", "discount",
            "gratis", "oferta", "descuento", "nuevo", "ahora",
            "don't miss", "last chance", "hurry", "today only",
        ],
        "claims": [
            "#1", "best", "guaranteed", "proven", "trusted",
            "award", "certified", "official", "premium",
        ],
        "urgency": [
            "now", "today", "limited", "hurry", "fast",
            "ending soon", "last chance", "final",
        ],
    }

    @classmethod
    def detect(
        cls,
        current_ads: list[AdCanonical],
        previous_ads: list[AdCanonical],
        min_frequency_increase: float = 0.2,
    ) -> list[SignalEvent]:
        signals: list[SignalEvent] = []
        now = datetime.utcnow()
        if not previous_ads:
            return signals

        current_total = max(len(current_ads), 1)
        previous_total = max(len(previous_ads), 1)

        for category, patterns in cls.TRACKED_PATTERNS.items():
            current_counts = cls._count_patterns(current_ads, patterns)
            previous_counts = cls._count_patterns(previous_ads, patterns)

            for pattern in patterns:
                curr_freq = current_counts.get(pattern, 0) / current_total
                prev_freq = previous_counts.get(pattern, 0) / previous_total

                if (
                    curr_freq - prev_freq >= min_frequency_increase
                    and current_counts.get(pattern, 0) >= 2
                ):
                    signals.append(SignalEvent(
                        type=SignalType.ANGLE_TREND,
                        platform="all",
                        entity=f"{category}:{pattern}",
                        previous_value=round(prev_freq, 3),
                        new_value=round(curr_freq, 3),
                        detected_at=now,
                        confidence_score=min(1.0, (curr_freq - prev_freq) / 0.5),
                    ))

        return signals

    @staticmethod
    def _count_patterns(ads: list[AdCanonical], patterns: list[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for ad in ads:
            text = f"{ad.headline} {ad.copy}".lower()
            for pattern in patterns:
                if pattern in text:
                    counts[pattern] = counts.get(pattern, 0) + 1
        return counts


# ── Creative Format Shift Detector ───────────────────────────────────────────

class CreativeFormatShiftDetector:
    """Detects shifts in dominant creative format (image→video, short→long copy, etc.)."""

    @classmethod
    def detect(
        cls,
        current_ads: list[AdCanonical],
        previous_ads: list[AdCanonical],
        min_shift: float = 0.15,
    ) -> list[SignalEvent]:
        signals: list[SignalEvent] = []
        now = datetime.utcnow()

        if not previous_ads or not current_ads:
            return signals

        # Format distribution shift
        curr_dist = cls._format_distribution(current_ads)
        prev_dist = cls._format_distribution(previous_ads)

        for fmt in set(curr_dist) | set(prev_dist):
            curr_pct = curr_dist.get(fmt, 0.0)
            prev_pct = prev_dist.get(fmt, 0.0)
            if abs(curr_pct - prev_pct) >= min_shift:
                signals.append(SignalEvent(
                    type=SignalType.FORMAT_SHIFT,
                    platform="all",
                    entity=f"format:{fmt}",
                    previous_value=round(prev_pct, 3),
                    new_value=round(curr_pct, 3),
                    detected_at=now,
                    confidence_score=min(1.0, abs(curr_pct - prev_pct) / 0.3),
                ))

        # Copy-length shift
        curr_avg = cls._avg_copy_length(current_ads)
        prev_avg = cls._avg_copy_length(previous_ads)
        if prev_avg > 0:
            change_ratio = abs(curr_avg - prev_avg) / max(prev_avg, 1)
            if change_ratio >= 0.3:
                direction = "longer" if curr_avg > prev_avg else "shorter"
                signals.append(SignalEvent(
                    type=SignalType.FORMAT_SHIFT,
                    platform="all",
                    entity=f"copy_length:{direction}",
                    previous_value=round(prev_avg),
                    new_value=round(curr_avg),
                    detected_at=now,
                    confidence_score=min(1.0, change_ratio / 0.5),
                ))

        return signals

    @staticmethod
    def _format_distribution(ads: list[AdCanonical]) -> dict[str, float]:
        if not ads:
            return {}
        counts: dict[str, int] = {}
        for ad in ads:
            fmt = ad.format.value if hasattr(ad.format, "value") else str(ad.format)
            counts[fmt] = counts.get(fmt, 0) + 1
        total = len(ads)
        return {k: v / total for k, v in counts.items()}

    @staticmethod
    def _avg_copy_length(ads: list[AdCanonical]) -> float:
        if not ads:
            return 0.0
        return sum(len(ad.copy) for ad in ads) / len(ads)
