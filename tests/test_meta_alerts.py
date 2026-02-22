"""
Sprint 6 Tests -- InsightEngine and AnomalyDetector alert generation.
Covers rule-based alert triggers, no-data edge cases, anomaly detection via
robust z-scores, and deduplication logic.
"""
import pytest
from uuid import uuid4
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PG_UUID BEFORE any model import so UUID columns map to String(36) on SQLite
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

from backend.src.database.models import (
    Base,
    Organization,
    MetaAdAccount,
    MetaInsightsDaily,
    MetaAlert,
    EntityMemory,
    InsightLevel,
    AlertSeverity,
)
from backend.src.engines.insight_engine import InsightEngine
from backend.src.engines.anomaly_detector import AnomalyDetector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


def _seed_org(db_session) -> dict:
    """Create a minimal Organization and MetaAdAccount. Returns ids dict."""
    org_id = uuid4()
    org = Organization(
        id=org_id,
        name="Alert Test Org",
        slug=f"alert-test-{uuid4().hex[:8]}",
        created_at=datetime.utcnow(),
    )
    db_session.add(org)

    ad_account_id = uuid4()
    ad_account = MetaAdAccount(
        id=ad_account_id,
        org_id=org_id,
        meta_account_id=f"act_{uuid4().hex[:8]}",
        name="Test Ad Account",
        currency="USD",
        status="active",
        created_at=datetime.utcnow(),
    )
    db_session.add(ad_account)
    db_session.commit()

    return {"org_id": org_id, "ad_account_id": ad_account_id}


def _make_insight(
    db_session,
    org_id,
    ad_account_id,
    entity_meta_id="camp_001",
    level=InsightLevel.CAMPAIGN,
    date_start=None,
    spend=50.0,
    impressions=10000,
    clicks=100,
    ctr=1.0,
    cpm=5.0,
    cpc=0.50,
    frequency=1.5,
    conversions=10,
    purchase_roas=2.5,
):
    """Insert a single MetaInsightsDaily row with realistic defaults."""
    if date_start is None:
        date_start = datetime.utcnow() - timedelta(days=1)
    row = MetaInsightsDaily(
        id=uuid4(),
        org_id=org_id,
        ad_account_id=ad_account_id,
        level=level,
        entity_meta_id=entity_meta_id,
        date_start=date_start,
        date_stop=date_start + timedelta(days=1),
        spend=spend,
        impressions=impressions,
        clicks=clicks,
        ctr=ctr,
        cpm=cpm,
        cpc=cpc,
        frequency=frequency,
        conversions=conversions,
        purchase_roas=purchase_roas,
    )
    db_session.add(row)
    return row


# ---------------------------------------------------------------------------
# InsightEngine Tests
# ---------------------------------------------------------------------------


class TestInsightEngineCtrLow:
    """Rule 1: CTR below 70% of baseline triggers ctr_low alert."""

    @patch("backend.src.engines.insight_engine.logger")
    def test_low_ctr_triggers_alert(self, _mock_logger, db_session):
        ids = _seed_org(db_session)

        # Default CTR_LOW_THRESHOLD is 0.5 -> baseline = 0.5
        # 70% of 0.5 = 0.35 -> anything below 0.35 triggers
        _make_insight(
            db_session,
            ids["org_id"],
            ids["ad_account_id"],
            entity_meta_id="camp_ctr_low",
            ctr=0.20,  # well below 0.35
        )
        db_session.commit()

        engine = InsightEngine(db_session)
        result = engine.analyze(ids["org_id"], ids["ad_account_id"])
        db_session.commit()

        assert result["status"] == "success"
        assert result["alerts"] >= 1

        alerts = db_session.query(MetaAlert).filter(
            MetaAlert.org_id == ids["org_id"],
            MetaAlert.alert_type == "ctr_low",
        ).all()
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.HIGH
        assert alerts[0].entity_meta_id == "camp_ctr_low"
        assert "CTR dropped" in alerts[0].message


