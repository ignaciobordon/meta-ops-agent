"""
Sprint 6 – Tests for MetaSyncService.sync_assets()
Covers campaign/adset/ad creation, upsert logic, orphan handling,
sync-run recording, token-expired failures, and returned counts.
"""
import pytest
from uuid import uuid4
from datetime import datetime
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)  # BEFORE model imports

from backend.src.database.models import (
    Base,
    Organization,
    MetaConnection,
    MetaAdAccount,
    MetaCampaign,
    MetaAdset,
    MetaAd,
    MetaSyncRun,
    SyncRunStatus,
)
from backend.src.services.meta_sync_service import MetaSyncService
from backend.src.services.meta_api_client import MetaTokenExpiredError


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


def _seed(db_session):
    """
    Seed the minimal entity graph required by sync_assets:
    Organization -> MetaConnection (status=active) -> MetaAdAccount.
    Returns dict with org_id, connection_id, ad_account_id, meta_account_id.
    """
    org_id = uuid4()
    org = Organization(
        id=org_id,
        name="Test Org",
        slug=f"test-org-{uuid4().hex[:6]}",
        created_at=datetime.utcnow(),
    )
    db_session.add(org)

    conn_id = uuid4()
    conn = MetaConnection(
        id=conn_id,
        org_id=org_id,
        access_token_encrypted="enc_test_token",
        status="active",
        connected_at=datetime.utcnow(),
    )
    db_session.add(conn)

    ad_account_id = uuid4()
    meta_account_id = f"act_{uuid4().hex[:8]}"
    ad_account = MetaAdAccount(
        id=ad_account_id,
        org_id=org_id,
        meta_account_id=meta_account_id,
        name="Test Ad Account",
        currency="USD",
        created_at=datetime.utcnow(),
    )
    db_session.add(ad_account)
    db_session.commit()

    return {
        "org_id": org_id,
        "connection_id": conn_id,
        "ad_account_id": ad_account_id,
        "meta_account_id": meta_account_id,
    }


# ── Helpers: raw Meta API-style payloads ─────────────────────────────────────


def _raw_campaigns(count=2):
    """Return list of raw campaign dicts as the Meta API would return them."""
    return [
        {
            "id": f"camp_{i+1}",
            "name": f"Campaign {i+1}",
            "objective": "CONVERSIONS",
            "status": "ACTIVE",
            "effective_status": "ACTIVE",
            "daily_budget": "500",
            "lifetime_budget": None,
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "created_time": "2025-06-01T10:00:00+0000",
            "updated_time": "2025-06-05T12:00:00+0000",
        }
        for i in range(count)
    ]


def _raw_adsets(campaign_ids=None, count=2):
    """Return list of raw adset dicts. Each links to a campaign_id."""
    if campaign_ids is None:
        campaign_ids = ["camp_1"]
    return [
        {
            "id": f"adset_{i+1}",
            "campaign_id": campaign_ids[i % len(campaign_ids)],
            "name": f"Adset {i+1}",
            "status": "ACTIVE",
            "effective_status": "ACTIVE",
            "daily_budget": "200",
            "lifetime_budget": None,
            "optimization_goal": "OFFSITE_CONVERSIONS",
            "billing_event": "IMPRESSIONS",
            "start_time": "2025-06-01T00:00:00+0000",
            "end_time": None,
        }
        for i in range(count)
    ]


def _raw_ads(adset_ids=None, count=2):
    """Return list of raw ad dicts. Each links to an adset_id."""
    if adset_ids is None:
        adset_ids = ["adset_1"]
    return [
        {
            "id": f"ad_{i+1}",
            "adset_id": adset_ids[i % len(adset_ids)],
            "name": f"Ad {i+1}",
            "status": "ACTIVE",
            "effective_status": "ACTIVE",
            "creative": {"id": f"creative_{i+1}"},
        }
        for i in range(count)
    ]


# ── Tests ────────────────────────────────────────────────────────────────────


