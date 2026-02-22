"""
Sprint 5 – BLOQUE A: NullProvider
Default fallback — returns unavailable metrics. Ensures the system never crashes
when no metrics source is configured.
"""
from uuid import UUID

from backend.src.providers.metrics_provider import MetricsProvider, MetricsSnapshot


class NullProvider(MetricsProvider):
    """Fallback provider that always returns unavailable metrics."""

    @property
    def provider_name(self) -> str:
        return "null"

    def get_snapshot(
        self,
        org_id: UUID,
        entity_type: str,
        entity_id: str,
        window_minutes: int = 1440,
    ) -> MetricsSnapshot:
        return MetricsSnapshot(
            entity_type=entity_type,
            entity_id=entity_id,
            provider="null",
            metrics={},
            available=False,
        )
