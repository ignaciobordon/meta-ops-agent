"""Detector: CompetitorOfferChangeDetector — detects price/discount/CTA/guarantee changes."""
from __future__ import annotations

from datetime import datetime, timedelta

from src.engines.opportunity_engine.config import OpportunityConfig, DEFAULT_CONFIG
from src.engines.opportunity_engine.models import CanonicalItem, Opportunity, OpportunityType
from src.engines.opportunity_engine.scoring import compute_impact_score
from .base import BaseOpportunityDetector


class CompetitorOfferChangeDetector(BaseOpportunityDetector):
    name = "competitor_offer_change"

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

        # Build latest offer snapshot per competitor (current)
        current_offers = self._latest_offers(current_items)
        previous_offers = self._latest_offers(previous_items)

        for competitor in set(current_offers) & set(previous_offers):
            curr = current_offers[competitor]
            prev = previous_offers[competitor]
            changes: list[str] = []
            evidence_ids: list[str] = []

            # Price change
            if curr.price is not None and prev.price is not None:
                if prev.price > 0:
                    pct_change = abs(curr.price - prev.price) / prev.price
                    if pct_change >= cfg.offer_price_change_pct:
                        direction = "decreased" if curr.price < prev.price else "increased"
                        changes.append(
                            f"Price {direction}: ${prev.price:.2f} → ${curr.price:.2f} "
                            f"({pct_change:.0%} change)"
                        )

            # Discount change
            if curr.discount != prev.discount:
                if curr.discount or prev.discount:
                    changes.append(f"Discount changed: '{prev.discount}' → '{curr.discount}'")

            # CTA change
            if curr.cta != prev.cta:
                if curr.cta or prev.cta:
                    changes.append(f"CTA changed: '{prev.cta}' → '{curr.cta}'")

            # Guarantee change
            if curr.guarantee != prev.guarantee:
                if curr.guarantee or prev.guarantee:
                    changes.append(f"Guarantee changed: '{prev.guarantee}' → '{curr.guarantee}'")

            if not changes:
                continue

            evidence_ids = [curr.id, prev.id]

            confidence = min(1.0, len(changes) * 0.35)
            impact = compute_impact_score(
                frequency=min(1.0, len(changes) / 4),
                growth_velocity=0.6,
                competitor_count=1,
                persistence=0.5,
            )

            opportunities.append(Opportunity(
                type=OpportunityType.COMPETITOR_OFFER_CHANGE,
                title=f"Offer change detected: {competitor}",
                description=(
                    f"{competitor} changed their offer: "
                    + "; ".join(changes)
                ),
                confidence_score=round(confidence, 4),
                impact_score=round(impact, 4),
                evidence_ids=evidence_ids,
                detected_at=now,
                expires_at=now + timedelta(days=cfg.default_expiry_days),
                suggested_actions=[
                    f"Review {competitor}'s updated offer positioning",
                    "Evaluate if your pricing remains competitive",
                    "Consider matching or countering with your own promotion",
                ],
                rationale=(
                    f"Detected {len(changes)} change(s) in {competitor}'s offer: "
                    + "; ".join(changes) + ". "
                    f"Offer changes from competitors often signal strategic shifts — "
                    f"new promotions, pricing experiments, or seasonal pushes. "
                    f"Review their current positioning and adjust your strategy."
                ),
            ))

        return opportunities

    @staticmethod
    def _latest_offers(items: list[CanonicalItem]) -> dict[str, CanonicalItem]:
        """Get the most recent item per competitor (as an offer proxy)."""
        latest: dict[str, CanonicalItem] = {}
        for it in items:
            if it.competitor not in latest or it.last_seen > latest[it.competitor].last_seen:
                latest[it.competitor] = it
        return latest