class TestSyncAssetsCreatesCampaigns:
    """1. sync_assets creates campaigns from API response."""

    def test_campaigns_are_created(self, db_session):
        data = _seed(db_session)
        svc = MetaSyncService(db=db_session)

        with patch.object(svc, "_get_client") as mock_gc:
            client = MagicMock()
            client.get_campaigns.return_value = _raw_campaigns(count=3)
            client.get_adsets.return_value = []
            client.get_ads.return_value = []
            mock_gc.return_value = client

            result = svc.sync_assets(data["org_id"], data["ad_account_id"])

        assert result["status"] == "success"
        campaigns = db_session.query(MetaCampaign).filter(
            MetaCampaign.org_id == data["org_id"],
        ).all()
        assert len(campaigns) == 3
        names = {c.name for c in campaigns}
        assert "Campaign 1" in names
        assert "Campaign 3" in names


class TestSyncAssetsCreatesAdsets:
    """2. sync_assets creates adsets linked to campaigns."""

    def test_adsets_linked_to_campaigns(self, db_session):
        data = _seed(db_session)
        svc = MetaSyncService(db=db_session)

        campaigns_raw = _raw_campaigns(count=1)  # camp_1
        adsets_raw = _raw_adsets(campaign_ids=["camp_1"], count=2)

        with patch.object(svc, "_get_client") as mock_gc:
            client = MagicMock()
            client.get_campaigns.return_value = campaigns_raw
            client.get_adsets.return_value = adsets_raw
            client.get_ads.return_value = []
            mock_gc.return_value = client

            svc.sync_assets(data["org_id"], data["ad_account_id"])

        adsets = db_session.query(MetaAdset).filter(
            MetaAdset.org_id == data["org_id"],
        ).all()
        assert len(adsets) == 2

        # Each adset must reference the campaign row
        campaign = db_session.query(MetaCampaign).filter(
            MetaCampaign.meta_campaign_id == "camp_1",
        ).first()
        for adset in adsets:
            assert adset.campaign_id == campaign.id


class TestSyncAssetsCreatesAds:
    """3. sync_assets creates ads linked to adsets."""

    def test_ads_linked_to_adsets(self, db_session):
        data = _seed(db_session)
        svc = MetaSyncService(db=db_session)

        campaigns_raw = _raw_campaigns(count=1)
        adsets_raw = _raw_adsets(campaign_ids=["camp_1"], count=1)
        ads_raw = _raw_ads(adset_ids=["adset_1"], count=3)

        with patch.object(svc, "_get_client") as mock_gc:
            client = MagicMock()
            client.get_campaigns.return_value = campaigns_raw
            client.get_adsets.return_value = adsets_raw
            client.get_ads.return_value = ads_raw
            mock_gc.return_value = client

            svc.sync_assets(data["org_id"], data["ad_account_id"])

        ads = db_session.query(MetaAd).filter(
            MetaAd.org_id == data["org_id"],
        ).all()
        assert len(ads) == 3

        adset = db_session.query(MetaAdset).filter(
            MetaAdset.meta_adset_id == "adset_1",
        ).first()
        for ad in ads:
            assert ad.adset_id == adset.id


