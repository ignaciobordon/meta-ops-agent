"""
Sprint 8 -- Analytics API Tests.
Tests the analytics endpoints that aggregate real data from MetaInsightsDaily:
summary, spend-over-time, top-campaigns, daily breakdown, and benchmarks.
10 tests covering GET /api/analytics/summary, /spend-over-time,
/top-campaigns, /daily, and /benchmarks.
"""
import os
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.main import app
from backend.src.database.models import (
    Base, Organization, MetaAdAccount, MetaCampaign, MetaInsightsDaily,
    InsightLevel, OrgBenchmark,
)
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user, require_admin


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db_session(db_engine):
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="function")
def override_db(db_engine):
    """Override get_db to use the in-memory SQLite engine."""

    def _override():
        SessionLocal = sessionmaker(bind=db_engine)
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(scope="function")
def org_id(db_session):
    """Create an Organization row and return its id."""
    _org_id = uuid4()
    org = Organization(
        id=_org_id,
        name="Test Org",
        slug="test-org",
        created_at=datetime.utcnow(),
    )
    db_session.add(org)
    db_session.commit()
    return _org_id


@pytest.fixture(scope="function")
def mock_user(org_id):
    """Return a dict representing the authenticated admin user."""
    return {
        "user_id": str(uuid4()),
        "org_id": str(org_id),
        "role": "admin",
        "email": "admin@test-org.com",
    }


@pytest.fixture(scope="function")
def client(override_db, db_session, org_id, mock_user):
    """TestClient with get_db, get_current_user, and require_admin overridden."""

    def fake_user():
        return mock_user

    def fake_admin():
        return None

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[require_admin] = fake_admin
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _seed_insights(db_session, org_id, days=7):
    """Seed a MetaAdAccount, MetaCampaign, and MetaInsightsDaily rows for N days."""
    ad_account_id = uuid4()
    ad_account = MetaAdAccount(
        id=ad_account_id,
        org_id=org_id,
        meta_account_id="act_123",
        name="Test Account",
        created_at=datetime.utcnow(),
    )
    db_session.add(ad_account)

    campaign_id = uuid4()
    campaign = MetaCampaign(
        id=campaign_id,
        org_id=org_id,
        ad_account_id=ad_account_id,
        meta_campaign_id="camp_1",
        name="Test Campaign",
        created_at=datetime.utcnow(),
    )
    db_session.add(campaign)

    for i in range(days):
        day = datetime.utcnow() - timedelta(days=i)
        insight = MetaInsightsDaily(
            id=uuid4(),
            org_id=org_id,
            ad_account_id=ad_account_id,
            level=InsightLevel.CAMPAIGN,
            entity_meta_id="camp_1",
            date_start=day,
            date_stop=day,
            spend=100.0 + i * 10,
            impressions=5000 + i * 100,
            clicks=100 + i * 5,
            ctr=2.0,
            cpc=1.0,
            cpm=20.0,
            frequency=1.5,
            conversions=10 + i,
            purchase_roas=2.5,
        )
        db_session.add(insight)

    db_session.commit()
    return {"ad_account_id": ad_account_id, "campaign_id": campaign_id}


# ── Tests ────────────────────────────────────────────────────────────────────


class TestAnalyticsSummary:

    def test_summary_empty(self, client, org_id):
        """GET /api/analytics/summary with no data returns zeros."""
        resp = client.get("/api/analytics/summary")
        assert resp.status_code == 200

        data = resp.json()
        assert data["total_spend"] == 0
        assert data["total_impressions"] == 0
        assert data["total_clicks"] == 0
        assert data["total_conversions"] == 0
        assert data["avg_ctr"] == 0
        assert data["avg_cpc"] == 0
        assert data["avg_cpm"] == 0
        assert data["avg_roas"] == 0
        assert data["period_days"] == 7

    def test_summary_with_data(self, client, db_session, org_id):
        """Seed insights, GET /api/analytics/summary returns correct totals."""
        _seed_insights(db_session, org_id, days=7)

        resp = client.get("/api/analytics/summary")
        assert resp.status_code == 200

        data = resp.json()
        # 7 days: spend = 100+110+120+130+140+150+160 = 910
        assert data["total_spend"] == 910.0
        # impressions = 5000+5100+5200+5300+5400+5500+5600 = 37100
        assert data["total_impressions"] == 37100
        # clicks = 100+105+110+115+120+125+130 = 805
        assert data["total_clicks"] == 805
        # conversions = 10+11+12+13+14+15+16 = 91
        assert data["total_conversions"] == 91
        assert data["period_days"] == 7
        # avg_ctr = (805/38100)*100 ~ 2.11
        assert data["avg_ctr"] > 0
        # avg_cpc = 910/805 ~ 1.13
        assert data["avg_cpc"] > 0
        # avg_roas = 2.5 (all rows have 2.5)
        assert data["avg_roas"] == 2.5

    def test_summary_period_parameter(self, client, db_session, org_id):
        """GET /api/analytics/summary?days=14 respects the period parameter."""
        _seed_insights(db_session, org_id, days=14)

        resp = client.get("/api/analytics/summary?days=14")
        assert resp.status_code == 200

        data = resp.json()
        assert data["period_days"] == 14
        # 14 days of data, all within the 14-day window
        assert data["total_spend"] > 0
        assert data["total_impressions"] > 0
        assert data["total_clicks"] > 0
        assert data["total_conversions"] > 0