class TestInsightEngineCpaHigh:
    """Rule 2: CPA > 1.5x baseline triggers cpa_high alert."""

    @patch("backend.src.engines.insight_engine.logger")
    def test_high_cpa_triggers_alert(self, _mock_logger, db_session):
        ids = _seed_org(db_session)
        entity_id = "camp_cpa_high"

        # Seed EntityMemory with a CPA baseline of 10.0
        em = EntityMemory(
            id=uuid4(),
            org_id=ids["org_id"],
            entity_type="campaign",
            entity_id=entity_id,
            baseline_ema_json={"cpa": 10.0},
        )
        db_session.add(em)

        # Create insight data: total spend=100, total conversions=5 -> CPA=20
        # CPA=20 > 10.0 * 1.5 = 15.0 -> triggers cpa_high
        now = datetime.utcnow()
        _make_insight(
            db_session,
            ids["org_id"],
            ids["ad_account_id"],
            entity_meta_id=entity_id,
            date_start=now - timedelta(days=2),
            spend=50.0,
            conversions=2,
            ctr=1.0,  # keep above threshold to avoid ctr_low noise
        )
        _make_insight(
            db_session,
            ids["org_id"],
            ids["ad_account_id"],
            entity_meta_id=entity_id,
            date_start=now - timedelta(days=1),
            spend=50.0,
            conversions=3,
            ctr=1.0,
        )
        db_session.commit()

        engine = InsightEngine(db_session)
        result = engine.analyze(ids["org_id"], ids["ad_account_id"])
        db_session.commit()

        assert result["status"] == "success"

        alerts = db_session.query(MetaAlert).filter(
            MetaAlert.org_id == ids["org_id"],
            MetaAlert.alert_type == "cpa_high",
        ).all()
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.HIGH
        assert alerts[0].entity_meta_id == entity_id
        assert "CPA spiked" in alerts[0].message
        assert alerts[0].payload_json["current_cpa"] == 20.0
        assert alerts[0].payload_json["baseline_cpa"] == 10.0


class TestInsightEngineFrequencyDecay:
    """Rule 4: High frequency (>3.0) with declining CTR over >=3 rows."""

    @patch("backend.src.engines.insight_engine.logger")
    def test_frequency_decay_triggers_alert(self, _mock_logger, db_session):
        ids = _seed_org(db_session)
        entity_id = "adset_freq_decay"
        now = datetime.utcnow()

        # 3 days of data with frequency > 3.0 and CTR declining
        _make_insight(
            db_session,
            ids["org_id"],
            ids["ad_account_id"],
            entity_meta_id=entity_id,
            level=InsightLevel.ADSET,
            date_start=now - timedelta(days=3),
            frequency=4.0,
            ctr=1.2,
        )
        _make_insight(
            db_session,
            ids["org_id"],
            ids["ad_account_id"],
            entity_meta_id=entity_id,
            level=InsightLevel.ADSET,
            date_start=now - timedelta(days=2),
            frequency=4.5,
            ctr=0.9,
        )
        _make_insight(
            db_session,
            ids["org_id"],
            ids["ad_account_id"],
            entity_meta_id=entity_id,
            level=InsightLevel.ADSET,
            date_start=now - timedelta(days=1),
            frequency=5.0,
            ctr=0.6,
        )
        db_session.commit()

        engine = InsightEngine(db_session)
        result = engine.analyze(ids["org_id"], ids["ad_account_id"])
        db_session.commit()

        assert result["status"] == "success"

        alerts = db_session.query(MetaAlert).filter(
            MetaAlert.org_id == ids["org_id"],
            MetaAlert.alert_type == "frequency_decay",
        ).all()
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.MEDIUM
        assert alerts[0].entity_meta_id == entity_id
        assert "frequency" in alerts[0].message.lower()
        assert alerts[0].payload_json["frequency"] > 3.0
        assert alerts[0].payload_json["ctr_trend"] < 0


class TestInsightEngineSpendSpikeNoConversions:
    """Rule 5: Spend spike (>2x average) with 0 conversions on latest day -> CRITICAL."""

    @patch("backend.src.engines.insight_engine.logger")
    def test_spend_spike_zero_conversions_triggers_critical(self, _mock_logger, db_session):
        ids = _seed_org(db_session)
        entity_id = "camp_spend_spike"
        now = datetime.utcnow()

        # 4 days of moderate spend, then 1 day with a huge spike and 0 conversions
        for i in range(4, 0, -1):
            _make_insight(
                db_session,
                ids["org_id"],
                ids["ad_account_id"],
                entity_meta_id=entity_id,
                date_start=now - timedelta(days=i),
                spend=50.0,
                conversions=5,
                ctr=1.0,
            )

        # Latest day: spend = 300 (6x of 50 avg), conversions = 0
        _make_insight(
            db_session,
            ids["org_id"],
            ids["ad_account_id"],
            entity_meta_id=entity_id,
            date_start=now,
            spend=300.0,
            conversions=0,
            ctr=1.0,
        )
        db_session.commit()

        engine = InsightEngine(db_session)
        result = engine.analyze(ids["org_id"], ids["ad_account_id"])
        db_session.commit()

        assert result["status"] == "success"

        alerts = db_session.query(MetaAlert).filter(
            MetaAlert.org_id == ids["org_id"],
            MetaAlert.alert_type == "spend_spike_no_conv",
        ).all()
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.CRITICAL
        assert alerts[0].entity_meta_id == entity_id
        assert "0 conversions" in alerts[0].message