class TestSyncAssetsUpsertsExistingCampaign:
    """4. sync_assets upserts (updates existing campaign on second run)."""

    def test_campaign_updated_on_second_sync(self, db_session):
        data = _seed(db_session)
        svc = MetaSyncService(db=db_session)

        # First run: campaign with original name
        campaigns_v1 = [
            {
                "id": "camp_upsert",
                "name": "Original Name",
                "objective": "CONVERSIONS",
                "status": "ACTIVE",
                "effective_status": "ACTIVE",
                "daily_budget": "500",
                "lifetime_budget": None,
                "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                "created_time": "2025-06-01T10:00:00+0000",
                "updated_time": "2025-06-05T12:00:00+0000",
            }
        ]

        with patch.object(svc, "_get_client") as mock_gc:
            client = MagicMock()
            client.get_campaigns.return_value = campaigns_v1
            client.get_adsets.return_value = []
            client.get_ads.return_value = []
            mock_gc.return_value = client
            svc.sync_assets(data["org_id"], data["ad_account_id"])

        campaign = db_session.query(MetaCampaign).filter(
            MetaCampaign.meta_campaign_id == "camp_upsert",
        ).first()
        assert campaign.name == "Original Name"
        original_id = campaign.id

        # Second run: same campaign, updated name and budget
        campaigns_v2 = [
            {
                "id": "camp_upsert",
                "name": "Updated Name",
                "objective": "CONVERSIONS",
                "status": "PAUSED",
                "effective_status": "PAUSED",
                "daily_budget": "800",
                "lifetime_budget": None,
                "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                "created_time": "2025-06-01T10:00:00+0000",
                "updated_time": "2025-06-10T12:00:00+0000",
            }
        ]

        with patch.object(svc, "_get_client") as mock_gc:
            client = MagicMock()
            client.get_campaigns.return_value = campaigns_v2
            client.get_adsets.return_value = []
            client.get_ads.return_value = []
            mock_gc.return_value = client
            svc.sync_assets(data["org_id"], data["ad_account_id"])

        db_session.expire_all()
        campaign = db_session.query(MetaCampaign).filter(
            MetaCampaign.meta_campaign_id == "camp_upsert",
        ).first()

        # Same row, not duplicated
        assert campaign.id == original_id
        # Fields updated
        assert campaign.name == "Updated Name"
        assert campaign.status == "PAUSED"
        assert campaign.daily_budget == 800.0

        # Only one campaign with this meta_campaign_id
        total = db_session.query(MetaCampaign).filter(
            MetaCampaign.meta_campaign_id == "camp_upsert",
        ).count()
        assert total == 1


class TestSyncAssetsOrphanAdsets:
    """5. sync_assets handles orphan adsets (missing campaign) gracefully."""

    def test_orphan_adsets_skipped_without_crash(self, db_session):
        data = _seed(db_session)
        svc = MetaSyncService(db=db_session)

        campaigns_raw = _raw_campaigns(count=1)  # camp_1
        # adset references a campaign that does NOT exist in campaigns_raw
        orphan_adsets = [
            {
                "id": "adset_orphan_1",
                "campaign_id": "camp_nonexistent",
                "name": "Orphan Adset",
                "status": "ACTIVE",
                "effective_status": "ACTIVE",
                "daily_budget": "100",
                "lifetime_budget": None,
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "billing_event": "IMPRESSIONS",
                "start_time": None,
                "end_time": None,
            }
        ]

        with patch.object(svc, "_get_client") as mock_gc:
            client = MagicMock()
            client.get_campaigns.return_value = campaigns_raw
            client.get_adsets.return_value = orphan_adsets
            client.get_ads.return_value = []
            mock_gc.return_value = client

            result = svc.sync_assets(data["org_id"], data["ad_account_id"])

        # Orphan adset is NOT inserted
        adsets = db_session.query(MetaAdset).filter(
            MetaAdset.org_id == data["org_id"],
        ).all()
        assert len(adsets) == 0

        # Error recorded but sync did not crash -- status is partial
        assert result["status"] == "partial"
        assert result["error_count"] == 1


class TestSyncAssetsOrphanAds:
    """6. sync_assets handles orphan ads (missing adset) gracefully."""

    def test_orphan_ads_skipped_without_crash(self, db_session):
        data = _seed(db_session)
        svc = MetaSyncService(db=db_session)

        campaigns_raw = _raw_campaigns(count=1)
        adsets_raw = _raw_adsets(campaign_ids=["camp_1"], count=1)  # adset_1
        # ad references an adset that does NOT exist in adsets_raw
        orphan_ads = [
            {
                "id": "ad_orphan_1",
                "adset_id": "adset_nonexistent",
                "name": "Orphan Ad",
                "status": "ACTIVE",
                "effective_status": "ACTIVE",
                "creative": {"id": "creative_orphan"},
            }
        ]

        with patch.object(svc, "_get_client") as mock_gc:
            client = MagicMock()
            client.get_campaigns.return_value = campaigns_raw
            client.get_adsets.return_value = adsets_raw
            client.get_ads.return_value = orphan_ads
            mock_gc.return_value = client

            result = svc.sync_assets(data["org_id"], data["ad_account_id"])

        ads = db_session.query(MetaAd).filter(
            MetaAd.org_id == data["org_id"],
        ).all()
        assert len(ads) == 0

        assert result["status"] == "partial"
        assert result["error_count"] == 1