class TestSpendOverTime:

    def test_spend_over_time_empty(self, client, org_id):
        """GET /api/analytics/spend-over-time with no data returns empty list."""
        resp = client.get("/api/analytics/spend-over-time")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_spend_over_time_with_data(self, client, db_session, org_id):
        """Seed insights, GET /api/analytics/spend-over-time returns daily spend entries."""
        _seed_insights(db_session, org_id, days=7)

        resp = client.get("/api/analytics/spend-over-time?days=30")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 7  # 7 distinct days
        # Each entry has date and spend keys
        for entry in data:
            assert "date" in entry
            assert "spend" in entry
            assert entry["spend"] > 0


class TestTopCampaigns:

    def test_top_campaigns_empty(self, client, org_id):
        """GET /api/analytics/top-campaigns returns empty list when no data."""
        resp = client.get("/api/analytics/top-campaigns")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_top_campaigns_with_data(self, client, db_session, org_id):
        """Seed insights, GET /api/analytics/top-campaigns returns campaigns sorted by spend."""
        _seed_insights(db_session, org_id, days=7)

        resp = client.get("/api/analytics/top-campaigns")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) >= 1
        top = data[0]
        assert top["campaign_id"] == "camp_1"
        assert top["name"] == "Test Campaign"
        assert top["spend"] == 910.0  # Sum of 7 days
        assert top["clicks"] == 805
        assert top["impressions"] == 37100
        assert top["conversions"] == 91
        assert top["ctr"] > 0


class TestDailyBreakdown:

    def test_daily_breakdown(self, client, db_session, org_id):
        """GET /api/analytics/daily returns daily metrics for each day."""
        _seed_insights(db_session, org_id, days=7)

        resp = client.get("/api/analytics/daily?days=30")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 7
        for entry in data:
            assert "date" in entry
            assert "spend" in entry
            assert "impressions" in entry
            assert "clicks" in entry
            assert "conversions" in entry
            assert entry["spend"] > 0
            assert entry["impressions"] > 0
            assert entry["clicks"] > 0
            assert entry["conversions"] > 0


class TestBenchmarks:

    def test_benchmarks_empty(self, client, org_id):
        """GET /api/analytics/benchmarks returns empty when no benchmarks exist."""
        resp = client.get("/api/analytics/benchmarks")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_benchmarks_with_data(self, client, db_session, org_id):
        """Create OrgBenchmark rows, GET /api/analytics/benchmarks returns them."""
        ad_account_id = uuid4()
        ad_account = MetaAdAccount(
            id=ad_account_id,
            org_id=org_id,
            meta_account_id="act_bench_001",
            name="Benchmark Account",
            created_at=datetime.utcnow(),
        )
        db_session.add(ad_account)

        metrics = [
            ("spend", 150.0, 180.0, 20.0),
            ("ctr", 2.0, 2.3, 15.0),
            ("cpc", 1.2, 1.0, -16.67),
        ]
        for metric_name, baseline, current, delta in metrics:
            bm = OrgBenchmark(
                id=uuid4(),
                org_id=org_id,
                ad_account_id=ad_account_id,
                metric_name=metric_name,
                baseline_value=baseline,
                current_value=current,
                delta_pct=delta,
                period_days=30,
                computed_at=datetime.utcnow(),
            )
            db_session.add(bm)
        db_session.commit()

        resp = client.get("/api/analytics/benchmarks")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 3

        metric_names = [b["metric_name"] for b in data]
        assert "spend" in metric_names
        assert "ctr" in metric_names
        assert "cpc" in metric_names

        spend_bm = next(b for b in data if b["metric_name"] == "spend")
        assert spend_bm["baseline_value"] == 150.0
        assert spend_bm["current_value"] == 180.0
        assert spend_bm["delta_pct"] == 20.0
        assert spend_bm["period_days"] == 30
        assert spend_bm["computed_at"] is not None
