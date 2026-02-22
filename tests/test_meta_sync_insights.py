"""
Tests for MetaSyncService.sync_insights().
Covers row creation, date mapping, upserts, multi-level sync,
MetaSyncRun recording, empty responses, partial failures,
unique constraints, conversions/ROAS mapping, and error counts.
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
    MetaInsightsDaily,
    MetaSyncRun,
    InsightLevel,
    SyncRunStatus,
)
from backend.src.services.meta_sync_service import MetaSyncService


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
def seed_data(db_session):
    """Seed an Organization, active MetaConnection, and MetaAdAccount."""
    org_id = uuid4()
    org = Organization(
        id=org_id,
        name="Insights Test Org",
        slug="insights-test-org",
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
    ad_account = MetaAdAccount(
        id=ad_account_id,
        org_id=org_id,
        meta_account_id="act_test_001",
        name="Test Ad Account",
        currency="USD",
        created_at=datetime.utcnow(),
    )
    db_session.add(ad_account)
    db_session.commit()

    return {
        "org_id": org_id,
        "conn_id": conn_id,
        "ad_account_id": ad_account_id,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_insight_row(
    campaign_id="camp_001",
    date_start="2025-06-01",
    date_stop="2025-06-01",
    spend="50.25",
    impressions="1200",
    clicks="30",
    ctr="2.5",
    cpm="41.88",
    cpc="1.68",
    frequency="1.3",
    actions=None,
    conversions=None,
    purchase_roas=None,
    level="campaign",
):
    """Build a raw insights row as the Meta API would return it."""
    row = {
        "date_start": date_start,
        "date_stop": date_stop,
        "spend": spend,
        "impressions": impressions,
        "clicks": clicks,
        "ctr": ctr,
        "cpm": cpm,
        "cpc": cpc,
        "frequency": frequency,
    }
    # Set entity id key based on level
    if level == "campaign":
        row["campaign_id"] = campaign_id
    elif level == "adset":
        row["adset_id"] = campaign_id  # reuse param name for simplicity
    elif level == "ad":
        row["ad_id"] = campaign_id
    if actions is not None:
        row["actions"] = actions
    if conversions is not None:
        row["conversions"] = conversions
    if purchase_roas is not None:
        row["purchase_roas"] = purchase_roas
    return row


def _patch_get_insights(return_values_by_level):
    """
    Patch MetaApiClient.get_insights to return per-level data.
    return_values_by_level: dict mapping level str -> list of row dicts.
    If a level maps to an Exception, it will be raised.
    """
    def side_effect(ad_account_meta_id, level, time_range):
        val = return_values_by_level.get(level, [])
        if isinstance(val, Exception):
            raise val
        return val
    return side_effect


# ── Test 1: sync_insights creates MetaInsightsDaily rows from API response ──


class TestSyncInsightsCreatesRows:

    def test_creates_insight_rows(self, db_session, seed_data):
        """sync_insights creates MetaInsightsDaily rows from API response."""
        api_rows = [
            _make_insight_row(campaign_id="camp_001", date_start="2025-06-01", date_stop="2025-06-01"),
            _make_insight_row(campaign_id="camp_002", date_start="2025-06-01", date_stop="2025-06-01", spend="75.00"),
        ]

        with patch("backend.src.services.meta_sync_service.MetaApiClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_insights.return_value = api_rows
            MockClient.return_value = mock_instance

            svc = MetaSyncService(db_session)
            result = svc.sync_insights(
                org_id=seed_data["org_id"],
                ad_account_id=seed_data["ad_account_id"],
                since="2025-06-01",
                until="2025-06-01",
                levels=["campaign"],
            )

        assert result["status"] == "success"
        assert result["items_upserted"] == 2

        rows = db_session.query(MetaInsightsDaily).filter(
            MetaInsightsDaily.org_id == seed_data["org_id"],
        ).all()
        assert len(rows) == 2

        entity_ids = {r.entity_meta_id for r in rows}
        assert entity_ids == {"camp_001", "camp_002"}
        assert all(r.spend is not None for r in rows)


# ── Test 2: sync_insights maps date_start / date_stop correctly ─────────────


class TestSyncInsightsDateMapping:

    def test_date_start_date_stop_mapped(self, db_session, seed_data):
        """sync_insights maps date_start and date_stop from the API row to datetime."""
        api_rows = [
            _make_insight_row(
                campaign_id="camp_dates",
                date_start="2025-07-15",
                date_stop="2025-07-15",
            ),
        ]

        with patch("backend.src.services.meta_sync_service.MetaApiClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_insights.return_value = api_rows
            MockClient.return_value = mock_instance

            svc = MetaSyncService(db_session)
            svc.sync_insights(
                org_id=seed_data["org_id"],
                ad_account_id=seed_data["ad_account_id"],
                since="2025-07-15",
                until="2025-07-15",
                levels=["campaign"],
            )

        row = db_session.query(MetaInsightsDaily).filter(
            MetaInsightsDaily.entity_meta_id == "camp_dates",
        ).first()

        assert row is not None
        assert row.date_start == datetime(2025, 7, 15, 0, 0, 0)
        assert row.date_stop == datetime(2025, 7, 15, 0, 0, 0)


# ── Test 3: sync_insights upserts (update on second run with same date) ─────


class TestSyncInsightsUpsert:

    def test_upserts_on_second_run(self, db_session, seed_data):
        """Running sync_insights twice with the same date+entity updates the row."""
        row_v1 = _make_insight_row(
            campaign_id="camp_upsert",
            date_start="2025-06-10",
            date_stop="2025-06-10",
            spend="100.00",
            clicks="50",
        )

        with patch("backend.src.services.meta_sync_service.MetaApiClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_insights.return_value = [row_v1]
            MockClient.return_value = mock_instance

            svc = MetaSyncService(db_session)
            svc.sync_insights(
                org_id=seed_data["org_id"],
                ad_account_id=seed_data["ad_account_id"],
                since="2025-06-10",
                until="2025-06-10",
                levels=["campaign"],
            )

        # First run: verify initial values
        insight = db_session.query(MetaInsightsDaily).filter(
            MetaInsightsDaily.entity_meta_id == "camp_upsert",
        ).first()
        assert insight is not None
        assert insight.spend == 100.0
        assert insight.clicks == 50

        # Second run: updated metrics
        row_v2 = _make_insight_row(
            campaign_id="camp_upsert",
            date_start="2025-06-10",
            date_stop="2025-06-10",
            spend="120.00",
            clicks="65",
        )

        with patch("backend.src.services.meta_sync_service.MetaApiClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_insights.return_value = [row_v2]
            MockClient.return_value = mock_instance

            svc = MetaSyncService(db_session)
            result = svc.sync_insights(
                org_id=seed_data["org_id"],
                ad_account_id=seed_data["ad_account_id"],
                since="2025-06-10",
                until="2025-06-10",
                levels=["campaign"],
            )

        assert result["items_upserted"] == 1

        db_session.expire_all()
        updated = db_session.query(MetaInsightsDaily).filter(
            MetaInsightsDaily.entity_meta_id == "camp_upsert",
        ).first()
        assert updated.spend == 120.0
        assert updated.clicks == 65

        # Only one row in DB (upsert, not duplicate)
        count = db_session.query(MetaInsightsDaily).filter(
            MetaInsightsDaily.entity_meta_id == "camp_upsert",
        ).count()
        assert count == 1


# ── Test 4: sync_insights handles multiple levels ───────────────────────────


class TestSyncInsightsMultipleLevels:

    def test_multiple_levels(self, db_session, seed_data):
        """sync_insights processes campaign, adset, and ad levels."""
        campaign_rows = [_make_insight_row(campaign_id="camp_L", level="campaign")]
        adset_rows = [_make_insight_row(campaign_id="adset_L", level="adset")]
        ad_rows = [_make_insight_row(campaign_id="ad_L", level="ad")]

        def side_effect(ad_account_meta_id, level, time_range):
            if level == "campaign":
                return campaign_rows
            elif level == "adset":
                return adset_rows
            elif level == "ad":
                return ad_rows
            return []

        with patch("backend.src.services.meta_sync_service.MetaApiClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_insights.side_effect = side_effect
            MockClient.return_value = mock_instance

            svc = MetaSyncService(db_session)
            result = svc.sync_insights(
                org_id=seed_data["org_id"],
                ad_account_id=seed_data["ad_account_id"],
                since="2025-06-01",
                until="2025-06-01",
                levels=["campaign", "adset", "ad"],
            )

        assert result["status"] == "success"
        assert result["items_upserted"] == 3

        levels_in_db = {
            r.level
            for r in db_session.query(MetaInsightsDaily).filter(
                MetaInsightsDaily.org_id == seed_data["org_id"],
            ).all()
        }
        assert InsightLevel.CAMPAIGN in levels_in_db
        assert InsightLevel.ADSET in levels_in_db
        assert InsightLevel.AD in levels_in_db


# ── Test 5: sync_insights records MetaSyncRun ───────────────────────────────


class TestSyncInsightsRecordsSyncRun:

    def test_records_sync_run(self, db_session, seed_data):
        """sync_insights creates a MetaSyncRun with job_type='insights'."""
        api_rows = [_make_insight_row(campaign_id="camp_run")]

        with patch("backend.src.services.meta_sync_service.MetaApiClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_insights.return_value = api_rows
            MockClient.return_value = mock_instance

            svc = MetaSyncService(db_session)
            svc.sync_insights(
                org_id=seed_data["org_id"],
                ad_account_id=seed_data["ad_account_id"],
                since="2025-06-01",
                until="2025-06-01",
                levels=["campaign"],
            )

        run = db_session.query(MetaSyncRun).filter(
            MetaSyncRun.org_id == seed_data["org_id"],
            MetaSyncRun.job_type == "insights",
        ).first()
        assert run is not None
        assert run.status == SyncRunStatus.SUCCESS
        assert run.items_upserted == 1
        assert run.error_count == 0
        assert run.started_at is not None
        assert run.finished_at is not None
        assert run.duration_ms >= 0
        assert run.ad_account_id == seed_data["ad_account_id"]


# ── Test 6: sync_insights handles empty API response ────────────────────────


class TestSyncInsightsEmptyResponse:

    def test_empty_api_response(self, db_session, seed_data):
        """sync_insights with empty API response records 0 items upserted."""
        with patch("backend.src.services.meta_sync_service.MetaApiClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_insights.return_value = []
            MockClient.return_value = mock_instance

            svc = MetaSyncService(db_session)
            result = svc.sync_insights(
                org_id=seed_data["org_id"],
                ad_account_id=seed_data["ad_account_id"],
                since="2025-06-01",
                until="2025-06-01",
                levels=["campaign"],
            )

        assert result["status"] == "success"
        assert result["items_upserted"] == 0
        assert result["error_count"] == 0

        insights_count = db_session.query(MetaInsightsDaily).filter(
            MetaInsightsDaily.org_id == seed_data["org_id"],
        ).count()
        assert insights_count == 0

        # A MetaSyncRun should still be recorded
        run = db_session.query(MetaSyncRun).filter(
            MetaSyncRun.org_id == seed_data["org_id"],
            MetaSyncRun.job_type == "insights",
        ).first()
        assert run is not None
        assert run.items_upserted == 0


# ── Test 7: sync_insights handles partial failure ───────────────────────────


class TestSyncInsightsPartialFailure:

    def test_partial_failure_one_level_fails(self, db_session, seed_data):
        """When one level fails, others still sync. Status is 'partial'."""
        campaign_rows = [_make_insight_row(campaign_id="camp_ok", level="campaign")]

        def side_effect(ad_account_meta_id, level, time_range):
            if level == "campaign":
                return campaign_rows
            elif level == "adset":
                raise RuntimeError("Adset API failure")
            elif level == "ad":
                return [_make_insight_row(campaign_id="ad_ok", level="ad")]
            return []

        with patch("backend.src.services.meta_sync_service.MetaApiClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_insights.side_effect = side_effect
            MockClient.return_value = mock_instance

            svc = MetaSyncService(db_session)
            result = svc.sync_insights(
                org_id=seed_data["org_id"],
                ad_account_id=seed_data["ad_account_id"],
                since="2025-06-01",
                until="2025-06-01",
                levels=["campaign", "adset", "ad"],
            )

        assert result["status"] == "partial"
        assert result["items_upserted"] == 2  # campaign + ad
        assert result["error_count"] == 1

        # Verify partial run recorded
        run = db_session.query(MetaSyncRun).filter(
            MetaSyncRun.org_id == seed_data["org_id"],
            MetaSyncRun.job_type == "insights",
        ).first()
        assert run.status == SyncRunStatus.PARTIAL
        assert run.error_count == 1


# ── Test 8: unique constraint prevents duplicates ───────────────────────────


class TestSyncInsightsUniqueConstraint:

    def test_unique_constraint_prevents_duplicates(self, db_session, seed_data):
        """Inserting two rows with the same (org, account, level, entity, date) is prevented by upsert logic."""
        api_rows = [
            _make_insight_row(campaign_id="camp_dup", date_start="2025-06-05", date_stop="2025-06-05", spend="80.00"),
        ]

        with patch("backend.src.services.meta_sync_service.MetaApiClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_insights.return_value = api_rows
            MockClient.return_value = mock_instance

            svc = MetaSyncService(db_session)
            # First sync
            svc.sync_insights(
                org_id=seed_data["org_id"],
                ad_account_id=seed_data["ad_account_id"],
                since="2025-06-05",
                until="2025-06-05",
                levels=["campaign"],
            )
            # Second sync with same data
            svc.sync_insights(
                org_id=seed_data["org_id"],
                ad_account_id=seed_data["ad_account_id"],
                since="2025-06-05",
                until="2025-06-05",
                levels=["campaign"],
            )

        # Should still be exactly 1 row, not 2
        rows = db_session.query(MetaInsightsDaily).filter(
            MetaInsightsDaily.entity_meta_id == "camp_dup",
            MetaInsightsDaily.org_id == seed_data["org_id"],
        ).all()
        assert len(rows) == 1


# ── Test 9: sync_insights maps conversions and roas from actions array ──────


class TestSyncInsightsConversionsAndRoas:

    def test_maps_conversions_from_actions(self, db_session, seed_data):
        """normalize_insight extracts conversions count and purchase_roas from the actions array."""
        actions = [
            {"action_type": "purchase", "value": "12"},
            {"action_type": "link_click", "value": "100"},
            {"action_type": "complete_registration", "value": "3"},
        ]
        roas_data = [
            {"action_type": "purchase", "value": "3.5"},
        ]

        api_rows = [
            _make_insight_row(
                campaign_id="camp_conv",
                date_start="2025-06-20",
                date_stop="2025-06-20",
                actions=actions,
                purchase_roas=roas_data,
            ),
        ]

        with patch("backend.src.services.meta_sync_service.MetaApiClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_insights.return_value = api_rows
            MockClient.return_value = mock_instance

            svc = MetaSyncService(db_session)
            svc.sync_insights(
                org_id=seed_data["org_id"],
                ad_account_id=seed_data["ad_account_id"],
                since="2025-06-20",
                until="2025-06-20",
                levels=["campaign"],
            )

        row = db_session.query(MetaInsightsDaily).filter(
            MetaInsightsDaily.entity_meta_id == "camp_conv",
        ).first()

        assert row is not None
        # 12 (purchase) + 3 (complete_registration) = 15
        assert row.conversions == 15
        # purchase ROAS = 3.5
        assert row.purchase_roas == 3.5
        # actions_json should be stored
        assert row.actions_json is not None
        assert len(row.actions_json) == 3

    def test_no_conversions_when_no_actions(self, db_session, seed_data):
        """When no actions array is provided, conversions and purchase_roas are None."""
        api_rows = [
            _make_insight_row(
                campaign_id="camp_no_conv",
                date_start="2025-06-21",
                date_stop="2025-06-21",
            ),
        ]

        with patch("backend.src.services.meta_sync_service.MetaApiClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_insights.return_value = api_rows
            MockClient.return_value = mock_instance

            svc = MetaSyncService(db_session)
            svc.sync_insights(
                org_id=seed_data["org_id"],
                ad_account_id=seed_data["ad_account_id"],
                since="2025-06-21",
                until="2025-06-21",
                levels=["campaign"],
            )

        row = db_session.query(MetaInsightsDaily).filter(
            MetaInsightsDaily.entity_meta_id == "camp_no_conv",
        ).first()
        assert row is not None
        assert row.conversions is None
        assert row.purchase_roas is None


# ── Test 10: sync_insights records error_count in MetaSyncRun ───────────────


class TestSyncInsightsErrorCountInRun:

    def test_error_count_recorded_in_sync_run(self, db_session, seed_data):
        """When multiple levels fail, error_count in MetaSyncRun matches the number of failures."""
        def side_effect(ad_account_meta_id, level, time_range):
            if level == "campaign":
                raise ValueError("Campaign level error")
            elif level == "adset":
                raise ConnectionError("Adset level error")
            elif level == "ad":
                return [_make_insight_row(campaign_id="ad_survive", level="ad")]
            return []

        with patch("backend.src.services.meta_sync_service.MetaApiClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_insights.side_effect = side_effect
            MockClient.return_value = mock_instance

            svc = MetaSyncService(db_session)
            result = svc.sync_insights(
                org_id=seed_data["org_id"],
                ad_account_id=seed_data["ad_account_id"],
                since="2025-06-01",
                until="2025-06-01",
                levels=["campaign", "adset", "ad"],
            )

        assert result["error_count"] == 2
        assert result["items_upserted"] == 1
        assert result["status"] == "partial"

        run = db_session.query(MetaSyncRun).filter(
            MetaSyncRun.org_id == seed_data["org_id"],
            MetaSyncRun.job_type == "insights",
        ).first()
        assert run is not None
        assert run.error_count == 2
        assert run.error_summary_json is not None
        assert len(run.error_summary_json) == 2
        assert any("Campaign level error" in e for e in run.error_summary_json)
        assert any("Adset level error" in e for e in run.error_summary_json)


# ── Test 11 (bonus): sync_insights with no active connection returns error ──


class TestSyncInsightsNoConnection:

    def test_no_active_connection_returns_error(self, db_session, seed_data):
        """When the connection is not active, sync_insights returns an error dict."""
        # Deactivate the connection
        conn = db_session.query(MetaConnection).filter(
            MetaConnection.id == seed_data["conn_id"],
        ).first()
        conn.status = "expired"
        db_session.commit()

        svc = MetaSyncService(db_session)
        result = svc.sync_insights(
            org_id=seed_data["org_id"],
            ad_account_id=seed_data["ad_account_id"],
            since="2025-06-01",
            until="2025-06-01",
            levels=["campaign"],
        )

        assert result["status"] == "error"
        assert "No active Meta connection" in result["message"]


# ── Test 12 (bonus): sync_insights default levels ──────────────────────────


class TestSyncInsightsDefaultLevels:

    def test_defaults_to_all_three_levels(self, db_session, seed_data):
        """When levels is not provided, sync_insights defaults to campaign, adset, ad."""
        called_levels = []

        def side_effect(ad_account_meta_id, level, time_range):
            called_levels.append(level)
            return []

        with patch("backend.src.services.meta_sync_service.MetaApiClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_insights.side_effect = side_effect
            MockClient.return_value = mock_instance

            svc = MetaSyncService(db_session)
            svc.sync_insights(
                org_id=seed_data["org_id"],
                ad_account_id=seed_data["ad_account_id"],
                since="2025-06-01",
                until="2025-06-01",
                # levels not passed -- defaults to all three
            )

        assert called_levels == ["campaign", "adset", "ad"]