class TestSyncAssetsRecordsSyncRunOnSuccess:
    """7. sync_assets records MetaSyncRun on success."""

    def test_sync_run_recorded_with_success(self, db_session):
        data = _seed(db_session)
        svc = MetaSyncService(db=db_session)

        with patch.object(svc, "_get_client") as mock_gc:
            client = MagicMock()
            client.get_campaigns.return_value = _raw_campaigns(count=2)
            client.get_adsets.return_value = []
            client.get_ads.return_value = []
            mock_gc.return_value = client

            svc.sync_assets(data["org_id"], data["ad_account_id"])

        runs = db_session.query(MetaSyncRun).filter(
            MetaSyncRun.org_id == data["org_id"],
            MetaSyncRun.job_type == "assets",
        ).all()
        assert len(runs) == 1

        run = runs[0]
        assert run.status == SyncRunStatus.SUCCESS
        assert run.ad_account_id == data["ad_account_id"]
        assert run.items_upserted == 2
        assert run.error_count == 0
        assert run.started_at is not None
        assert run.finished_at is not None
        assert run.duration_ms is not None
        assert run.duration_ms >= 0


class TestSyncAssetsRecordsSyncRunOnTokenExpired:
    """8. sync_assets records MetaSyncRun with FAILED on token expired."""

    def test_sync_run_failed_on_token_expired(self, db_session):
        data = _seed(db_session)
        svc = MetaSyncService(db=db_session)

        with patch.object(svc, "_get_client") as mock_gc:
            client = MagicMock()
            client.get_campaigns.side_effect = MetaTokenExpiredError("Token expired")
            mock_gc.return_value = client

            result = svc.sync_assets(data["org_id"], data["ad_account_id"])

        assert result["status"] == "failed"
        assert "Token expired" in result["message"]

        runs = db_session.query(MetaSyncRun).filter(
            MetaSyncRun.org_id == data["org_id"],
            MetaSyncRun.job_type == "assets",
        ).all()
        assert len(runs) == 1

        run = runs[0]
        assert run.status == SyncRunStatus.FAILED
        assert run.error_count == 1
        assert run.error_summary_json is not None
        assert "Token expired" in run.error_summary_json


class TestSyncAssetsUpdatesLastSyncedAt:
    """9. sync_assets updates MetaAdAccount.last_synced_at."""

    def test_last_synced_at_updated(self, db_session):
        data = _seed(db_session)

        # Verify it starts as None
        account_before = db_session.query(MetaAdAccount).filter(
            MetaAdAccount.id == data["ad_account_id"],
        ).first()
        assert account_before.last_synced_at is None

        svc = MetaSyncService(db=db_session)

        with patch.object(svc, "_get_client") as mock_gc:
            client = MagicMock()
            client.get_campaigns.return_value = _raw_campaigns(count=1)
            client.get_adsets.return_value = []
            client.get_ads.return_value = []
            mock_gc.return_value = client

            svc.sync_assets(data["org_id"], data["ad_account_id"])

        db_session.expire_all()
        account_after = db_session.query(MetaAdAccount).filter(
            MetaAdAccount.id == data["ad_account_id"],
        ).first()
        assert account_after.last_synced_at is not None
        # Sanity check: timestamp is recent (within last 60 seconds)
        delta = (datetime.utcnow() - account_after.last_synced_at).total_seconds()
        assert delta < 60


