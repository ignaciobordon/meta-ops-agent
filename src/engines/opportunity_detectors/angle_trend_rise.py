"""Detector: AngleTrendRiseDetector — detects rising frequency of hooks, claims, keywords."""
from __future__ import annotations

from datetime import datetime, timedelta

from src.engines.opportunity_engine.baselines import extract_keywords
from src.engines.opportunity_engine.config import OpportunityConfig, DEFAULT_CONFIG
from src.engines.opportunity_engine.models import CanonicalItem, Opportunity, OpportunityType
from src.engines.opportunity_engine.scoring import compute_impact_score
from .base import BaseOpportunityDetector

# Tracked angle patterns (hooks, claims, urgency)
_ANGLE_PATTERNS: dict[str, list[str]] = {
    "hooks": [
        "free", "limited time", "exclusive", "save", "discount",
        "gratis", "oferta", "descuento", "nuevo", "ahora",
        "don't miss", "last chance", "hurry", "today only",
    ],
    "claims": [
        "#1", "best", "guaranteed", "proven", "trusted",
        "award", "certified", "official", "premium", "number one",
    ],
    "urgency": [
        "now", "today", "limited", "hurry", "fast",
        "ending soon", "last chance", "final", "expires",
    ],
    "social_proof": [
        "million", "thousands", "rated", "reviews", "stars",
        "recommended", "top rated", "bestseller", "most popular",
    ],
}


class AngleTrendRiseDetector(BaseOpportunityDetector):
    name = "angle_trend_rise"

    def run(
        self,
        current_items: list[CanonicalItem],
        previous_items: list[CanonicalItem] | None = None,
        config: OpportunityConfig | None = None,
    ) -> list[Opportunity]:
        cfg = config or DEFAULT_CONFIG
        previous_items = previous_items or []
        now = datetime.utcnow()
        opportunities: list[Opportunity] = []

        if not previous_items:
            return opportunities

        current_total = max(len(current_items), 1)
        previous_total = max(len(previous_items), 1)

        for category, patterns in _ANGLE_PATTERNS.items():
            curr_counts = self._count_patterns(current_items, patterns)
            prev_counts = self._count_patterns(previous_items, patterns)

            for pattern in patterns:
                curr_freq = curr_counts.get(pattern, 0) / current_total
                prev_freq = prev_counts.get(pattern, 0) / previous_total
                increase = curr_freq - prev_freq

                if increase < cfg.trend_min_frequency_increase:
                    continue
                if curr_counts.get(pattern, 0) < cfg.trend_min_occurrences:
                    continue

                # Confidence scales with the increase magnitude
                confidence = min(1.0, increase / 0.5)

                # Impact: how widespread is this trend
                matching_items = [
                    it for it in current_items
                    if pattern in f"{it.headline} {it.body}".lower()
                ]
                competitors = len(set(it.competitor for it in matching_items))

                impact = compute_impact_score(
                    frequency=min(1.0, curr_freq),
                    growth_velocity=min(1.0, increase / 0.3),
                    competitor_count=competitors,
                    persistence=0.5,
                )

                evidence = [it.id for it in matching_items[:10]]

                opportunities.append(Opportunity(
                    type=OpportunityType.ANGLE_TREND_RISE,
                    title=f"Rising angle: '{pattern}' ({category})",
                    description=(
                        f"The angle '{pattern}' ({category}) increased from "
                        f"{prev_freq:.0%} to {curr_freq:.0%} of ads. "
                        f"Observed across {competitors} competitor(s)."
                    ),
                    confidence_score=round(confidence, 4),
                    impact_score=round(impact, 4),
                    evidence_ids=evidence,
                    detected_at=now,
                    expires_at=now + timedelta(days=cfg.default_expiry_days),
                    suggested_actions=[
                        f"Test '{pattern}' angle in your own ads",
                        f"Create variations using '{category}' framing",
                        "A/B test this angle against current top performer",
                    ],
                    rationale=(
                        f"The pattern '{pattern}' (category: {category}) was found in "
                        f"{curr_counts.get(pattern, 0)}/{current_total} current items "
                        f"({curr_freq:.0%}) vs {prev_counts.get(pattern, 0)}/{previous_total} "
                        f"previous items ({prev_freq:.0%}). This {increase:.0%} increase "
                        f"across {competitors} competitor(s) suggests this messaging angle "
                        f"is gaining traction in the market. Consider testing similar "
                        f"messaging in your campaigns."
                    ),
                ))

        return opportunities

    @staticmethod
    def _count_patterns(
        items: list[CanonicalItem], patterns: list[str],
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for it in items:
            text = f"{it.headline} {it.body}".lower()
            for p in patterns:
                if p in text:
                    counts[p] = counts.get(p, 0) + 1
        return counts
