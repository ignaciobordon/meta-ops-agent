"""Core orchestrator — load items → baselines → detect → score → dedup → persist."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from .config import OpportunityConfig, DEFAULT_CONFIG
from .dedup import deduplicate_opportunities
from .models import CanonicalItem, Opportunity, OpportunityRunReport
from .scoring import compute_novelty_score, compute_priority_score, score_opportunity
from .storage import InMemoryOpportunityStore

from src.engines.opportunity_detectors.new_ads_spike import NewAdsSpikeDetector
from src.engines.opportunity_detectors.angle_trend_rise import AngleTrendRiseDetector
from src.engines.opportunity_detectors.competitor_offer_change import CompetitorOfferChangeDetector
from src.engines.opportunity_detectors.format_dominance_shift import FormatDominanceShiftDetector
from src.engines.opportunity_detectors.keyword_emergence import KeywordEmergenceDetector
from src.engines.opportunity_detectors.base import BaseOpportunityDetector

logger = logging.getLogger(__name__)


class OpportunityEngine:
    """
    Main entry point for the Opportunity Detection Engine.

    Pipeline:
        load canonical items
        → group by competitor
        → compute baselines
        → run detectors
        → score opportunities
        → dedupe
        → persist
    """

    def __init__(
        self,
        config: OpportunityConfig | None = None,
        storage: Any = None,
    ):
        self.config = config or DEFAULT_CONFIG
        self.storage = storage or InMemoryOpportunityStore()
        self._detectors: dict[str, BaseOpportunityDetector] = {
            "new_ads_spike": NewAdsSpikeDetector(),
            "angle_trend_rise": AngleTrendRiseDetector(),
            "competitor_offer_change": CompetitorOfferChangeDetector(),
            "format_dominance_shift": FormatDominanceShiftDetector(),
            "keyword_emergence": KeywordEmergenceDetector(),
        }

    # ── Execution ─────────────────────────────────────────────────────────────

    def run_all(
        self,
        current_items: list[CanonicalItem],
        previous_items: list[CanonicalItem] | None = None,
    ) -> OpportunityRunReport:
        """Run all detectors on the provided data."""
        report = OpportunityRunReport(started_at=datetime.utcnow())
        t0 = time.monotonic()

        all_opportunities: list[Opportunity] = []

        for name, detector in self._detectors.items():
            try:
                opps = detector.run(current_items, previous_items, self.config)
                all_opportunities.extend(opps)
                report.detectors_executed += 1
            except Exception as e:
                logger.error("DETECTOR_ERROR | name=%s | error=%s", name, str(e)[:300])
                report.errors += 1

        # Score all opportunities
        all_opportunities = self._score_all(all_opportunities)

        # Dedup
        before_dedup = len(all_opportunities)
        all_opportunities = deduplicate_opportunities(all_opportunities, self.config)
        report.opportunities_deduped = before_dedup - len(all_opportunities)

        # Persist
        for opp in all_opportunities:
            self.storage.store_opportunity(opp)

        report.opportunities_found = len(all_opportunities)
        report.opportunities_new = len(all_opportunities)
        report.duration = round(time.monotonic() - t0, 4)
        report.finished_at = datetime.utcnow()

        # Update watermark
        self.storage.last_run_at = datetime.utcnow()
        self.storage.store_report(report)

        logger.info(
            "RUN_COMPLETE | detectors=%d | found=%d | deduped=%d | errors=%d | duration=%.3fs",
            report.detectors_executed, report.opportunities_found,
            report.opportunities_deduped, report.errors, report.duration,
        )
        return report

    def run_detector(
        self,
        detector_name: str,
        current_items: list[CanonicalItem],
        previous_items: list[CanonicalItem] | None = None,
    ) -> OpportunityRunReport:
        """Run a single detector by name."""
        report = OpportunityRunReport(started_at=datetime.utcnow())
        t0 = time.monotonic()

        detector = self._detectors.get(detector_name)
        if not detector:
            logger.error("UNKNOWN_DETECTOR | name=%s", detector_name)
            report.errors = 1
            report.duration = round(time.monotonic() - t0, 4)
            report.finished_at = datetime.utcnow()
            return report

        try:
            opps = detector.run(current_items, previous_items, self.config)
            opps = self._score_all(opps)
            opps = deduplicate_opportunities(opps, self.config)
            report.detectors_executed = 1
            report.opportunities_found = len(opps)
            report.opportunities_new = len(opps)

            for opp in opps:
                self.storage.store_opportunity(opp)

        except Exception as e:
            logger.error("DETECTOR_ERROR | name=%s | error=%s", detector_name, str(e)[:300])
            report.errors = 1

        report.duration = round(time.monotonic() - t0, 4)
        report.finished_at = datetime.utcnow()
        self.storage.store_report(report)
        return report

    def run_since(
        self,
        since: datetime,
        current_items: list[CanonicalItem],
        previous_items: list[CanonicalItem] | None = None,
    ) -> OpportunityRunReport:
        """Incremental run — only process items newer than `since`."""
        filtered_current = [it for it in current_items if it.first_seen >= since]
        filtered_previous = previous_items  # Keep full previous for baseline
        return self.run_all(filtered_current, filtered_previous)

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_opportunities(
        self,
        opp_type: str | None = None,
        min_priority: float = 0.0,
        min_confidence: float = 0.0,
        limit: int = 50,
    ) -> list[Opportunity]:
        return self.storage.list_opportunities(
            opp_type=opp_type,
            min_priority=min_priority,
            min_confidence=min_confidence,
            limit=limit,
        )

    def get_opportunity(self, opp_id: str) -> Opportunity | None:
        return self.storage.get_opportunity(opp_id)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _score_all(self, opportunities: list[Opportunity]) -> list[Opportunity]:
        """Compute priority scores for all opportunities."""
        # Count existing similar opportunities for novelty decay
        for opp in opportunities:
            opp_type_val = opp.type.value if hasattr(opp.type, "value") else str(opp.type)
            existing = self.storage.get_existing_by_type(opp_type_val)
            similar_count = len(existing)
            score_opportunity(opp, similar_count, self.config)
        return opportunities
