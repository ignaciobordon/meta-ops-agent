"""Detector: NewAdsSpikeDetector — fires when a competitor launches an unusual burst of ads."""
from __future__ import annotations

from datetime import datetime, timedelta

from src.engines.opportunity_engine.config import OpportunityConfig, DEFAULT_CONFIG
from src.engines.opportunity_engine.models import CanonicalItem, Opportunity, OpportunityType
from src.engines.opportunity_engine.scoring import compute_impact_score
from .base import BaseOpportunityDetector


class NewAdsSpikeDetector(BaseOpportunityDetector):
    name = "new_ads_spike"

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

        # Only ads
        current_ads = [it for it in current_items if it.item_type == "ad"]
        previous_ads = [it for it in previous_items if it.item_type == "ad"]

        # Recent window counts per competitor
        recent_cutoff = now - timedelta(days=cfg.recent_window_days)
        recent_by_comp: dict[str, list[CanonicalItem]] = {}
        for ad in current_ads:
            if ad.first_seen >= recent_cutoff:
                recent_by_comp.setdefault(ad.competitor, []).append(ad)

        # Baseline: average ads/day per competitor from previous data
        baseline_days = max(cfg.baseline_window_days, 1)
        baseline_counts: dict[str, int] = {}
        for ad in previous_ads:
            baseline_counts[ad.competitor] = baseline_counts.get(ad.competitor, 0) + 1

        for competitor, recent_ads in recent_by_comp.items():
            recent_count = len(recent_ads)
            if recent_count < cfg.min_ads_for_spike:
                continue

            # Expected count for this competitor in the recent window
            baseline_total = baseline_counts.get(competitor, 0)
            baseline_rate = baseline_total / baseline_days  # ads/day
            expected = baseline_rate * cfg.recent_window_days

            # Spike ratio
            if expected > 0:
                spike_ratio = recent_count / expected
            else:
                spike_ratio = float(recent_count)  # no baseline → any ads = spike

            if spike_ratio < cfg.spike_threshold:
                continue

            # Confidence based on spike magnitude
            confidence = min(1.0, spike_ratio / (cfg.spike_threshold * 3))

            # Impact
            impact = compute_impact_score(
                frequency=min(1.0, recent_count / 20),
                growth_velocity=min(1.0, (spike_ratio - 1) / 5),
                competitor_count=1,
                persistence=0.5,
            )

            evidence = [ad.id for ad in recent_ads]

            opportunities.append(Opportunity(
                type=OpportunityType.NEW_ADS_SPIKE,
                title=f"Ad spike detected: {competitor}",
                description=(
                    f"{competitor} launched {recent_count} ads in the last "
                    f"{cfg.recent_window_days} days — {spike_ratio:.1f}x above baseline."
                ),
                confidence_score=round(confidence, 4),
                impact_score=round(impact, 4),
                evidence_ids=evidence,
                detected_at=now,
                expires_at=now + timedelta(days=cfg.default_expiry_days),
                suggested_actions=[
                    f"Analyze {competitor}'s new ads for messaging angles",
                    "Consider launching counter-campaign",
                    "Review their landing pages for offer changes",
                ],
                rationale=(
                    f"Detected because {competitor} published {recent_count} new ads "
                    f"in the last {cfg.recent_window_days} days, which is {spike_ratio:.1f}x "
                    f"above their historical average of {baseline_rate:.1f} ads/day. "
                    f"This level of activity typically signals a new campaign launch, "
                    f"product release, or promotional push. Recommended action: analyze "
                    f"their ad creatives and messaging to identify angles worth countering."
                ),
            ))

        return opportunities
