"""Base interface for all opportunity detectors."""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.engines.opportunity_engine.config import OpportunityConfig
from src.engines.opportunity_engine.models import CanonicalItem, Opportunity


class BaseOpportunityDetector(ABC):
    """Every detector implements this contract."""

    name: str = "base"

    @abstractmethod
    def run(
        self,
        current_items: list[CanonicalItem],
        previous_items: list[CanonicalItem] | None = None,
        config: OpportunityConfig | None = None,
    ) -> list[Opportunity]:
        """
        Analyze items and return detected opportunities.

        Args:
            current_items:  data from the latest collection run
            previous_items: data from a prior run (for comparison)
            config:         engine config overrides

        Returns:
            List of Opportunity objects
        """
        ...
