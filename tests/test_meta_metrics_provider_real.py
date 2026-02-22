"""
Sprint 6 – Tests for MetaMetricsProvider (REAL DB-backed).
Validates that MetaMetricsProvider reads from meta_insights_daily,
aggregates across multiple rows, computes derived metrics, and falls
back to NullProvider when no data exists.
"""
import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PostgreSQL UUID type for SQLite compatibility — MUST happen before model imports
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

from backend.src.database.models import (
    Base,
    Organization,
    MetaAdAccount,
    MetaInsightsDaily,
    InsightLevel,
)
from backend.src.providers.meta_provider import MetaMetricsProvider


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_session():
    """Create an in-memory SQLite database with schema for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="function")
def seed_org(db_session):
    """Seed a single Organization and return its id."""
    org_id = uuid4()
    org = Organization(
        id=org_id,
        name="Test Org Real",
        slug=f"test-org-real-{org_id.hex[:8]}",
        created_at=datetime.utcnow(),
    )
    db_session.add(org)
    db_session.commit()
    return org_id


@pytest.fixture(scope="function")
def seed_ad_account(db_session, seed_org):
    """Seed a MetaAdAccount tied to the test org and return its id."""
    aa_id = uuid4()
    aa = MetaAdAccount(
        id=aa_id,
        org_id=seed_org,
        meta_account_id="act_real_001",
        name="Real Ad Account",
        currency="USD",
        created_at=datetime.utcnow(),
    )
    db_session.add(aa)
    db_session.commit()
    return aa_id


# ── Test class ───────────────────────────────────────────────────────────────


class TestMetaMetricsProviderReal:
    """Test MetaMetricsProvider reading from meta_insights_daily."""

    # ------------------------------------------------------------------
    # 1. get_snapshot returns metrics from meta_insights_daily rows
    # ------------------------------------------------------------------
    def test_get_snapshot_returns_metrics_from_insights_rows(
        self, db_session, seed_org, seed_ad_account
    ):
        """A single MetaInsightsDaily row should surface its values in the snapshot."""
        entity_meta_id = "campaign_100"
        now = datetime.utcnow()

        insight = MetaInsightsDaily(
            id=uuid4(),
            org_id=seed_org,
            ad_account_id=seed_ad_account,
            level=InsightLevel.CAMPAIGN,
            entity_meta_id=entity_meta_id,
            date_start=now - timedelta(hours=6),
            date_stop=now - timedelta(hours=5),
            spend=150.0,
            impressions=5000,
            clicks=200,
            conversions=10,
            frequency=1.5,
            purchase_roas=3.2,
            created_at=now,
        )
        db_session.add(insight)
        db_session.commit()

        provider = MetaMetricsProvider(db=db_session)
        snapshot = provider.get_snapshot(
            org_id=seed_org,
            entity_type="campaign",
            entity_id=entity_meta_id,
            window_minutes=1440,
        )

        assert snapshot.available is True
        assert snapshot.metrics["spend"] == 150.0
        assert snapshot.metrics["impressions"] == 5000
        assert snapshot.metrics["clicks"] == 200
        assert snapshot.metrics["conversions"] == 10
        assert snapshot.metrics["frequency"] == 1.5
        assert snapshot.metrics["roas"] == 3.2

    # ------------------------------------------------------------------
    # 2. get_snapshot aggregates multiple days correctly
    # ------------------------------------------------------------------
    def test_get_snapshot_aggregates_multiple_days(
        self, db_session, seed_org, seed_ad_account
    ):
        """Multiple insight rows should be summed for spend, clicks, impressions."""
        entity_meta_id = "campaign_200"
        now = datetime.utcnow()

        day1 = MetaInsightsDaily(
            id=uuid4(),
            org_id=seed_org,
            ad_account_id=seed_ad_account,
            level=InsightLevel.CAMPAIGN,
            entity_meta_id=entity_meta_id,
            date_start=now - timedelta(hours=20),
            date_stop=now - timedelta(hours=19),
            spend=100.0,
            impressions=4000,
            clicks=120,
            conversions=6,
            frequency=1.2,
            purchase_roas=2.5,
            created_at=now,
        )
        day2 = MetaInsightsDaily(
            id=uuid4(),
            org_id=seed_org,
            ad_account_id=seed_ad_account,
            level=InsightLevel.CAMPAIGN,
            entity_meta_id=entity_meta_id,
            date_start=now - timedelta(hours=10),
            date_stop=now - timedelta(hours=9),
            spend=200.0,
            impressions=6000,
            clicks=180,
            conversions=14,
            frequency=1.8,
            purchase_roas=3.5,
            created_at=now,
        )
        db_session.add_all([day1, day2])
        db_session.commit()

        provider = MetaMetricsProvider(db=db_session)
        snapshot = provider.get_snapshot(
            org_id=seed_org,
            entity_type="campaign",
            entity_id=entity_meta_id,
            window_minutes=1440,
        )

        assert snapshot.available is True
        assert snapshot.metrics["spend"] == 300.0      # 100 + 200
        assert snapshot.metrics["clicks"] == 300        # 120 + 180
        assert snapshot.metrics["impressions"] == 10000  # 4000 + 6000
        assert snapshot.metrics["conversions"] == 20     # 6 + 14

        # frequency is averaged: (1.2 + 1.8) / 2 = 1.5
        assert snapshot.metrics["frequency"] == 1.5

        # roas is averaged: (2.5 + 3.5) / 2 = 3.0
        assert snapshot.metrics["roas"] == 3.0

    # ------------------------------------------------------------------
    # 3. get_snapshot computes derived metrics (ctr, cpm, cpc, cpa)
    # ------------------------------------------------------------------
    def test_get_snapshot_computes_derived_metrics(
        self, db_session, seed_org, seed_ad_account
    ):
        """Derived metrics must be calculated from aggregated raw values."""
        entity_meta_id = "adset_300"
        now = datetime.utcnow()

        insight = MetaInsightsDaily(
            id=uuid4(),
            org_id=seed_org,
            ad_account_id=seed_ad_account,
            level=InsightLevel.ADSET,
            entity_meta_id=entity_meta_id,
            date_start=now - timedelta(hours=12),
            date_stop=now - timedelta(hours=11),
            spend=500.0,
            impressions=10000,
            clicks=250,
            conversions=25,
            frequency=2.0,
            purchase_roas=4.0,
            created_at=now,
        )
        db_session.add(insight)
        db_session.commit()

        provider = MetaMetricsProvider(db=db_session)
        snapshot = provider.get_snapshot(
            org_id=seed_org,
            entity_type="adset",
            entity_id=entity_meta_id,
            window_minutes=1440,
        )

        assert snapshot.available is True

        # ctr = clicks / impressions * 100 = 250/10000*100 = 2.5
        assert snapshot.metrics["ctr"] == round(250 / 10000 * 100, 4)

        # cpm = spend / impressions * 1000 = 500/10000*1000 = 50.0
        assert snapshot.metrics["cpm"] == round(500.0 / 10000 * 1000, 4)

        # cpc = spend / clicks = 500/250 = 2.0
        assert snapshot.metrics["cpc"] == round(500.0 / 250, 4)

        # cpa = spend / conversions = 500/25 = 20.0
        assert snapshot.metrics["cpa"] == round(500.0 / 25, 4)

    # ------------------------------------------------------------------
    # 4. get_snapshot returns available=False when no insights exist
    # ------------------------------------------------------------------
    def test_get_snapshot_returns_unavailable_when_no_insights(
        self, db_session, seed_org, seed_ad_account
    ):
        """When no MetaInsightsDaily rows match, fall back to NullProvider."""
        provider = MetaMetricsProvider(db=db_session)
        snapshot = provider.get_snapshot(
            org_id=seed_org,
            entity_type="campaign",
            entity_id="campaign_nonexistent",
            window_minutes=1440,
        )

        assert snapshot.available is False
        assert snapshot.metrics == {}
        assert snapshot.provider == "null"

    # ------------------------------------------------------------------
    # 5. get_snapshot filters by entity_meta_id and level
    # ------------------------------------------------------------------
    def test_get_snapshot_filters_by_entity_and_level(
        self, db_session, seed_org, seed_ad_account
    ):
        """Only rows matching the requested entity_meta_id AND level are included."""
        now = datetime.utcnow()

        # Row for campaign_500 at CAMPAIGN level (target)
        target_row = MetaInsightsDaily(
            id=uuid4(),
            org_id=seed_org,
            ad_account_id=seed_ad_account,
            level=InsightLevel.CAMPAIGN,
            entity_meta_id="campaign_500",
            date_start=now - timedelta(hours=6),
            date_stop=now - timedelta(hours=5),
            spend=75.0,
            impressions=3000,
            clicks=90,
            conversions=5,
            frequency=1.1,
            purchase_roas=2.0,
            created_at=now,
        )

        # Row for a DIFFERENT entity_meta_id at the same level (should be excluded)
        other_entity = MetaInsightsDaily(
            id=uuid4(),
            org_id=seed_org,
            ad_account_id=seed_ad_account,
            level=InsightLevel.CAMPAIGN,
            entity_meta_id="campaign_999",
            date_start=now - timedelta(hours=6),
            date_stop=now - timedelta(hours=5),
            spend=9999.0,
            impressions=99999,
            clicks=9999,
            conversions=999,
            frequency=5.0,
            purchase_roas=10.0,
            created_at=now,
        )

        # Row for the SAME entity_meta_id but at ADSET level (should be excluded)
        wrong_level = MetaInsightsDaily(
            id=uuid4(),
            org_id=seed_org,
            ad_account_id=seed_ad_account,
            level=InsightLevel.ADSET,
            entity_meta_id="campaign_500",
            date_start=now - timedelta(hours=6),
            date_stop=now - timedelta(hours=5),
            spend=8888.0,
            impressions=88888,
            clicks=8888,
            conversions=888,
            frequency=4.0,
            purchase_roas=9.0,
            created_at=now,
        )

        db_session.add_all([target_row, other_entity, wrong_level])
        db_session.commit()

        provider = MetaMetricsProvider(db=db_session)
        snapshot = provider.get_snapshot(
            org_id=seed_org,
            entity_type="campaign",
            entity_id="campaign_500",
            window_minutes=1440,
        )

        assert snapshot.available is True
        # Only the target row values must appear
        assert snapshot.metrics["spend"] == 75.0
        assert snapshot.metrics["impressions"] == 3000
        assert snapshot.metrics["clicks"] == 90
        assert snapshot.metrics["conversions"] == 5

    # ------------------------------------------------------------------
    # 6. get_snapshot returns provider="meta" when data exists
    # ------------------------------------------------------------------
    def test_get_snapshot_returns_provider_meta_when_data_exists(
        self, db_session, seed_org, seed_ad_account
    ):
        """The snapshot provider field must be 'meta' when insights are found."""
        entity_meta_id = "ad_600"
        now = datetime.utcnow()

        insight = MetaInsightsDaily(
            id=uuid4(),
            org_id=seed_org,
            ad_account_id=seed_ad_account,
            level=InsightLevel.AD,
            entity_meta_id=entity_meta_id,
            date_start=now - timedelta(hours=3),
            date_stop=now - timedelta(hours=2),
            spend=50.0,
            impressions=2000,
            clicks=80,
            conversions=4,
            frequency=1.0,
            purchase_roas=1.5,
            created_at=now,
        )
        db_session.add(insight)
        db_session.commit()

        provider = MetaMetricsProvider(db=db_session)
        snapshot = provider.get_snapshot(
            org_id=seed_org,
            entity_type="ad",
            entity_id=entity_meta_id,
            window_minutes=1440,
        )

        assert snapshot.provider == "meta"
        assert snapshot.entity_type == "ad"
        assert snapshot.entity_id == entity_meta_id
        assert snapshot.available is True

    # ------------------------------------------------------------------
    # 7. (bonus) unknown entity_type falls back to NullProvider
    # ------------------------------------------------------------------
    def test_get_snapshot_unknown_entity_type_falls_back(
        self, db_session, seed_org
    ):
        """An unrecognized entity_type (not campaign/adset/ad) should fall back."""
        provider = MetaMetricsProvider(db=db_session)
        snapshot = provider.get_snapshot(
            org_id=seed_org,
            entity_type="pixel",
            entity_id="pixel_123",
            window_minutes=1440,
        )

        assert snapshot.available is False
        assert snapshot.provider == "null"
        assert snapshot.metrics == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
