"""
Sprint 6 – BLOQUE F: MetaMetricsProvider (REAL — DB-backed)
Reads from meta_insights_daily table. Never calls Meta API directly.
Falls back to NullProvider when no insights data available.
"""
from datetime import datetime, timedelta
from typing import Any, Dict
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.src.database.models import MetaInsightsDaily, InsightLevel
from backend.src.providers.metrics_provider import MetricsProvider, MetricsSnapshot
from backend.src.providers.null_provider import NullProvider


# Map entity_type strings to InsightLevel enum
_LEVEL_MAP = {
    "campaign": InsightLevel.CAMPAIGN,
    "adset": InsightLevel.ADSET,
    "ad": InsightLevel.AD,
}


class MetaMetricsProvider(MetricsProvider):
    """
    DB-backed Meta metrics provider.
    Reads aggregated metrics from meta_insights_daily over the specified window.
    Never calls Meta API — data comes from sync jobs.
    """

    def __init__(self, db: Session):
        self.db = db
        self._fallback = NullProvider()

    @property
    def provider_name(self) -> str:
        return "meta"

    def get_snapshot(
        self,
        org_id: UUID,
        entity_type: str,
        entity_id: str,
        window_minutes: int = 1440,
    ) -> MetricsSnapshot:
        level = _LEVEL_MAP.get(entity_type)
        if not level:
            return self._fallback.get_snapshot(org_id, entity_type, entity_id, window_minutes)

        # Calculate the time window
        since = datetime.utcnow() - timedelta(minutes=window_minutes)

        # Query aggregated metrics from meta_insights_daily
        rows = self.db.query(MetaInsightsDaily).filter(
            MetaInsightsDaily.org_id == org_id,
            MetaInsightsDaily.entity_meta_id == entity_id,
            MetaInsightsDaily.level == level,
            MetaInsightsDaily.date_start >= since,
        ).all()

        if not rows:
            return self._fallback.get_snapshot(org_id, entity_type, entity_id, window_minutes)

        # Aggregate metrics across the window
        total_spend = 0.0
        total_impressions = 0
        total_clicks = 0
        total_conversions = 0
        total_frequency = 0.0
        roas_values = []
        row_count = len(rows)

        for row in rows:
            total_spend += row.spend or 0.0
            total_impressions += row.impressions or 0
            total_clicks += row.clicks or 0
            total_conversions += row.conversions or 0
            total_frequency += row.frequency or 0.0
            if row.purchase_roas is not None:
                roas_values.append(row.purchase_roas)

        # Compute derived metrics
        ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0.0
        cpm = (total_spend / total_impressions * 1000) if total_impressions > 0 else 0.0
        cpc = (total_spend / total_clicks) if total_clicks > 0 else 0.0
        cpa = (total_spend / total_conversions) if total_conversions > 0 else 0.0
        avg_frequency = total_frequency / row_count if row_count > 0 else 0.0
        avg_roas = sum(roas_values) / len(roas_values) if roas_values else 0.0

        metrics: Dict[str, Any] = {
            "spend": round(total_spend, 2),
            "impressions": total_impressions,
            "clicks": total_clicks,
            "conversions": total_conversions,
            "ctr": round(ctr, 4),
            "cpm": round(cpm, 4),
            "cpc": round(cpc, 4),
            "cpa": round(cpa, 4),
            "roas": round(avg_roas, 4),
            "frequency": round(avg_frequency, 2),
        }

        return MetricsSnapshot(
            entity_type=entity_type,
            entity_id=entity_id,
            provider="meta",
            metrics=metrics,
            available=True,
        )
