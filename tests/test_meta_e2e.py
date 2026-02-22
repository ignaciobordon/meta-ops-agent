"""
Sprint 6 E2E Tests -- Meta Sync API Endpoints
Tests the /api/meta/* endpoints via TestClient with SQLite in-memory DB.
Covers: sync status, sync-now trigger, campaigns listing, alerts listing,
insights filtering, campaign search/filter, and multi-tenant isolation.
"""
import os
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PG_UUID before any model imports so SQLite works with UUID columns
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from fastapi.testclient import TestClient
from backend.main import app
from backend.src.database.models import (
    Base,
    Organization,
    User,
    UserOrgRole,
    RoleEnum,
    MetaConnection,
    ConnectionStatus,
    Subscription,
    PlanEnum,
    SubscriptionStatusEnum,
    MetaAdAccount,
    MetaCampaign,
    MetaInsightsDaily,
    MetaSyncRun,
    MetaAlert,
    AlertSeverity,
    InsightLevel,
    SyncRunStatus,
    ScheduledJob,
    SyncJobType,
)
from backend.src.database.session import get_db
from backend.src.middleware.auth import create_access_token, hash_password


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
    SessionLocal = sessionmaker(bind=db_engine)

    def _override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    yield
    app.dependency_overrides.clear()


# ── Seed Helpers ─────────────────────────────────────────────────────────────


