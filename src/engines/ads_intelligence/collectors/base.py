"""Base collector interface — all platform collectors implement this."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..core.models import AdCanonical, CollectorTarget


class BaseAdsCollector(ABC):
    """Contract every platform collector must fulfil."""

    @abstractmethod
    async def discover_targets(
        self, query: str = "", country: str = "US",
    ) -> list[CollectorTarget]:
        """Find advertisers / ad sets to collect."""
        ...

    @abstractmethod
    async def collect(self, target: CollectorTarget) -> list[dict]:
        """Fetch raw ad data for a target. Returns list of raw dicts."""
        ...

    @abstractmethod
    def normalize(self, raw: dict) -> AdCanonical:
        """Convert raw platform dict → AdCanonical."""
        ...

    @abstractmethod
    def validate(self, ad: AdCanonical) -> bool:
        """Return True if ad passes validation."""
        ...

    @abstractmethod
    def persist(self, ad: AdCanonical) -> None:
        """Store a validated ad."""
        ...
