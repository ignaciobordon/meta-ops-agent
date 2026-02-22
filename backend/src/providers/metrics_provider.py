"""
Sprint 5 – BLOQUE A: MetricsProvider Abstraction
Base interface and schema for metrics snapshots used by the outcome system.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict
from uuid import UUID

from pydantic import BaseModel, Field


class MetricsSnapshot(BaseModel):
    """Point-in-time metrics for an entity."""
    entity_type: str
    entity_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    provider: str  # "meta" | "csv" | "null"
    metrics: Dict[str, Any]  # {spend, impressions, ctr, cpm, cpa, roas, frequency, ...}
    available: bool = True  # False when provider has no data


class MetricsProvider(ABC):
    """Interface for retrieving metrics snapshots."""

    @abstractmethod
    def get_snapshot(
        self,
        org_id: UUID,
        entity_type: str,
        entity_id: str,
        window_minutes: int = 1440,
    ) -> MetricsSnapshot:
        """Get a metrics snapshot for an entity over a time window."""
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass
