"""
Sprint 5 – BLOQUE A: CsvMetricsProvider
Uses existing Creative performance data from the database as a metrics source.
"""
from uuid import UUID

from sqlalchemy.orm import Session

from backend.src.database.models import Creative
from backend.src.providers.metrics_provider import MetricsProvider, MetricsSnapshot


class CsvMetricsProvider(MetricsProvider):
    """Provides metrics from Creative table performance fields (CSV-sourced data)."""

    def __init__(self, db: Session):
        self.db = db

    @property
    def provider_name(self) -> str:
        return "csv"

    def get_snapshot(
        self,
        org_id: UUID,
        entity_type: str,
        entity_id: str,
        window_minutes: int = 1440,
    ) -> MetricsSnapshot:
        # Look up creative by meta_ad_id
        creative = self.db.query(Creative).filter(
            Creative.meta_ad_id == entity_id
        ).first()

        if not creative:
            return MetricsSnapshot(
                entity_type=entity_type,
                entity_id=entity_id,
                provider="csv",
                metrics={},
                available=False,
            )

        impressions = creative.impressions or 0
        clicks = creative.clicks or 0
        spend = creative.spend or 0.0
        conversions = creative.conversions or 0

        metrics = {
            "spend": spend,
            "impressions": impressions,
            "clicks": clicks,
            "conversions": conversions,
            "ctr": round((clicks / impressions * 100), 4) if impressions > 0 else 0,
            "cpm": round((spend / impressions * 1000), 4) if impressions > 0 else 0,
            "cpa": round((spend / conversions), 4) if conversions > 0 else 0,
        }

        return MetricsSnapshot(
            entity_type=entity_type,
            entity_id=entity_id,
            provider="csv",
            metrics=metrics,
            available=True,
        )