def _seed_meta_org(db_session, org_name, slug, email, role=RoleEnum.ADMIN, plan=PlanEnum.PRO):
    """Seed a full org with user, role, meta connection, subscription,
    MetaAdAccount, MetaCampaign, MetaInsightsDaily, and MetaAlert.
    Returns a dict with all generated IDs and an auth token.
    """
    org_id = uuid4()
    org = Organization(
        id=org_id, name=org_name, slug=slug,
        operator_armed=True, created_at=datetime.utcnow(),
    )
    db_session.add(org)

    user_id = uuid4()
    user = User(
        id=user_id, email=email, name=f"User {org_name}",
        password_hash=hash_password("TestPass123"),
        created_at=datetime.utcnow(),
    )
    db_session.add(user)

    user_role = UserOrgRole(
        id=uuid4(), user_id=user_id, org_id=org_id,
        role=role, assigned_at=datetime.utcnow(),
    )
    db_session.add(user_role)

    conn_id = uuid4()
    conn = MetaConnection(
        id=conn_id, org_id=org_id,
        access_token_encrypted="enc_test_token",
        status="active",
        connected_at=datetime.utcnow(),
    )
    db_session.add(conn)

    sub = Subscription(
        id=uuid4(), org_id=org_id,
        plan=plan,
        status=SubscriptionStatusEnum.ACTIVE if plan != PlanEnum.TRIAL else SubscriptionStatusEnum.TRIALING,
        max_ad_accounts=100 if plan != PlanEnum.TRIAL else 1,
        max_decisions_per_month=1000,
        max_creatives_per_month=500,
        allow_live_execution=plan != PlanEnum.TRIAL,
        created_at=datetime.utcnow(),
    )
    db_session.add(sub)

    # MetaAdAccount
    meta_ad_account_id = uuid4()
    meta_ad_account = MetaAdAccount(
        id=meta_ad_account_id, org_id=org_id,
        meta_account_id=f"act_{slug}_001",
        name=f"{org_name} Ad Account",
        currency="USD", timezone_name="America/New_York",
        status="active",
        created_at=datetime.utcnow(),
    )
    db_session.add(meta_ad_account)

    # MetaCampaign
    campaign_id = uuid4()
    campaign = MetaCampaign(
        id=campaign_id, org_id=org_id,
        ad_account_id=meta_ad_account_id,
        meta_campaign_id=f"camp_{slug}_001",
        name=f"{org_name} Sales Campaign",
        objective="CONVERSIONS",
        status="ACTIVE",
        effective_status="ACTIVE",
        daily_budget=50.0,
        lifetime_budget=1500.0,
        bid_strategy="LOWEST_COST",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(campaign)

    # Second campaign (PAUSED) for filter testing
    campaign2_id = uuid4()
    campaign2 = MetaCampaign(
        id=campaign2_id, org_id=org_id,
        ad_account_id=meta_ad_account_id,
        meta_campaign_id=f"camp_{slug}_002",
        name=f"{org_name} Brand Awareness",
        objective="BRAND_AWARENESS",
        status="PAUSED",
        effective_status="PAUSED",
        daily_budget=25.0,
        bid_strategy="LOWEST_COST",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(campaign2)

    # MetaInsightsDaily -- campaign level
    insight_campaign_id = uuid4()
    insight_campaign = MetaInsightsDaily(
        id=insight_campaign_id, org_id=org_id,
        ad_account_id=meta_ad_account_id,
        level=InsightLevel.CAMPAIGN,
        entity_meta_id=f"camp_{slug}_001",
        date_start=datetime(2026, 2, 15),
        date_stop=datetime(2026, 2, 15),
        spend=120.50, impressions=5000, clicks=250,
        ctr=5.0, cpm=24.10, cpc=0.48,
        frequency=1.8, conversions=12, purchase_roas=3.2,
        created_at=datetime.utcnow(),
    )
    db_session.add(insight_campaign)

    # MetaInsightsDaily -- adset level
    insight_adset_id = uuid4()
    insight_adset = MetaInsightsDaily(
        id=insight_adset_id, org_id=org_id,
        ad_account_id=meta_ad_account_id,
        level=InsightLevel.ADSET,
        entity_meta_id=f"adset_{slug}_001",
        date_start=datetime(2026, 2, 15),
        date_stop=datetime(2026, 2, 15),
        spend=60.25, impressions=2500, clicks=125,
        ctr=5.0, cpm=24.10, cpc=0.48,
        frequency=1.4, conversions=6, purchase_roas=2.8,
        created_at=datetime.utcnow(),
    )
    db_session.add(insight_adset)

    # MetaAlert -- active (no resolved_at)
    alert_id = uuid4()
    alert = MetaAlert(
        id=alert_id, org_id=org_id,
        ad_account_id=meta_ad_account_id,
        alert_type="ctr_low",
        severity=AlertSeverity.HIGH,
        message="CTR dropped below 1% for campaign Sales Campaign",
        entity_type="campaign",
        entity_meta_id=f"camp_{slug}_001",
        detected_at=datetime.utcnow(),
        resolved_at=None,
        payload_json={"current_ctr": 0.8, "threshold": 1.0},
        created_at=datetime.utcnow(),
    )
    db_session.add(alert)

    # Second active alert with different severity
    alert2_id = uuid4()
    alert2 = MetaAlert(
        id=alert2_id, org_id=org_id,
        ad_account_id=meta_ad_account_id,
        alert_type="spend_spike_no_conv",
        severity=AlertSeverity.CRITICAL,
        message="Spend spike with zero conversions on Brand Awareness",
        entity_type="campaign",
        entity_meta_id=f"camp_{slug}_002",
        detected_at=datetime.utcnow() - timedelta(hours=1),
        resolved_at=None,
        payload_json={"spend": 200.0, "conversions": 0},
        created_at=datetime.utcnow(),
    )
    db_session.add(alert2)

    # Resolved alert (should NOT appear in active alerts query)
    alert3_id = uuid4()
    alert3 = MetaAlert(
        id=alert3_id, org_id=org_id,
        ad_account_id=meta_ad_account_id,
        alert_type="frequency_decay",
        severity=AlertSeverity.MEDIUM,
        message="Frequency decay resolved",
        entity_type="campaign",
        entity_meta_id=f"camp_{slug}_001",
        detected_at=datetime.utcnow() - timedelta(days=2),
        resolved_at=datetime.utcnow() - timedelta(days=1),
        created_at=datetime.utcnow(),
    )
    db_session.add(alert3)

    db_session.commit()

    token = create_access_token(
        user_id=str(user_id), email=email,
        role=role.value, org_id=str(org_id),
    )

    return {
        "org_id": org_id,
        "user_id": user_id,
        "conn_id": conn_id,
        "meta_ad_account_id": meta_ad_account_id,
        "campaign_id": campaign_id,
        "campaign2_id": campaign2_id,
        "insight_campaign_id": insight_campaign_id,
        "insight_adset_id": insight_adset_id,
        "alert_id": alert_id,
        "alert2_id": alert2_id,
        "alert3_id": alert3_id,
        "token": token,
    }


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── Test 1: GET /api/meta/sync/status ────────────────────────────────────────


class TestSyncStatus:

    def test_sync_status_returns_ad_account_info(self, db_session, override_db):
        """GET /api/meta/sync/status returns one entry per MetaAdAccount
        with sync lag info, error counts, and pending job counts.
        """
        data = _seed_meta_org(db_session, "SyncStatus Org", "syncstatus", "sync@test.com")

        # Seed a completed MetaSyncRun (assets) so lag is computed
        sync_run = MetaSyncRun(
            id=uuid4(), org_id=data["org_id"],
            ad_account_id=data["meta_ad_account_id"],
            job_type="assets",
            status=SyncRunStatus.SUCCESS,
            started_at=datetime.utcnow() - timedelta(minutes=10),
            finished_at=datetime.utcnow() - timedelta(minutes=5),
            duration_ms=5000, items_upserted=20,
            created_at=datetime.utcnow(),
        )
        db_session.add(sync_run)

        # Seed a failed MetaSyncRun to verify error_count
        failed_run = MetaSyncRun(
            id=uuid4(), org_id=data["org_id"],
            ad_account_id=data["meta_ad_account_id"],
            job_type="insights",
            status=SyncRunStatus.FAILED,
            started_at=datetime.utcnow() - timedelta(minutes=20),
            finished_at=datetime.utcnow() - timedelta(minutes=19),
            duration_ms=1000, error_count=1,
            error_summary_json={"error": "rate_limit"},
            created_at=datetime.utcnow(),
        )
        db_session.add(failed_run)

        # Seed a pending ScheduledJob
        pending_job = ScheduledJob(
            id=uuid4(), org_id=data["org_id"],
            job_type=SyncJobType.META_SYNC_ASSETS.value,
            reference_id=data["meta_ad_account_id"],
            scheduled_for=datetime.utcnow() + timedelta(minutes=5),
            completed_at=None,
            created_at=datetime.utcnow(),
        )
        db_session.add(pending_job)
        db_session.commit()

        client = TestClient(app)
        resp = client.get(
            "/api/meta/sync/status",
            headers=_auth(data["token"]),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 1

        entry = body[0]
        assert entry["ad_account_id"] == str(data["meta_ad_account_id"])
        assert entry["meta_account_id"] == "act_syncstatus_001"
        # Assets sync was 5 min ago, so lag should be >= 5
        assert entry["last_assets_sync"] is not None
        assert entry["assets_lag_minutes"] is not None
        assert entry["assets_lag_minutes"] >= 4  # allow slight timing variance
        # 1 failed run in DB
        assert entry["recent_error_count"] == 1
        # 1 pending job
        assert entry["pending_jobs"] == 1


# ── Test 2: POST /api/meta/sync/now ──────────────────────────────────────────


class TestSyncNow:

    def test_sync_now_enqueues_jobs(self, db_session, override_db):
        """POST /api/meta/sync/now enqueues sync jobs for all org ad accounts.
        We mock MetaJobScheduler.enqueue_if_missing to avoid side effects and
        verify the endpoint returns the correct enqueued count.
        """
        data = _seed_meta_org(db_session, "SyncNow Org", "syncnow", "syncnow@test.com")

        # Create mock ScheduledJob objects to return from enqueue_if_missing
        mock_jobs = [
            ScheduledJob(
                id=uuid4(), org_id=data["org_id"],
                job_type=jt.value,
                reference_id=data["meta_ad_account_id"],
                scheduled_for=datetime.utcnow(),
                created_at=datetime.utcnow(),
            )
            for jt in SyncJobType
        ]

        with patch(
            "backend.src.services.meta_job_scheduler.MetaJobScheduler"
        ) as MockSchedulerClass:
            mock_scheduler = MagicMock()
            mock_scheduler.enqueue_if_missing.return_value = mock_jobs
            MockSchedulerClass.return_value = mock_scheduler

            client = TestClient(app)
            resp = client.post(
                "/api/meta/sync/now",
                headers=_auth(data["token"]),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["accounts"] == 1
        assert body["message"].startswith("Enqueued")
        # 4 job types were returned by mock
        assert "4" in body["message"]

    def test_sync_now_blocked_for_canceled_subscription(self, db_session, override_db):
        """POST /api/meta/sync/now returns 403 when subscription is canceled."""
        org_id = uuid4()
        org = Organization(
            id=org_id, name="Canceled Org", slug="canceled-sync",
            operator_armed=True, created_at=datetime.utcnow(),
        )
        db_session.add(org)

        user_id = uuid4()
        user = User(
            id=user_id, email="canceled-sync@test.com", name="Canceled User",
            password_hash=hash_password("TestPass123"),
            created_at=datetime.utcnow(),
        )
        db_session.add(user)

        role = UserOrgRole(
            id=uuid4(), user_id=user_id, org_id=org_id,
            role=RoleEnum.ADMIN, assigned_at=datetime.utcnow(),
        )
        db_session.add(role)

        sub = Subscription(
            id=uuid4(), org_id=org_id,
            plan=PlanEnum.PRO,
            status=SubscriptionStatusEnum.CANCELED,
            created_at=datetime.utcnow(),
        )
        db_session.add(sub)
        db_session.commit()

        token = create_access_token(
            user_id=str(user_id), email="canceled-sync@test.com",
            role="admin", org_id=str(org_id),
        )

        client = TestClient(app)
        resp = client.post(
            "/api/meta/sync/now",
            headers=_auth(token),
        )

        assert resp.status_code == 403
        assert "inactive" in resp.json()["detail"].lower() or "disabled" in resp.json()["detail"].lower()


# ── Test 3: GET /api/meta/campaigns ──────────────────────────────────────────


class TestListCampaigns:

    def test_campaigns_returns_all_for_org(self, db_session, override_db):
        """GET /api/meta/campaigns returns all campaigns belonging to the org."""
        data = _seed_meta_org(db_session, "Campaigns Org", "campaigns", "campaigns@test.com")

        client = TestClient(app)
        resp = client.get(
            "/api/meta/campaigns",
            headers=_auth(data["token"]),
        )

        assert resp.status_code == 200
        campaigns = resp.json()
        assert isinstance(campaigns, list)
        assert len(campaigns) == 2

        # Verify fields present
        names = {c["name"] for c in campaigns}
        assert "Campaigns Org Sales Campaign" in names
        assert "Campaigns Org Brand Awareness" in names

        for c in campaigns:
            assert "id" in c
            assert "meta_campaign_id" in c
            assert "objective" in c
            assert "status" in c
            assert "effective_status" in c

    def test_campaigns_filter_by_status(self, db_session, override_db):
        """GET /api/meta/campaigns?status=ACTIVE returns only active campaigns."""
        data = _seed_meta_org(db_session, "CampFilter Org", "campfilter", "campfilter@test.com")

        client = TestClient(app)
        resp = client.get(
            "/api/meta/campaigns?status=ACTIVE",
            headers=_auth(data["token"]),
        )

        assert resp.status_code == 200
        campaigns = resp.json()
        assert len(campaigns) == 1
        assert campaigns[0]["effective_status"] == "ACTIVE"
        assert campaigns[0]["name"] == "CampFilter Org Sales Campaign"

    def test_campaigns_search_by_name(self, db_session, override_db):
        """GET /api/meta/campaigns?search=Brand returns campaigns matching the name."""
        data = _seed_meta_org(db_session, "CampSearch Org", "campsearch", "campsearch@test.com")

        client = TestClient(app)
        resp = client.get(
            "/api/meta/campaigns?search=Brand",
            headers=_auth(data["token"]),
        )

        assert resp.status_code == 200
        campaigns = resp.json()
        assert len(campaigns) == 1
        assert "Brand" in campaigns[0]["name"]


# ── Test 4: GET /api/meta/alerts ─────────────────────────────────────────────


class TestListAlerts:

    def test_alerts_returns_active_only(self, db_session, override_db):
        """GET /api/meta/alerts returns only unresolved alerts (resolved_at is None)."""
        data = _seed_meta_org(db_session, "Alerts Org", "alerts", "alerts@test.com")

        client = TestClient(app)
        resp = client.get(
            "/api/meta/alerts",
            headers=_auth(data["token"]),
        )

        assert resp.status_code == 200
        alerts = resp.json()
        assert isinstance(alerts, list)
        # We seeded 2 active + 1 resolved; only 2 should be returned
        assert len(alerts) == 2

        for a in alerts:
            assert "id" in a
            assert "alert_type" in a
            assert "severity" in a
            assert "message" in a
            assert "detected_at" in a
            assert a["resolved_at"] is None

        alert_types = {a["alert_type"] for a in alerts}
        assert "ctr_low" in alert_types
        assert "spend_spike_no_conv" in alert_types

    def test_alerts_filter_by_severity(self, db_session, override_db):
        """GET /api/meta/alerts?severity=critical returns only critical alerts."""
        data = _seed_meta_org(db_session, "AlertSev Org", "alertsev", "alertsev@test.com")

        client = TestClient(app)
        resp = client.get(
            "/api/meta/alerts?severity=critical",
            headers=_auth(data["token"]),
        )

        assert resp.status_code == 200
        alerts = resp.json()
        assert len(alerts) == 1
        assert alerts[0]["severity"] == "critical"
        assert alerts[0]["alert_type"] == "spend_spike_no_conv"

    def test_alerts_payload_included(self, db_session, override_db):
        """GET /api/meta/alerts includes payload data in the response."""
        data = _seed_meta_org(db_session, "AlertPayload Org", "alertpayload", "alertpayload@test.com")

        client = TestClient(app)
        resp = client.get(
            "/api/meta/alerts",
            headers=_auth(data["token"]),
        )

        assert resp.status_code == 200
        alerts = resp.json()

        # Find the ctr_low alert
        ctr_alert = next(a for a in alerts if a["alert_type"] == "ctr_low")
        assert ctr_alert["payload"] is not None
        assert ctr_alert["payload"]["current_ctr"] == 0.8
        assert ctr_alert["payload"]["threshold"] == 1.0


# ── Test 5: GET /api/meta/insights ───────────────────────────────────────────


class TestListInsights:

    def test_insights_filtered_by_level_campaign(self, db_session, override_db):
        """GET /api/meta/insights?level=campaign returns only campaign-level insights."""
        data = _seed_meta_org(db_session, "Insights Org", "insights", "insights@test.com")

        client = TestClient(app)
        resp = client.get(
            "/api/meta/insights?level=campaign",
            headers=_auth(data["token"]),
        )

        assert resp.status_code == 200
        insights = resp.json()
        assert isinstance(insights, list)
        assert len(insights) == 1

        row = insights[0]
        assert row["level"] == "campaign"
        assert row["entity_meta_id"] == "camp_insights_001"
        assert row["spend"] == 120.50
        assert row["impressions"] == 5000
        assert row["clicks"] == 250
        assert row["conversions"] == 12
        assert row["purchase_roas"] == 3.2
        assert row["date_start"] == "2026-02-15"

    def test_insights_filtered_by_level_adset(self, db_session, override_db):
        """GET /api/meta/insights?level=adset returns only adset-level insights."""
        data = _seed_meta_org(db_session, "InsAdset Org", "insadset", "insadset@test.com")

        client = TestClient(app)
        resp = client.get(
            "/api/meta/insights?level=adset",
            headers=_auth(data["token"]),
        )

        assert resp.status_code == 200
        insights = resp.json()
        assert len(insights) == 1
        assert insights[0]["level"] == "adset"
        assert insights[0]["entity_meta_id"] == "adset_insadset_001"
        assert insights[0]["spend"] == 60.25

    def test_insights_empty_for_ad_level(self, db_session, override_db):
        """GET /api/meta/insights?level=ad returns empty when no ad-level data seeded."""
        data = _seed_meta_org(db_session, "InsAd Org", "insad", "insad@test.com")

        client = TestClient(app)
        resp = client.get(
            "/api/meta/insights?level=ad",
            headers=_auth(data["token"]),
        )

        assert resp.status_code == 200
        insights = resp.json()
        assert len(insights) == 0

    def test_insights_filter_by_entity_id(self, db_session, override_db):
        """GET /api/meta/insights?level=campaign&entity_id=... returns only matching entity."""
        data = _seed_meta_org(db_session, "InsEntity Org", "insentity", "insentity@test.com")

        client = TestClient(app)
        resp = client.get(
            "/api/meta/insights?level=campaign&entity_id=camp_insentity_001",
            headers=_auth(data["token"]),
        )

        assert resp.status_code == 200
        insights = resp.json()
        assert len(insights) == 1
        assert insights[0]["entity_meta_id"] == "camp_insentity_001"

        # Non-existent entity returns empty
        resp2 = client.get(
            "/api/meta/insights?level=campaign&entity_id=nonexistent",
            headers=_auth(data["token"]),
        )
        assert resp2.status_code == 200
        assert len(resp2.json()) == 0


# ── Test 6: Multi-tenant isolation ───────────────────────────────────────────


class TestMultiTenantIsolation:

    def test_org_a_data_invisible_to_org_b(self, db_session, override_db):
        """Org A's campaigns, insights, and alerts are invisible to Org B."""
        data_a = _seed_meta_org(db_session, "Iso Org A", "iso-a", "iso-a@test.com")
        data_b = _seed_meta_org(db_session, "Iso Org B", "iso-b", "iso-b@test.com")

        client = TestClient(app)

        # Org A sees its own campaigns
        resp_a_camp = client.get("/api/meta/campaigns", headers=_auth(data_a["token"]))
        assert resp_a_camp.status_code == 200
        names_a = {c["name"] for c in resp_a_camp.json()}
        assert "Iso Org A Sales Campaign" in names_a

        # Org B sees its own campaigns (not Org A's)
        resp_b_camp = client.get("/api/meta/campaigns", headers=_auth(data_b["token"]))
        assert resp_b_camp.status_code == 200
        names_b = {c["name"] for c in resp_b_camp.json()}
        assert "Iso Org B Sales Campaign" in names_b
        assert "Iso Org A Sales Campaign" not in names_b

        # Org A sees its own alerts
        resp_a_alerts = client.get("/api/meta/alerts", headers=_auth(data_a["token"]))
        assert resp_a_alerts.status_code == 200
        a_alert_entities = {a["entity_meta_id"] for a in resp_a_alerts.json()}
        assert "camp_iso-a_001" in a_alert_entities

        # Org B sees its own alerts (not Org A's)
        resp_b_alerts = client.get("/api/meta/alerts", headers=_auth(data_b["token"]))
        assert resp_b_alerts.status_code == 200
        b_alert_entities = {a["entity_meta_id"] for a in resp_b_alerts.json()}
        assert "camp_iso-b_001" in b_alert_entities
        assert "camp_iso-a_001" not in b_alert_entities

        # Org A insights isolated from Org B
        resp_a_ins = client.get(
            "/api/meta/insights?level=campaign", headers=_auth(data_a["token"]),
        )
        resp_b_ins = client.get(
            "/api/meta/insights?level=campaign", headers=_auth(data_b["token"]),
        )
        assert resp_a_ins.status_code == 200
        assert resp_b_ins.status_code == 200
        a_entities = {i["entity_meta_id"] for i in resp_a_ins.json()}
        b_entities = {i["entity_meta_id"] for i in resp_b_ins.json()}
        assert a_entities & b_entities == set()  # No overlap


# ── Test 7: Unauthenticated access blocked ───────────────────────────────────


class TestUnauthenticatedAccess:

    def test_no_token_returns_401_or_403(self, db_session, override_db):
        """All Meta sync endpoints reject requests without a valid JWT."""
        _seed_meta_org(db_session, "NoAuth Org", "noauth", "noauth@test.com")

        client = TestClient(app)
        endpoints = [
            ("GET", "/api/meta/sync/status"),
            ("POST", "/api/meta/sync/now"),
            ("GET", "/api/meta/campaigns"),
            ("GET", "/api/meta/alerts"),
            ("GET", "/api/meta/insights?level=campaign"),
        ]

        for method, url in endpoints:
            if method == "GET":
                resp = client.get(url)
            else:
                resp = client.post(url)

            # Should be 401 (missing token) or 403 (forbidden)
            assert resp.status_code in (401, 403), (
                f"{method} {url} returned {resp.status_code}, expected 401/403"
            )
