"""
Sprint 5 – BLOQUE A: MetricsProviderFactory
Resolves the best available MetricsProvider for an organization.
"""
from uuid import UUID

from sqlalchemy.orm import Session

from backend.src.database.models import MetaConnection, Creative, AdAccount
from backend.src.providers.metrics_provider import MetricsProvider
from backend.src.providers.null_provider import NullProvider
from backend.src.providers.csv_provider import CsvMetricsProvider
from backend.src.providers.meta_provider import MetaMetricsProvider


class MetricsProviderFactory:
    """Resolves the best available MetricsProvider for an organization."""

    @staticmethod
    def get_provider(org_id: UUID, db: Session) -> MetricsProvider:
        # 1. Check if Meta OAuth is connected + active
        connection = db.query(MetaConnection).filter(
            MetaConnection.org_id == org_id,
            MetaConnection.status == "active",
        ).first()

        if connection:
            return MetaMetricsProvider(db)

        # 2. Check if CSV/performance data exists (creatives with impressions > 0)
        has_performance = db.query(Creative).join(
            AdAccount, Creative.ad_account_id == AdAccount.id
        ).join(
            MetaConnection, AdAccount.connection_id == MetaConnection.id
        ).filter(
            MetaConnection.org_id == org_id,
            Creative.impressions > 0,
        ).first()

        if has_performance:
            return CsvMetricsProvider(db)

        # 3. Fallback — no metrics available
        return NullProvider()