class TestInsightEngineNoData:
    """No insights data present -> engine returns no_data status with 0 alerts."""

    @patch("backend.src.engines.insight_engine.logger")
    def test_no_data_returns_no_alerts(self, _mock_logger, db_session):
        ids = _seed_org(db_session)

        engine = InsightEngine(db_session)
        result = engine.analyze(ids["org_id"], ids["ad_account_id"])

        assert result["status"] == "no_data"
        assert result["alerts"] == 0

        total_alerts = db_session.query(MetaAlert).filter(
            MetaAlert.org_id == ids["org_id"],
        ).count()
        assert total_alerts == 0


# ---------------------------------------------------------------------------
# AnomalyDetector Tests
# ---------------------------------------------------------------------------


class TestAnomalyDetectorSpendSpike:
    """Spike in spend with z-score > 3.5 triggers a CRITICAL anomaly alert."""

    @patch("backend.src.engines.anomaly_detector.logger")
    def test_spend_spike_detected_as_critical(self, _mock_logger, db_session):
        ids = _seed_org(db_session)
        entity_id = "camp_anomaly_spike"
        now = datetime.utcnow()

        # 7 normal days with very consistent spend ~50
        for i in range(7, 0, -1):
            _make_insight(
                db_session,
                ids["org_id"],
                ids["ad_account_id"],
                entity_meta_id=entity_id,
                date_start=now - timedelta(days=i),
                spend=50.0 + (i % 3),  # slight variation: 50, 51, 52
                ctr=1.0,
                cpm=5.0,
                cpc=0.50,
                frequency=1.5,
            )

        # Day 0: extreme outlier spend = 500 (10x normal)
        _make_insight(
            db_session,
            ids["org_id"],
            ids["ad_account_id"],
            entity_meta_id=entity_id,
            date_start=now,
            spend=500.0,
            ctr=1.0,
            cpm=5.0,
            cpc=0.50,
            frequency=1.5,
        )
        db_session.commit()

        detector = AnomalyDetector(db_session)
        result = detector.detect(ids["org_id"], ids["ad_account_id"])
        db_session.commit()

        assert result["status"] == "success"
        assert result["anomalies"] >= 1

        spend_alerts = db_session.query(MetaAlert).filter(
            MetaAlert.org_id == ids["org_id"],
            MetaAlert.alert_type == "anomaly_spend_spike",
        ).all()
        assert len(spend_alerts) == 1
        assert spend_alerts[0].severity == AlertSeverity.CRITICAL
        assert spend_alerts[0].entity_meta_id == entity_id
        assert spend_alerts[0].payload_json["metric"] == "spend"
        assert spend_alerts[0].payload_json["direction"] == "spike"
        assert spend_alerts[0].payload_json["z_score"] > 3.5


class TestAnomalyDetectorNormalValues:
    """Normal, consistent values across days -> no anomaly alerts generated."""

    @patch("backend.src.engines.anomaly_detector.logger")
    def test_normal_values_no_anomaly(self, _mock_logger, db_session):
        ids = _seed_org(db_session)
        entity_id = "camp_normal"
        now = datetime.utcnow()

        # 8 days of perfectly consistent data (all identical)
        for i in range(8, 0, -1):
            _make_insight(
                db_session,
                ids["org_id"],
                ids["ad_account_id"],
                entity_meta_id=entity_id,
                date_start=now - timedelta(days=i),
                spend=50.0,
                ctr=1.0,
                cpm=5.0,
                cpc=0.50,
                frequency=1.5,
            )

        # Latest day: same as all others
        _make_insight(
            db_session,
            ids["org_id"],
            ids["ad_account_id"],
            entity_meta_id=entity_id,
            date_start=now,
            spend=50.0,
            ctr=1.0,
            cpm=5.0,
            cpc=0.50,
            frequency=1.5,
        )
        db_session.commit()

        detector = AnomalyDetector(db_session)
        result = detector.detect(ids["org_id"], ids["ad_account_id"])
        db_session.commit()

        assert result["status"] == "success"
        assert result["anomalies"] == 0

        total_alerts = db_session.query(MetaAlert).filter(
            MetaAlert.org_id == ids["org_id"],
        ).count()
        assert total_alerts == 0


