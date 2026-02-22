"""Detector: FormatDominanceShiftDetector — fires on dominant creative format changes."""
from __future__ import annotations

from datetime import datetime, timedelta

from src.engines.opportunity_engine.config import OpportunityConfig, DEFAULT_CONFIG
from src.engines.opportunity_engine.models import CanonicalItem, Opportunity, OpportunityType
from src.engines.opportunity_engine.scoring import compute_impact_score
from .base import BaseOpportunityDetector


class FormatDominanceShiftDetector(BaseOpportunityDetector):
    name = "format_dominance_shift"

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

        if not previous_items or not current_items:
            return opportunities

        # Only ads
        current_ads = [it for it in current_items if it.item_type == "ad"]
        previous_ads = [it for it in previous_items if it.item_type == "ad"]

        if not current_ads or not previous_ads:
            return opportunities

        curr_dist = self._format_distribution(current_ads)
        prev_dist = self._format_distribution(previous_ads)

        for fmt in set(curr_dist) | set(prev_dist):
            curr_pct = curr_dist.get(fmt, 0.0)
            prev_pct = prev_dist.get(fmt, 0.0)
            delta = curr_pct - prev_pct

            if abs(delta) < cfg.format_shift_min_delta:
                continue

            direction = "rising" if delta > 0 else "declining"

            # Evidence: ads with this format
            evidence = [
                ad.id for ad in current_ads
                if (ad.format or "unknown") == fmt
            ][:10]

            # Competitors using this format
            competitors = set(
                ad.competitor for ad in current_ads
                if (ad.format or "unknown") == fmt
            )

            confidence = min(1.0, abs(delta) / 0.4)
            impact = compute_impact_score(
                frequency=curr_pct,
                growth_velocity=min(1.0, abs(delta) / 0.3),
                competitor_count=len(competitors),
                persistence=0.5,
            )

            opportunities.append(Opportunity(
                type=OpportunityType.FORMAT_DOMINANCE_SHIFT,
                title=f"Format shift: '{fmt}' is {direction} ({delta:+.0%})",
                description=(
                    f"The '{fmt}' format went from {prev_pct:.0%} to {curr_pct:.0%} "
                    f"of all ads ({direction}). Observed across {len(competitors)} competitor(s)."
                ),
                confidence_score=round(confidence, 4),
                impact_score=round(impact, 4),
                evidence_ids=evidence,
                detected_at=now,
                expires_at=now + timedelta(days=cfg.default_expiry_days),
                suggested_actions=[
                    f"Consider {'increasing' if delta > 0 else 'reviewing'} your '{fmt}' creative output",
                    "Test format mix aligned with market trend",
                    f"Analyze top-performing '{fmt}' creatives from competitors",
                ],
                rationale=(
                    f"The market share of '{fmt}' format creatives shifted from "
                    f"{prev_pct:.0%} to {curr_pct:.0%} (Δ {delta:+.0%}). "
                    f"This shift is observed across {len(competitors)} competitor(s): "
                    f"{', '.join(list(competitors)[:5])}. "
                    f"Format dominance shifts often indicate platform algorithm changes, "
                    f"audience preference evolution, or successful A/B test results "
                    f"being scaled across the market."
                ),
            ))

        return opportunities

    @staticmethod
    def _format_distribution(ads: list[CanonicalItem]) -> dict[str, float]:
        if not ads:
            return {}
        counts: dict[str, int] = {}
        for ad in ads:
            fmt = ad.format or "unknown"
            counts[fmt] = counts.get(fmt, 0) + 1
        total = len(ads)
        return {k: v / total for k, v in counts.items()}
