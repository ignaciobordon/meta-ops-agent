"""
Unit tests for Sprint 5 MetricsProvider system.
Tests NullProvider, CsvMetricsProvider, MetaMetricsProvider, MetricsProviderFactory,
and MetricsSnapshot schema validation.
"""
import pytest
from datetime import datetime
from uuid import uuid4
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PostgreSQL UUID type for SQLite compatibility
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

from backend.src.database.models import (
    Base, Organization, MetaConnection, AdAccount, Creative,
)
from backend.src.providers.metrics_provider import MetricsSnapshot
from backend.src.providers.null_provider import NullProvider
from backend.src.providers.csv_provider import CsvMetricsProvider
from backend.src.providers.meta_provider import MetaMetricsProvider
from backend.src.providers.provider_factory import MetricsProviderFactory


# Test database setup
@pytest.fixture(scope="function")
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    org_id = uuid4()
    connection_id = uuid4()
    ad_account_id = uuid4()

    # Create test organization
    org = Organization(
        id=org_id,
        name="Test Org",
        slug="test-org-metrics",
        created_at=datetime.utcnow(),
    )
    session.add(org)

    # Create test Meta connection (active)
    connection = MetaConnection(
        id=connection_id,
        org_id=org_id,
        access_token_encrypted="enc_test_token",
        status="active",
        connected_at=datetime.utcnow(),
    )
    session.add(connection)

    # Create test ad account
    ad_account = AdAccount(
        id=ad_account_id,
        connection_id=connection_id,
        meta_ad_account_id="act_metrics_001",
        name="Test Ad Account",
        currency="USD",
    )
    session.add(ad_account)

    # Create test creative with performance data
    creative = Creative(
        id=uuid4(),
        ad_account_id=ad_account_id,
        meta_ad_id="ad_12345",
        name="Test Creative",
        impressions=10000,
        clicks=250,
        spend=500.0,
        conversions=25,
    )
    session.add(creative)

    session.commit()

    yield session

    session.close()


class TestNullProvider:
    """Test NullProvider returns unavailable metrics."""

    def test_null_provider_returns_unavailable_with_empty_metrics(self):
        """Scenario 1: NullProvider returns available=False with empty metrics."""
        provider = NullProvider()
        org_id = uuid4()

        snapshot = provider.get_snapshot(
            org_id=org_id,
            entity_type="ad",
            entity_id="ad_99999",
        )

        assert snapshot.available is False
        assert snapshot.metrics == {}
        assert snapshot.provider == "null"
        assert snapshot.entity_type == "ad"
        assert snapshot.entity_id == "ad_99999"


class TestCsvMetricsProvider:
    """Test CsvMetricsProvider queries Creative and computes metrics."""

    def test_csv_provider_finds_creative_and_computes_metrics(self, db_session):
        """Scenario 2: CsvProvider finds Creative by meta_ad_id and computes metrics correctly."""
        provider = CsvMetricsProvider(db=db_session)
        org_id = db_session.query(Organization).first().id

        snapshot = provider.get_snapshot(
            org_id=org_id,
            entity_type="ad",
            entity_id="ad_12345",
        )

        assert snapshot.available is True
        assert snapshot.provider == "csv"
        assert snapshot.entity_type == "ad"
        assert snapshot.entity_id == "ad_12345"

        # Verify raw metrics
        assert snapshot.metrics["impressions"] == 10000
        assert snapshot.metrics["clicks"] == 250
        assert snapshot.metrics["spend"] == 500.0
        assert snapshot.metrics["conversions"] == 25

        # Verify computed metrics: ctr = clicks / impressions * 100
        expected_ctr = round((250 / 10000 * 100), 4)
        assert snapshot.metrics["ctr"] == expected_ctr  # 2.5

        # Verify computed metrics: cpm = spend / impressions * 1000
        expected_cpm = round((500.0 / 10000 * 1000), 4)
        assert snapshot.metrics["cpm"] == expected_cpm  # 50.0

        # Verify computed metrics: cpa = spend / conversions
        expected_cpa = round((500.0 / 25), 4)
        assert snapshot.metrics["cpa"] == expected_cpa  # 20.0

    def test_csv_provider_returns_unavailable_for_missing_creative(self, db_session):
        """Scenario 3: CsvProvider returns available=False for missing creative."""
        provider = CsvMetricsProvider(db=db_session)
        org_id = db_session.query(Organization).first().id

        snapshot = provider.get_snapshot(
            org_id=org_id,
            entity_type="ad",
            entity_id="ad_nonexistent",
        )

        assert snapshot.available is False
        assert snapshot.metrics == {}
        assert snapshot.provider == "csv"
        assert snapshot.entity_type == "ad"
        assert snapshot.entity_id == "ad_nonexistent"