class TestSyncAssetsReturnsCorrectCounts:
    """10. sync_assets returns correct counts (items_upserted, error_count)."""

    def test_counts_reflect_all_asset_types(self, db_session):
        data = _seed(db_session)
        svc = MetaSyncService(db=db_session)

        # 2 campaigns + 2 adsets (both linked to camp_1) + 3 ads (all linked to adset_1)
        campaigns_raw = _raw_campaigns(count=2)
        adsets_raw = _raw_adsets(campaign_ids=["camp_1"], count=2)
        ads_raw = _raw_ads(adset_ids=["adset_1"], count=3)

        with patch.object(svc, "_get_client") as mock_gc:
            client = MagicMock()
            client.get_campaigns.return_value = campaigns_raw
            client.get_adsets.return_value = adsets_raw
            client.get_ads.return_value = ads_raw
            mock_gc.return_value = client

            result = svc.sync_assets(data["org_id"], data["ad_account_id"])

        assert result["items_upserted"] == 2 + 2 + 3  # 7 total
        assert result["error_count"] == 0
        assert result["status"] == "success"

    def test_counts_include_orphan_errors(self, db_session):
        data = _seed(db_session)
        svc = MetaSyncService(db=db_session)

        campaigns_raw = _raw_campaigns(count=1)  # camp_1
        # 1 valid adset + 1 orphan adset
        adsets_raw = [
            {
                "id": "adset_valid",
                "campaign_id": "camp_1",
                "name": "Valid Adset",
                "status": "ACTIVE",
                "effective_status": "ACTIVE",
                "daily_budget": "200",
                "lifetime_budget": None,
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "billing_event": "IMPRESSIONS",
                "start_time": None,
                "end_time": None,
            },
            {
                "id": "adset_orphan",
                "campaign_id": "camp_ghost",
                "name": "Orphan Adset",
                "status": "ACTIVE",
                "effective_status": "ACTIVE",
                "daily_budget": "100",
                "lifetime_budget": None,
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "billing_event": "IMPRESSIONS",
                "start_time": None,
                "end_time": None,
            },
        ]
        # 1 valid ad + 1 orphan ad
        ads_raw = [
            {
                "id": "ad_valid",
                "adset_id": "adset_valid",
                "name": "Valid Ad",
                "status": "ACTIVE",
                "effective_status": "ACTIVE",
                "creative": {"id": "creative_1"},
            },
            {
                "id": "ad_orphan",
                "adset_id": "adset_missing",
                "name": "Orphan Ad",
                "status": "ACTIVE",
                "effective_status": "ACTIVE",
                "creative": {"id": "creative_2"},
            },
        ]

        with patch.object(svc, "_get_client") as mock_gc:
            client = MagicMock()
            client.get_campaigns.return_value = campaigns_raw
            client.get_adsets.return_value = adsets_raw
            client.get_ads.return_value = ads_raw
            mock_gc.return_value = client

            result = svc.sync_assets(data["org_id"], data["ad_account_id"])

        # 1 campaign + 1 valid adset + 1 valid ad = 3 upserted
        assert result["items_upserted"] == 3
        # 1 orphan adset + 1 orphan ad = 2 errors
        assert result["error_count"] == 2
        assert result["status"] == "partial"


