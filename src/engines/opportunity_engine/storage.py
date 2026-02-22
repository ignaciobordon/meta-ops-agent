"""Storage layer — in-memory implementation with swappable Protocol interface."""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol

from .models import CanonicalItem, Opportunity, OpportunityRunReport


class OpportunityStore(Protocol):
    """Interface for opportunity persistence. Swap for DB later."""

    def store_opportunity(self, opp: Opportunity) -> None: ...
    def get_opportunity(self, opp_id: str) -> Optional[Opportunity]: ...
    def list_opportunities(
        self,
        opp_type: str | None = None,
        min_priority: float = 0.0,
        min_confidence: float = 0.0,
        limit: int = 50,
    ) -> list[Opportunity]: ...
    def get_existing_by_type(self, opp_type: str) -> list[Opportunity]: ...
    def store_report(self, report: OpportunityRunReport) -> None: ...


class InMemoryOpportunityStore:
    """In-memory mock store. Data lost on restart."""

    def __init__(self) -> None:
        self._opportunities: dict[str, Opportunity] = {}
        self._reports: list[OpportunityRunReport] = []
        self._items: list[CanonicalItem] = []
        self._last_run_at: Optional[datetime] = None

    # ── Opportunities ─────────────────────────────────────────────────────────

    def store_opportunity(self, opp: Opportunity) -> None:
        self._opportunities[opp.id] = opp

    def get_opportunity(self, opp_id: str) -> Optional[Opportunity]:
        return self._opportunities.get(opp_id)

    def list_opportunities(
        self,
        opp_type: str | None = None,
        min_priority: float = 0.0,
        min_confidence: float = 0.0,
        limit: int = 50,
    ) -> list[Opportunity]:
        result = list(self._opportunities.values())
        if opp_type:
            result = [
                o for o in result
                if (o.type.value if hasattr(o.type, "value") else str(o.type)) == opp_type
            ]
        if min_priority > 0:
            result = [o for o in result if o.priority_score >= min_priority]
        if min_confidence > 0:
            result = [o for o in result if o.confidence_score >= min_confidence]
        # Sort by priority descending
        result.sort(key=lambda o: o.priority_score, reverse=True)
        return result[:limit]

    def get_existing_by_type(self, opp_type: str) -> list[Opportunity]:
        return [
            o for o in self._opportunities.values()
            if (o.type.value if hasattr(o.type, "value") else str(o.type)) == opp_type
        ]

    # ── Reports ───────────────────────────────────────────────────────────────

    def store_report(self, report: OpportunityRunReport) -> None:
        self._reports.append(report)

    def get_reports(self) -> list[OpportunityRunReport]:
        return list(self._reports)

    # ── Canonical items ───────────────────────────────────────────────────────

    def store_items(self, items: list[CanonicalItem]) -> None:
        self._items.extend(items)

    def get_items(self) -> list[CanonicalItem]:
        return list(self._items)

    # ── Watermark ─────────────────────────────────────────────────────────────

    @property
    def last_run_at(self) -> Optional[datetime]:
        return self._last_run_at

    @last_run_at.setter
    def last_run_at(self, value: datetime) -> None:
        self._last_run_at = value

    # ── Counts ────────────────────────────────────────────────────────────────

    def opportunity_count(self) -> int:
        return len(self._opportunities)

    def item_count(self) -> int:
        return len(self._items)