class TestMetaMetricsProvider:
    """Test MetaMetricsProvider falls back to NullProvider."""

    def test_meta_provider_falls_back_to_null(self, db_session):
        """Scenario 4: MetaProvider falls back to NullProvider (Sprint 6 stub)."""
        provider = MetaMetricsProvider(db=db_session)
        org_id = db_session.query(Organization).first().id

        snapshot = provider.get_snapshot(
            org_id=org_id,
            entity_type="ad",
            entity_id="ad_12345",
        )

        # MetaProvider delegates to NullProvider, so available=False
        assert snapshot.available is False
        assert snapshot.metrics == {}
        assert snapshot.provider == "null"
        assert provider.provider_name == "meta"


class TestMetricsProviderFactory:
    """Test MetricsProviderFactory resolves the best provider for an org."""

    def test_factory_returns_null_provider_when_no_connections(self, db_session):
        """Scenario 5: Factory returns NullProvider when no connections exist for org."""
        # Create an org with no connections at all
        lonely_org_id = uuid4()
        lonely_org = Organization(
            id=lonely_org_id,
            name="Lonely Org",
            slug="lonely-org-no-conn",
            created_at=datetime.utcnow(),
        )
        db_session.add(lonely_org)
        db_session.commit()

        provider = MetricsProviderFactory.get_provider(lonely_org_id, db_session)

        assert isinstance(provider, NullProvider)
        assert provider.provider_name == "null"

    def test_factory_returns_csv_provider_when_creatives_have_performance(self, db_session):
        """Scenario 6: Factory returns CsvProvider when creatives have performance data."""
        # Create a separate org with an expired connection (not active)
        # so the first check (active connection) fails,
        # but the performance data check succeeds.
        csv_org_id = uuid4()
        csv_connection_id = uuid4()
        csv_ad_account_id = uuid4()

        csv_org = Organization(
            id=csv_org_id,
            name="CSV Org",
            slug="csv-org-perf",
            created_at=datetime.utcnow(),
        )
        db_session.add(csv_org)

        csv_connection = MetaConnection(
            id=csv_connection_id,
            org_id=csv_org_id,
            access_token_encrypted="enc_expired_token",
            status="expired",
            connected_at=datetime.utcnow(),
        )
        db_session.add(csv_connection)

        csv_ad_account = AdAccount(
            id=csv_ad_account_id,
            connection_id=csv_connection_id,
            meta_ad_account_id="act_csv_002",
            name="CSV Ad Account",
            currency="USD",
        )
        db_session.add(csv_ad_account)

        csv_creative = Creative(
            id=uuid4(),
            ad_account_id=csv_ad_account_id,
            meta_ad_id="ad_csv_perf",
            name="Creative With Performance",
            impressions=5000,
            clicks=100,
            spend=200.0,
            conversions=10,
        )
        db_session.add(csv_creative)
        db_session.commit()

        provider = MetricsProviderFactory.get_provider(csv_org_id, db_session)

        assert isinstance(provider, CsvMetricsProvider)
        assert provider.provider_name == "csv"


class TestMetricsSnapshot:
    """Test MetricsSnapshot Pydantic schema validation."""

    def test_metrics_snapshot_validates_correctly(self):
        """Scenario 7: MetricsSnapshot schema validates correctly."""
        snapshot = MetricsSnapshot(
            entity_type="ad",
            entity_id="ad_schema_test",
            provider="csv",
            metrics={"spend": 100.0, "impressions": 5000, "ctr": 2.5},
            available=True,
        )

        assert snapshot.entity_type == "ad"
        assert snapshot.entity_id == "ad_schema_test"
        assert snapshot.provider == "csv"
        assert snapshot.metrics["spend"] == 100.0
        assert snapshot.metrics["impressions"] == 5000
        assert snapshot.metrics["ctr"] == 2.5
        assert snapshot.available is True
        assert snapshot.timestamp is not None
        assert isinstance(snapshot.timestamp, datetime)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