class TestSyncAssetsUpsertAdsetOnSecondRun:
    """11. sync_assets upserts (updates existing adset on second run)."""

    def test_adset_updated_on_second_sync(self, db_session):
        data = _seed(db_session)
        svc = MetaSyncService(db=db_session)

        campaigns_raw = _raw_campaigns(count=1)
        adsets_v1 = [
            {
                "id": "adset_upsert",
                "campaign_id": "camp_1",
                "name": "Adset Original",
                "status": "ACTIVE",
                "effective_status": "ACTIVE",
                "daily_budget": "200",
                "lifetime_budget": None,
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "billing_event": "IMPRESSIONS",
                "start_time": None,
                "end_time": None,
            }
        ]

        with patch.object(svc, "_get_client") as mock_gc:
            client = MagicMock()
            client.get_campaigns.return_value = campaigns_raw
            client.get_adsets.return_value = adsets_v1
            client.get_ads.return_value = []
            mock_gc.return_value = client
            svc.sync_assets(data["org_id"], data["ad_account_id"])

        adset = db_session.query(MetaAdset).filter(
            MetaAdset.meta_adset_id == "adset_upsert",
        ).first()
        assert adset.name == "Adset Original"
        original_id = adset.id

        adsets_v2 = [
            {
                "id": "adset_upsert",
                "campaign_id": "camp_1",
                "name": "Adset Renamed",
                "status": "PAUSED",
                "effective_status": "PAUSED",
                "daily_budget": "300",
                "lifetime_budget": None,
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "billing_event": "IMPRESSIONS",
                "start_time": None,
                "end_time": None,
            }
        ]

        with patch.object(svc, "_get_client") as mock_gc:
            client = MagicMock()
            client.get_campaigns.return_value = campaigns_raw
            client.get_adsets.return_value = adsets_v2
            client.get_ads.return_value = []
            mock_gc.return_value = client
            svc.sync_assets(data["org_id"], data["ad_account_id"])

        db_session.expire_all()
        adset = db_session.query(MetaAdset).filter(
            MetaAdset.meta_adset_id == "adset_upsert",
        ).first()
        assert adset.id == original_id
        assert adset.name == "Adset Renamed"
        assert adset.status == "PAUSED"
        assert adset.daily_budget == 300.0


class TestSyncAssetsNoConnectionReturnsError:
    """12. sync_assets returns error when no active connection exists."""

    def test_returns_error_without_active_connection(self, db_session):
        org_id = uuid4()
        org = Organization(
            id=org_id,
            name="No-Conn Org",
            slug=f"no-conn-{uuid4().hex[:6]}",
            created_at=datetime.utcnow(),
        )
        db_session.add(org)

        # Connection with status=expired (not active)
        conn = MetaConnection(
            id=uuid4(),
            org_id=org_id,
            access_token_encrypted="enc_token",
            status="expired",
            connected_at=datetime.utcnow(),
        )
        db_session.add(conn)

        ad_account_id = uuid4()
        ad_account = MetaAdAccount(
            id=ad_account_id,
            org_id=org_id,
            meta_account_id="act_noconn",
            name="No Conn Account",
            created_at=datetime.utcnow(),
        )
        db_session.add(ad_account)
        db_session.commit()

        svc = MetaSyncService(db=db_session)
        result = svc.sync_assets(org_id, ad_account_id)

        assert result["status"] == "error"
        assert "No active Meta connection" in result["message"]


class TestSyncAssetsFullHierarchy:
    """13. sync_assets creates the full campaign -> adset -> ad hierarchy in one pass."""

    def test_full_hierarchy_created(self, db_session):
        data = _seed(db_session)
        svc = MetaSyncService(db=db_session)

        campaigns_raw = _raw_campaigns(count=2)   # camp_1, camp_2
        adsets_raw = _raw_adsets(campaign_ids=["camp_1", "camp_2"], count=4)  # adset_1..4
        ads_raw = _raw_ads(adset_ids=["adset_1", "adset_2", "adset_3", "adset_4"], count=4)

        with patch.object(svc, "_get_client") as mock_gc:
            client = MagicMock()
            client.get_campaigns.return_value = campaigns_raw
            client.get_adsets.return_value = adsets_raw
            client.get_ads.return_value = ads_raw
            mock_gc.return_value = client

            result = svc.sync_assets(data["org_id"], data["ad_account_id"])

        assert result["status"] == "success"
        assert result["items_upserted"] == 2 + 4 + 4  # 10

        # Verify FK chain: ad -> adset -> campaign
        ad = db_session.query(MetaAd).filter(MetaAd.meta_ad_id == "ad_1").first()
        adset = db_session.query(MetaAdset).filter(MetaAdset.id == ad.adset_id).first()
        campaign = db_session.query(MetaCampaign).filter(MetaCampaign.id == adset.campaign_id).first()
        assert campaign is not None
        assert campaign.org_id == data["org_id"]