class TestAnomalyDetectorDeduplication:
    """Same alert type + entity within 24h should not be created twice."""

    @patch("backend.src.engines.anomaly_detector.logger")
    def test_duplicate_alert_not_created(self, _mock_logger, db_session):
        ids = _seed_org(db_session)
        entity_id = "camp_dedup"
        now = datetime.utcnow()

        # 7 normal days + 1 outlier
        for i in range(7, 0, -1):
            _make_insight(
                db_session,
                ids["org_id"],
                ids["ad_account_id"],
                entity_meta_id=entity_id,
                date_start=now - timedelta(days=i),
                spend=50.0 + (i % 3),
                ctr=1.0,
                cpm=5.0,
                cpc=0.50,
                frequency=1.5,
            )
        _make_insight(
            db_session,
            ids["org_id"],
            ids["ad_account_id"],
            entity_meta_id=entity_id,
            date_start=now,
            spend=500.0,
            ctr=1.0,
            cpm=5.0,
            cpc=0.50,
            frequency=1.5,
        )
        db_session.commit()

        detector = AnomalyDetector(db_session)

        # First run: alerts should be created
        result1 = detector.detect(ids["org_id"], ids["ad_account_id"])
        db_session.commit()
        first_count = result1["anomalies"]
        assert first_count >= 1

        spend_alerts_after_first = db_session.query(MetaAlert).filter(
            MetaAlert.org_id == ids["org_id"],
            MetaAlert.alert_type == "anomaly_spend_spike",
            MetaAlert.entity_meta_id == entity_id,
        ).count()
        assert spend_alerts_after_first == 1

        # Second run: same alert should be deduplicated (already exists within 24h)
        result2 = detector.detect(ids["org_id"], ids["ad_account_id"])
        db_session.commit()

        spend_alerts_after_second = db_session.query(MetaAlert).filter(
            MetaAlert.org_id == ids["org_id"],
            MetaAlert.alert_type == "anomaly_spend_spike",
            MetaAlert.entity_meta_id == entity_id,
        ).count()
        # Still only 1 -- the second run did NOT create a duplicate
        assert spend_alerts_after_second == 1


class TestInsightEngineDeduplication:
    """InsightEngine also deduplicates: same ctr_low alert within 24h is not duplicated."""

    @patch("backend.src.engines.insight_engine.logger")
    def test_insight_engine_dedup(self, _mock_logger, db_session):
        ids = _seed_org(db_session)
        entity_id = "camp_ie_dedup"

        _make_insight(
            db_session,
            ids["org_id"],
            ids["ad_account_id"],
            entity_meta_id=entity_id,
            ctr=0.10,
        )
        db_session.commit()

        engine = InsightEngine(db_session)

        # First run
        engine.analyze(ids["org_id"], ids["ad_account_id"])
        db_session.commit()

        ctr_alerts = db_session.query(MetaAlert).filter(
            MetaAlert.org_id == ids["org_id"],
            MetaAlert.alert_type == "ctr_low",
            MetaAlert.entity_meta_id == entity_id,
        ).count()
        assert ctr_alerts == 1

        # Second run
        engine.analyze(ids["org_id"], ids["ad_account_id"])
        db_session.commit()

        ctr_alerts_after = db_session.query(MetaAlert).filter(
            MetaAlert.org_id == ids["org_id"],
            MetaAlert.alert_type == "ctr_low",
            MetaAlert.entity_meta_id == entity_id,
        ).count()
        assert ctr_alerts_after == 1


class TestInsightEngineNoAccountReturnsNoAccount:
    """Calling analyze with a non-existent ad_account_id returns no_account status."""

    @patch("backend.src.engines.insight_engine.logger")
    def test_no_account_returns_status(self, _mock_logger, db_session):
        ids = _seed_org(db_session)
        fake_account_id = uuid4()

        engine = InsightEngine(db_session)
        result = engine.analyze(ids["org_id"], fake_account_id)

        assert result["status"] == "no_account"
        assert result["alerts"] == 0
