"""
CI AutoLoop v1 — Comprehensive tests (30+).

Covers: tick scheduling, idempotency keys, should_run logic, run-now,
degraded mode skip, ci_run lifecycle, detect creates opportunities + alerts,
failure error classification, plan gates, queue routing, backoff policies.
"""
import os
import math
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from uuid import uuid4, UUID

from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PG_UUID BEFORE any model imports so SQLite can handle UUID columns.
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.src.database.models import (
    Base, Organization, JobRun, JobRunStatus, MetaAlert, AlertSeverity,
    Subscription, PlanEnum, SubscriptionStatusEnum,
)
from backend.src.ci.models import (
    CIRun, CIRunType, CIRunStatus,
    CICompetitor, CICompetitorStatus, CICanonicalItem, CIItemType,
    CICompetitorDomain, CIDomainType,
)
from backend.src.ci.ci_autoloop import (
    CIAutoLoop, make_idempotency_key,
    _get_plan, _get_sub_status, _ingest_interval, _detect_interval,
    _max_competitors, _max_items,
)
from backend.src.ci.ci_tasks import (
    run_ci_ingest, run_ci_detect,
    _is_provider_degraded, _score_to_severity, _opp_type_to_alert_type,
    _db_item_to_canonical,
    _collect_from_source, _collect_web, _collect_meta_ads,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


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
def db(db_engine):
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


def _create_org(db, name="Test Org") -> UUID:
    org_id = uuid4()
    org = Organization(id=org_id, name=name, slug=f"test-{org_id.hex[:8]}")
    db.add(org)
    db.flush()
    return org_id


def _create_subscription(db, org_id, plan="pro", status="active"):
    sub = Subscription(
        id=uuid4(),
        org_id=org_id,
        stripe_customer_id=f"cus_{uuid4().hex[:12]}",
        stripe_subscription_id=f"sub_{uuid4().hex[:12]}",
        plan=PlanEnum(plan) if isinstance(plan, str) else plan,
        status=SubscriptionStatusEnum(status) if isinstance(status, str) else status,
    )
    db.add(sub)
    db.flush()
    return sub


def _create_ci_run(db, org_id, run_type="ingest", source="web", status="succeeded",
                   finished_at=None, idempotency_key=None):
    run = CIRun(
        id=uuid4(),
        org_id=org_id,
        run_type=CIRunType(run_type),
        source=source,
        status=CIRunStatus(status),
        finished_at=finished_at or datetime.utcnow(),
        idempotency_key=idempotency_key,
    )
    db.add(run)
    db.flush()
    return run


def _create_competitor(db, org_id, name="Competitor A"):
    comp = CICompetitor(
        id=uuid4(),
        org_id=org_id,
        name=name,
        status=CICompetitorStatus.ACTIVE,
    )
    db.add(comp)
    db.flush()
    return comp


def _create_canonical_item(db, org_id, competitor_id, title="Test Ad",
                           item_type="ad", last_seen_at=None):
    item = CICanonicalItem(
        id=uuid4(),
        org_id=org_id,
        competitor_id=competitor_id,
        item_type=CIItemType(item_type),
        title=title,
        body_text="Test body text for the ad",
        first_seen_at=last_seen_at or datetime.utcnow(),
        last_seen_at=last_seen_at or datetime.utcnow(),
        canonical_json={
            "platform": "meta",
            "competitor": "Competitor A",
            "cta": "Shop Now",
            "format": "image",
            "country": "US",
            "keywords": ["test", "ad"],
            "fingerprint": f"fp_{uuid4().hex[:8]}",
        },
    )
    db.add(item)
    db.flush()
    return item


# ═══════════════════════════════════════════════════════════════════════════
# UNIT TESTS — Idempotency Keys
# ═══════════════════════════════════════════════════════════════════════════


class TestIdempotencyKeys:

    def test_key_format(self):
        org_id = uuid4()
        now = datetime(2025, 6, 15, 10, 30)
        key = make_idempotency_key("ingest", org_id, "web", now, 180)
        assert key.startswith("ci:ingest:")
        assert str(org_id) in key
        assert "web" in key
        assert "2025-06-15" in key

    def test_key_bucket_calculation(self):
        org_id = uuid4()
        now = datetime(2025, 6, 15, 10, 30)  # 630 minutes
        key = make_idempotency_key("ingest", org_id, "web", now, 180)
        bucket = math.floor(630 / 180)  # 3
        assert key.endswith(f":3")

    def test_same_window_same_key(self):
        org_id = uuid4()
        t1 = datetime(2025, 6, 15, 10, 0)
        t2 = datetime(2025, 6, 15, 10, 30)
        k1 = make_idempotency_key("ingest", org_id, "web", t1, 180)
        k2 = make_idempotency_key("ingest", org_id, "web", t2, 180)
        assert k1 == k2

    def test_different_window_different_key(self):
        org_id = uuid4()
        t1 = datetime(2025, 6, 15, 10, 0)
        t2 = datetime(2025, 6, 15, 13, 0)  # next 3-hour bucket
        k1 = make_idempotency_key("ingest", org_id, "web", t1, 180)
        k2 = make_idempotency_key("ingest", org_id, "web", t2, 180)
        assert k1 != k2

    def test_different_org_different_key(self):
        t = datetime(2025, 6, 15, 10, 0)
        k1 = make_idempotency_key("ingest", uuid4(), "web", t, 180)
        k2 = make_idempotency_key("ingest", uuid4(), "web", t, 180)
        assert k1 != k2

    def test_different_source_different_key(self):
        org_id = uuid4()
        t = datetime(2025, 6, 15, 10, 0)
        k1 = make_idempotency_key("ingest", org_id, "web", t, 180)
        k2 = make_idempotency_key("ingest", org_id, "meta_ads", t, 180)
        assert k1 != k2

    def test_detect_key_uses_all_source(self):
        org_id = uuid4()
        t = datetime(2025, 6, 15, 10, 0)
        key = make_idempotency_key("detect", org_id, None, t, 60)
        assert ":all:" in key

    def test_zero_interval_no_division_error(self):
        key = make_idempotency_key("ingest", uuid4(), "web", datetime.utcnow(), 0)
        assert "ci:ingest:" in key


# ═══════════════════════════════════════════════════════════════════════════
# UNIT TESTS — Plan Gates
# ═══════════════════════════════════════════════════════════════════════════


class TestPlanGates:

    def test_get_plan_no_subscription(self, db):
        org_id = _create_org(db)
        assert _get_plan(db, org_id) == "trial"

    def test_get_plan_pro(self, db):
        org_id = _create_org(db)
        _create_subscription(db, org_id, plan="pro")
        assert _get_plan(db, org_id) == "pro"

    def test_get_sub_status_no_subscription(self, db):
        org_id = _create_org(db)
        assert _get_sub_status(db, org_id) == "trialing"

    def test_get_sub_status_active(self, db):
        org_id = _create_org(db)
        _create_subscription(db, org_id, status="active")
        assert _get_sub_status(db, org_id) == "active"

    def test_ingest_interval_trial(self):
        assert _ingest_interval("trial") == 1440

    def test_ingest_interval_pro(self):
        assert _ingest_interval("pro") == 180

    def test_detect_interval_trial(self):
        assert _detect_interval("trial") == 1440

    def test_detect_interval_pro(self):
        assert _detect_interval("pro") == 60

    def test_max_competitors_trial(self):
        assert _max_competitors("trial") == 3

    def test_max_competitors_pro(self):
        assert _max_competitors("pro") == 25

    def test_max_items_trial(self):
        assert _max_items("trial") == 200

    def test_max_items_pro(self):
        assert _max_items("pro") == 2000


# ═══════════════════════════════════════════════════════════════════════════
# UNIT TESTS — Should Run Logic
# ═══════════════════════════════════════════════════════════════════════════


class TestShouldRunLogic:

    def test_should_run_ingest_first_time(self, db):
        org_id = _create_org(db)
        loop = CIAutoLoop()
        assert loop.should_run_ingest(org_id, "trial", datetime.utcnow(), db, "web") is True

    def test_should_not_run_ingest_if_idempotency_key_exists(self, db):
        org_id = _create_org(db)
        now = datetime.utcnow()
        idem_key = make_idempotency_key("ingest", org_id, "web", now, 1440)
        _create_ci_run(db, org_id, "ingest", "web", "succeeded", idempotency_key=idem_key)
        db.commit()

        loop = CIAutoLoop()
        assert loop.should_run_ingest(org_id, "trial", now, db, "web") is False

    def test_should_not_run_ingest_if_recent_success(self, db):
        org_id = _create_org(db)
        now = datetime.utcnow()
        # Succeeded 30 minutes ago, trial interval is 1440
        _create_ci_run(db, org_id, "ingest", "web", "succeeded",
                       finished_at=now - timedelta(minutes=30))
        db.commit()

        loop = CIAutoLoop()
        assert loop.should_run_ingest(org_id, "trial", now, db, "web") is False

    def test_should_run_ingest_after_interval_elapsed(self, db):
        org_id = _create_org(db)
        now = datetime.utcnow()
        # Succeeded 200 minutes ago, pro interval is 180
        _create_ci_run(db, org_id, "ingest", "web", "succeeded",
                       finished_at=now - timedelta(minutes=200))
        db.commit()

        loop = CIAutoLoop()
        assert loop.should_run_ingest(org_id, "pro", now, db, "web") is True

    def test_should_run_detect_first_time(self, db):
        org_id = _create_org(db)
        loop = CIAutoLoop()
        assert loop.should_run_detect(org_id, "trial", datetime.utcnow(), db) is True

    def test_should_not_run_detect_if_recent(self, db):
        org_id = _create_org(db)
        now = datetime.utcnow()
        _create_ci_run(db, org_id, "detect", None, "succeeded",
                       finished_at=now - timedelta(minutes=30))
        db.commit()

        loop = CIAutoLoop()
        assert loop.should_run_detect(org_id, "pro", now, db) is False


# ═══════════════════════════════════════════════════════════════════════════
# UNIT TESTS — Task Helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestTaskHelpers:

    def test_score_to_severity_high(self):
        assert _score_to_severity(0.8) == "high"

    def test_score_to_severity_medium(self):
        assert _score_to_severity(0.5) == "medium"

    def test_score_to_severity_low(self):
        assert _score_to_severity(0.2) == "low"

    def test_opp_type_to_alert_type_known(self):
        assert _opp_type_to_alert_type("new_ads_spike") == "new_ads_spike"
        assert _opp_type_to_alert_type("angle_trend_rise") == "angle_trend_rise"
        assert _opp_type_to_alert_type("format_dominance_shift") == "format_dominance_shift"

    def test_opp_type_to_alert_type_unknown(self):
        assert _opp_type_to_alert_type("unknown_type") is None

    def test_is_provider_degraded_unknown_source(self):
        assert _is_provider_degraded("unknown_source", uuid4()) is False


# ═══════════════════════════════════════════════════════════════════════════
# UNIT TESTS — Queue Routing + Backoff
# ═══════════════════════════════════════════════════════════════════════════


class TestQueueRoutingAndBackoff:

    def test_ci_ingest_routes_to_ci_io(self):
        from backend.src.jobs.queue import QUEUE_ROUTING
        assert QUEUE_ROUTING["ci_ingest"] == "ci_io"

    def test_ci_detect_routes_to_ci_cpu(self):
        from backend.src.jobs.queue import QUEUE_ROUTING
        assert QUEUE_ROUTING["ci_detect"] == "ci_cpu"

    def test_ci_ingest_backoff_policy(self):
        from backend.src.retries.backoff import BACKOFF_POLICIES
        policy = BACKOFF_POLICIES["ci_ingest"]
        assert policy["max_attempts"] == 4
        assert len(policy["delays"]) >= 3

    def test_ci_detect_backoff_policy(self):
        from backend.src.retries.backoff import BACKOFF_POLICIES
        policy = BACKOFF_POLICIES["ci_detect"]
        assert policy["max_attempts"] == 4

    def test_ci_ingest_timeout(self):
        from backend.src.jobs.task_runner import _JOB_TIMEOUT
        assert _JOB_TIMEOUT["ci_ingest"] == 300

    def test_ci_detect_timeout(self):
        from backend.src.jobs.task_runner import _JOB_TIMEOUT
        assert _JOB_TIMEOUT["ci_detect"] == 180


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — Ingest
# ═══════════════════════════════════════════════════════════════════════════


class TestCIIngestIntegration:

    def test_ingest_creates_ci_run(self, db):
        org_id = _create_org(db)
        _create_competitor(db, org_id, "Comp A")
        db.commit()

        run_ci_ingest(org_id, {"source": "web", "max_competitors": 3, "max_items": 100}, db)

        runs = db.query(CIRun).filter(CIRun.org_id == org_id).all()
        assert len(runs) == 1
        assert runs[0].run_type == CIRunType.INGEST
        assert runs[0].status == CIRunStatus.SUCCEEDED
        assert runs[0].metadata_json is not None
        assert "duration_ms" in runs[0].metadata_json

    def test_ingest_succeeds_with_no_competitors(self, db):
        org_id = _create_org(db)
        db.commit()

        run_ci_ingest(org_id, {"source": "web"}, db)

        run = db.query(CIRun).filter(CIRun.org_id == org_id).first()
        assert run.status == CIRunStatus.SUCCEEDED
        assert run.items_collected == 0

    @patch("backend.src.ci.ci_tasks._is_provider_degraded", return_value=True)
    def test_ingest_skipped_on_degraded_provider(self, mock_degraded, db):
        org_id = _create_org(db)
        db.commit()

        run_ci_ingest(org_id, {"source": "web"}, db)

        run = db.query(CIRun).filter(CIRun.org_id == org_id).first()
        assert run.status == CIRunStatus.SKIPPED
        assert run.metadata_json["skip_reason"] == "provider_web_degraded"

    def test_ingest_records_error_on_failure(self, db):
        org_id = _create_org(db)
        db.commit()

        with patch("backend.src.ci.ci_tasks._collect_from_source", side_effect=RuntimeError("API down")):
            with pytest.raises(RuntimeError, match="API down"):
                # Need a competitor to trigger the collect call
                _create_competitor(db, org_id)
                db.commit()
                run_ci_ingest(org_id, {"source": "web"}, db)

        run = db.query(CIRun).filter(CIRun.org_id == org_id).first()
        assert run.status == CIRunStatus.FAILED
        assert run.error_class == "RuntimeError"
        assert "API down" in run.error_message

    def test_ingest_links_to_job_run_id(self, db):
        org_id = _create_org(db)
        db.commit()

        job_run_id = str(uuid4())
        run_ci_ingest(org_id, {"source": "web"}, db, job_run_id=job_run_id)

        run = db.query(CIRun).filter(CIRun.org_id == org_id).first()
        assert str(run.job_run_id) == job_run_id


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — Detect
# ═══════════════════════════════════════════════════════════════════════════


class TestCIDetectIntegration:

    def test_detect_succeeds_with_no_items(self, db):
        org_id = _create_org(db)
        db.commit()

        run_ci_detect(org_id, {"max_items": 200}, db)

        run = db.query(CIRun).filter(CIRun.org_id == org_id).first()
        assert run.status == CIRunStatus.SUCCEEDED
        assert run.metadata_json.get("skip_reason") == "no_items"

    def test_detect_creates_ci_run(self, db):
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id)
        # Create items in the current window (last 30 days)
        for i in range(5):
            _create_canonical_item(db, org_id, comp.id, f"Ad {i}",
                                   last_seen_at=datetime.utcnow() - timedelta(days=i))
        db.commit()

        # Mock the opportunity engine to avoid full engine execution
        mock_report = MagicMock()
        mock_report.opportunities_found = 2
        mock_report.detectors_executed = 5
        mock_report.opportunities_deduped = 0
        mock_report.errors = []

        mock_store = MagicMock()
        mock_store.list_opportunities.return_value = []

        with patch("src.engines.opportunity_engine.engine.OpportunityEngine") as MockEngine, \
             patch("src.engines.opportunity_engine.storage.InMemoryOpportunityStore", return_value=mock_store):
            MockEngine.return_value.run_all.return_value = mock_report
            run_ci_detect(org_id, {"max_items": 200}, db)

        run = db.query(CIRun).filter(CIRun.org_id == org_id).first()
        assert run.status == CIRunStatus.SUCCEEDED
        assert run.run_type == CIRunType.DETECT
        assert run.items_collected == 5
        assert "duration_ms" in run.metadata_json

    def test_detect_creates_alerts_for_opportunities(self, db):
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id)
        for i in range(3):
            _create_canonical_item(db, org_id, comp.id, f"Ad {i}")
        db.commit()

        mock_report = MagicMock()
        mock_report.opportunities_found = 1
        mock_report.detectors_executed = 5
        mock_report.opportunities_deduped = 0
        mock_report.errors = []

        mock_opp = MagicMock()
        mock_opp.type = "new_ads_spike"
        mock_opp.priority_score = 0.8
        mock_opp.title = "Competitor spike detected"
        mock_opp.description = "Competitor A launched 10 new ads"
        mock_opp.evidence_ids = ["ev-1"]
        mock_opp.rationale = "Significant increase"
        mock_opp.suggested_actions = ["Analyze competitor creative"]

        mock_store = MagicMock()
        mock_store.list_opportunities.return_value = [mock_opp]

        with patch("src.engines.opportunity_engine.engine.OpportunityEngine") as MockEngine, \
             patch("src.engines.opportunity_engine.storage.InMemoryOpportunityStore", return_value=mock_store):
            MockEngine.return_value.run_all.return_value = mock_report
            run_ci_detect(org_id, {}, db)

        run = db.query(CIRun).filter(CIRun.org_id == org_id).first()
        assert run.alerts_created == 1

        alerts = db.query(MetaAlert).filter(MetaAlert.org_id == org_id).all()
        assert len(alerts) == 1
        assert alerts[0].alert_type == "new_ads_spike"
        assert alerts[0].severity == AlertSeverity.HIGH
        assert alerts[0].entity_type == "ci_opportunity"
        assert "evidence_ids" in alerts[0].payload_json

    def test_detect_failure_sets_error_class(self, db):
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id)
        _create_canonical_item(db, org_id, comp.id)
        db.commit()

        with patch("src.engines.opportunity_engine.engine.OpportunityEngine", side_effect=ValueError("Engine broken")):
            with patch("src.engines.opportunity_engine.storage.InMemoryOpportunityStore"):
                with pytest.raises(ValueError, match="Engine broken"):
                    run_ci_detect(org_id, {}, db)

        run = db.query(CIRun).filter(CIRun.org_id == org_id).first()
        assert run.status == CIRunStatus.FAILED
        assert run.error_class == "ValueError"
        assert "Engine broken" in run.error_message


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — Tick Orchestration
# ═══════════════════════════════════════════════════════════════════════════


class TestTickOrchestration:

    @patch("backend.src.ci.ci_autoloop.settings")
    def test_tick_disabled(self, mock_settings, db):
        mock_settings.CI_AUTOLOOP_ENABLED = False
        loop = CIAutoLoop()
        result = loop.tick(datetime.utcnow(), db)
        assert result == {"status": "disabled"}

    @patch("backend.src.ci.ci_autoloop.settings")
    def test_tick_enumerates_all_orgs(self, mock_settings, db):
        mock_settings.CI_AUTOLOOP_ENABLED = True
        mock_settings.CI_INGEST_INTERVAL_MINUTES_TRIAL = 1440
        mock_settings.CI_DETECT_INTERVAL_MINUTES_TRIAL = 1440
        mock_settings.CI_INGEST_INTERVAL_MINUTES_PRO = 180
        mock_settings.CI_DETECT_INTERVAL_MINUTES_PRO = 60
        mock_settings.CI_MAX_COMPETITORS_TRIAL = 3
        mock_settings.CI_MAX_COMPETITORS_PRO = 25
        mock_settings.CI_MAX_ITEMS_PER_RUN_TRIAL = 200
        mock_settings.CI_MAX_ITEMS_PER_RUN_PRO = 2000
        mock_settings.CI_SOURCE_WEB_ENABLED = True
        mock_settings.CI_SOURCE_META_ADS_ENABLED = True
        mock_settings.CI_SOURCE_GOOGLE_ADS_ENABLED = False
        mock_settings.CI_SOURCE_TIKTOK_ENABLED = False

        _create_org(db, "Org A")
        _create_org(db, "Org B")
        db.commit()

        loop = CIAutoLoop()
        with patch.object(loop, "enqueue_ingest", return_value="job-1") as mock_ingest, \
             patch.object(loop, "enqueue_detect", return_value="job-2") as mock_detect:
            result = loop.tick(datetime.utcnow(), db)

        assert result["orgs_checked"] == 2
        # 2 orgs × 2 enabled sources = 4 ingest + 2 detect
        assert mock_ingest.call_count == 4
        assert mock_detect.call_count == 2

    @patch("backend.src.ci.ci_autoloop.settings")
    def test_tick_past_due_only_detect(self, mock_settings, db):
        mock_settings.CI_AUTOLOOP_ENABLED = True
        mock_settings.CI_INGEST_INTERVAL_MINUTES_TRIAL = 1440
        mock_settings.CI_DETECT_INTERVAL_MINUTES_TRIAL = 1440
        mock_settings.CI_INGEST_INTERVAL_MINUTES_PRO = 180
        mock_settings.CI_DETECT_INTERVAL_MINUTES_PRO = 60
        mock_settings.CI_MAX_COMPETITORS_TRIAL = 3
        mock_settings.CI_MAX_COMPETITORS_PRO = 25
        mock_settings.CI_MAX_ITEMS_PER_RUN_TRIAL = 200
        mock_settings.CI_MAX_ITEMS_PER_RUN_PRO = 2000
        mock_settings.CI_SOURCE_WEB_ENABLED = True
        mock_settings.CI_SOURCE_META_ADS_ENABLED = True
        mock_settings.CI_SOURCE_GOOGLE_ADS_ENABLED = False
        mock_settings.CI_SOURCE_TIKTOK_ENABLED = False

        org_id = _create_org(db)
        _create_subscription(db, org_id, plan="pro", status="past_due")
        db.commit()

        loop = CIAutoLoop()
        with patch.object(loop, "enqueue_ingest") as mock_ingest, \
             patch.object(loop, "enqueue_detect", return_value="job-2") as mock_detect:
            result = loop.tick(datetime.utcnow(), db)

        # past_due → no ingest, only detect
        assert mock_ingest.call_count == 0
        assert mock_detect.call_count == 1


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — DB Item Conversion
# ═══════════════════════════════════════════════════════════════════════════


class TestDBItemConversion:

    def test_db_item_to_canonical(self, db):
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id)
        item = _create_canonical_item(db, org_id, comp.id, "Test Headline")
        db.commit()

        canonical = _db_item_to_canonical(item)
        assert canonical.id == str(item.id)
        assert canonical.source == "ci_module"
        assert canonical.headline == "Test Headline"
        assert canonical.platform == "meta"
        assert canonical.cta == "Shop Now"
        assert "test" in canonical.keywords


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — CIRun Lifecycle
# ═══════════════════════════════════════════════════════════════════════════


class TestCIRunLifecycle:

    def test_ci_run_status_transitions(self, db):
        org_id = _create_org(db)
        db.commit()

        run_ci_ingest(org_id, {"source": "web"}, db)
        run = db.query(CIRun).filter(CIRun.org_id == org_id).first()

        # Should have transitioned: QUEUED → RUNNING → SUCCEEDED
        assert run.status == CIRunStatus.SUCCEEDED
        assert run.started_at is not None
        assert run.finished_at is not None
        assert run.finished_at >= run.started_at

    def test_ci_run_metadata_populated(self, db):
        org_id = _create_org(db)
        _create_competitor(db, org_id)
        db.commit()

        run_ci_ingest(org_id, {"source": "web", "max_items": 50}, db)
        run = db.query(CIRun).filter(CIRun.org_id == org_id).first()

        assert run.metadata_json is not None
        assert "duration_ms" in run.metadata_json
        assert "competitors_scanned" in run.metadata_json
        assert run.metadata_json["competitors_scanned"] == 1

    def test_multiple_runs_different_types(self, db):
        org_id = _create_org(db)
        db.commit()

        run_ci_ingest(org_id, {"source": "web"}, db)
        run_ci_detect(org_id, {}, db)

        runs = db.query(CIRun).filter(CIRun.org_id == org_id).all()
        assert len(runs) == 2
        types = {r.run_type for r in runs}
        assert CIRunType.INGEST in types
        assert CIRunType.DETECT in types


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestCIConfig:

    def test_config_defaults_exist(self):
        from backend.src.config import settings
        assert hasattr(settings, "CI_AUTOLOOP_ENABLED")
        assert hasattr(settings, "CI_INGEST_INTERVAL_MINUTES_TRIAL")
        assert hasattr(settings, "CI_INGEST_INTERVAL_MINUTES_PRO")
        assert hasattr(settings, "CI_DETECT_INTERVAL_MINUTES_TRIAL")
        assert hasattr(settings, "CI_DETECT_INTERVAL_MINUTES_PRO")
        assert hasattr(settings, "CI_MAX_COMPETITORS_TRIAL")
        assert hasattr(settings, "CI_MAX_COMPETITORS_PRO")
        assert hasattr(settings, "CI_MAX_ITEMS_PER_RUN_TRIAL")
        assert hasattr(settings, "CI_MAX_ITEMS_PER_RUN_PRO")

    def test_config_reasonable_defaults(self):
        from backend.src.config import settings
        assert settings.CI_INGEST_INTERVAL_MINUTES_TRIAL >= 60
        assert settings.CI_INGEST_INTERVAL_MINUTES_PRO < settings.CI_INGEST_INTERVAL_MINUTES_TRIAL
        assert settings.CI_MAX_COMPETITORS_PRO > settings.CI_MAX_COMPETITORS_TRIAL


# ═══════════════════════════════════════════════════════════════════════════
# METRICS TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestCIMetrics:

    def test_ci_metrics_registered(self):
        from backend.src.observability.metrics import metrics
        assert hasattr(metrics, "ci_runs_total")
        assert hasattr(metrics, "ci_run_duration_seconds")
        assert hasattr(metrics, "ci_items_collected_total")
        assert hasattr(metrics, "ci_opportunities_detected_total")
        assert hasattr(metrics, "ci_alerts_created_total")
        assert hasattr(metrics, "ci_tick_orgs_gauge")

    def test_track_ci_run_no_error(self):
        from backend.src.observability.metrics import track_ci_run
        track_ci_run("ingest", "succeeded", 1.5)  # Should not raise

    def test_track_ci_items_collected_no_error(self):
        from backend.src.observability.metrics import track_ci_items_collected
        track_ci_items_collected("web", 10)  # Should not raise

    def test_track_ci_tick_orgs_no_error(self):
        from backend.src.observability.metrics import track_ci_tick_orgs
        track_ci_tick_orgs(5)  # Should not raise


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE FEATURE FLAG TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestSourceFeatureFlags:

    def test_source_flags_exist_in_config(self):
        from backend.src.config import settings
        assert hasattr(settings, "CI_SOURCE_WEB_ENABLED")
        assert hasattr(settings, "CI_SOURCE_META_ADS_ENABLED")
        assert hasattr(settings, "CI_SOURCE_GOOGLE_ADS_ENABLED")
        assert hasattr(settings, "CI_SOURCE_TIKTOK_ENABLED")
        assert hasattr(settings, "CI_SOURCE_INSTAGRAM_ENABLED")
        assert hasattr(settings, "CI_SOURCE_SOCIAL_SCRAPING_ENABLED")

    def test_nivel_a_b_enabled_by_default(self):
        from backend.src.config import settings
        assert settings.CI_SOURCE_WEB_ENABLED is True
        assert settings.CI_SOURCE_META_ADS_ENABLED is True

    def test_nivel_c_disabled_by_default(self):
        from backend.src.config import settings
        assert settings.CI_SOURCE_GOOGLE_ADS_ENABLED is False
        assert settings.CI_SOURCE_TIKTOK_ENABLED is False
        assert settings.CI_SOURCE_INSTAGRAM_ENABLED is False
        assert settings.CI_SOURCE_SOCIAL_SCRAPING_ENABLED is False

    def test_get_enabled_sources_returns_only_enabled(self):
        from backend.src.ci.ci_autoloop import _get_enabled_sources
        sources = _get_enabled_sources()
        assert "web" in sources
        assert "meta_ads" in sources
        assert "instagram" not in sources
        assert "tiktok" not in sources

    def test_is_source_enabled_respects_flags(self):
        from backend.src.ci.ci_tasks import _is_source_enabled
        assert _is_source_enabled("web") is True
        assert _is_source_enabled("meta_ads") is True
        assert _is_source_enabled("tiktok") is False
        assert _is_source_enabled("instagram") is False
        assert _is_source_enabled("social") is False
        assert _is_source_enabled("unknown_source") is False

    def test_ingest_skipped_on_disabled_source(self, db):
        org_id = _create_org(db)
        db.commit()

        # tiktok is disabled by default
        run_ci_ingest(org_id, {"source": "tiktok"}, db)
        run = db.query(CIRun).filter(CIRun.org_id == org_id).first()
        assert run.status == CIRunStatus.SKIPPED
        assert run.metadata_json["skip_reason"] == "source_tiktok_disabled"


# ═══════════════════════════════════════════════════════════════════════════
# ROUTER / API TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestCIRouter:

    def test_router_registered_in_main(self):
        """Verify CI router is mounted in main.py (no longer dark-launched)."""
        from backend.main import app
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        ci_paths = [r for r in routes if "/ci/" in r]
        assert len(ci_paths) > 0, "CI router not found in app routes"

    def test_feed_endpoint_exists(self):
        from backend.src.ci.router import router
        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/feed" in paths

    def test_opportunities_endpoint_exists(self):
        from backend.src.ci.router import router
        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/opportunities" in paths

    def test_export_pdf_endpoint_exists(self):
        from backend.src.ci.router import router
        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/export/pdf" in paths

    def test_export_xlsx_endpoint_exists(self):
        from backend.src.ci.router import router
        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/export/xlsx" in paths

    def test_competitors_crud_endpoints_exist(self):
        from backend.src.ci.router import router
        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/competitors" in paths
        assert "/competitors/{competitor_id}" in paths


# ═══════════════════════════════════════════════════════════════════════════
# COLLECTION ENGINE INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════


def _add_domain(db, org_id, competitor_id, domain, domain_type="website"):
    d = CICompetitorDomain(
        id=uuid4(),
        org_id=org_id,
        competitor_id=competitor_id,
        domain=domain,
        domain_type=CIDomainType(domain_type),
    )
    db.add(d)
    db.flush()
    return d


class TestCollectFromSourceDispatch:

    def test_unknown_source_returns_empty(self, db):
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id)
        db.commit()
        result = _collect_from_source("unknown_source", comp, org_id, 100, db)
        assert result == []

    def test_web_dispatches_to_collect_web(self, db):
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id)
        db.commit()

        with patch("backend.src.ci.ci_tasks._collect_web", return_value=[]) as mock_web:
            _collect_from_source("web", comp, org_id, 100, db)
        mock_web.assert_called_once_with(comp, org_id, 100, db)

    def test_meta_ads_dispatches_to_collect_meta_ads(self, db):
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id)
        db.commit()

        with patch("backend.src.ci.ci_tasks._collect_meta_ads", return_value=[]) as mock_ads:
            _collect_from_source("meta_ads", comp, org_id, 100, db)
        mock_ads.assert_called_once_with(comp, org_id, 100, db)


class TestCollectWeb:

    def test_no_domains_no_website_returns_empty(self, db):
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id, "No Domains Corp")
        db.commit()
        result = _collect_web(comp, org_id, 100, db)
        assert result == []

    def test_fallback_to_website_url(self, db):
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id, "With Website")
        comp.website_url = "https://example.com"
        db.commit()

        # Mock crawl_domain to return realistic data
        mock_page = MagicMock()
        mock_page.title = "Example Page"
        mock_page.headlines = ["Big Headline"]
        mock_page.offers = ["50% off"]
        mock_page.pricing_blocks = ["$9.99/mo"]
        mock_page.cta_phrases = ["Sign Up Now"]
        mock_page.guarantees = ["30-day money back"]
        mock_page.product_names = ["Widget Pro"]
        mock_page.hero_sections = []
        mock_page.semantic_keywords = ["widget", "pro"]
        mock_page.model_dump.return_value = {"title": "Example Page"}

        mock_report = MagicMock()
        mock_report.pages_crawled = 1

        async def fake_crawl(*args, **kwargs):
            return (
                {"https://example.com": MagicMock()},
                {"https://example.com": mock_page},
                {"https://example.com": "<html></html>"},
                mock_report,
            )

        with patch("src.engines.web_intelligence.crawler_service.crawl_domain", side_effect=fake_crawl):
            result = _collect_web(comp, org_id, 100, db)

        assert len(result) == 1
        item = result[0]
        assert item.item_type == CIItemType.LANDING_PAGE
        assert item.title == "Example Page"
        assert item.url == "https://example.com"
        assert item.canonical_json["competitor"] == "With Website"
        assert "Big Headline" in item.canonical_json["headlines"]

    def test_uses_explicit_domains(self, db):
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id, "Domain Corp")
        comp.website_url = "https://fallback.com"  # Should NOT be used
        _add_domain(db, org_id, comp.id, "https://real-domain.com")
        db.commit()

        mock_page = MagicMock()
        mock_page.title = "Real Domain"
        mock_page.headlines = []
        mock_page.offers = []
        mock_page.pricing_blocks = []
        mock_page.cta_phrases = []
        mock_page.guarantees = []
        mock_page.product_names = []
        mock_page.hero_sections = []
        mock_page.semantic_keywords = []
        mock_page.model_dump.return_value = {"title": "Real Domain"}

        mock_report = MagicMock()
        mock_report.pages_crawled = 1

        captured_domains = []

        async def fake_crawl(domain, **kwargs):
            captured_domains.append(domain)
            return (
                {f"https://{domain}": MagicMock()},
                {f"https://{domain}": mock_page},
                {},
                mock_report,
            )

        with patch("src.engines.web_intelligence.crawler_service.crawl_domain", side_effect=fake_crawl):
            _collect_web(comp, org_id, 100, db)

        assert "https://real-domain.com" in captured_domains
        assert "https://fallback.com" not in captured_domains

    def test_respects_max_items_limit(self, db):
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id, "Many Pages Corp")
        comp.website_url = "https://big-site.com"
        db.commit()

        # Return 5 pages but limit to 2
        pages = {}
        for i in range(5):
            url = f"https://big-site.com/page{i}"
            mock_page = MagicMock()
            mock_page.title = f"Page {i}"
            mock_page.headlines = [f"Headline {i}"]
            mock_page.offers = []
            mock_page.pricing_blocks = []
            mock_page.cta_phrases = []
            mock_page.guarantees = []
            mock_page.product_names = []
            mock_page.hero_sections = []
            mock_page.semantic_keywords = []
            mock_page.model_dump.return_value = {"title": f"Page {i}"}
            pages[url] = mock_page

        mock_report = MagicMock()
        mock_report.pages_crawled = 5

        async def fake_crawl(*args, **kwargs):
            return ({}, pages, {}, mock_report)

        with patch("src.engines.web_intelligence.crawler_service.crawl_domain", side_effect=fake_crawl):
            result = _collect_web(comp, org_id, 2, db)

        assert len(result) == 2

    def test_crawl_error_continues_gracefully(self, db):
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id, "Error Corp")
        comp.website_url = "https://down-site.com"
        db.commit()

        async def failing_crawl(*args, **kwargs):
            raise ConnectionError("DNS resolution failed")

        with patch("src.engines.web_intelligence.crawler_service.crawl_domain", side_effect=failing_crawl):
            result = _collect_web(comp, org_id, 100, db)

        assert result == []

    def test_upsert_deduplicates_same_url(self, db):
        """Second crawl of same URL should update, not duplicate."""
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id, "Dedup Corp")
        comp.website_url = "https://dedup.com"
        db.commit()

        mock_page = MagicMock()
        mock_page.title = "V1"
        mock_page.headlines = ["Old"]
        mock_page.offers = []
        mock_page.pricing_blocks = []
        mock_page.cta_phrases = []
        mock_page.guarantees = []
        mock_page.product_names = []
        mock_page.hero_sections = []
        mock_page.semantic_keywords = []
        mock_page.model_dump.return_value = {"title": "V1"}

        mock_report = MagicMock()
        mock_report.pages_crawled = 1

        async def fake_crawl(*args, **kwargs):
            return (
                {"https://dedup.com": MagicMock()},
                {"https://dedup.com": mock_page},
                {},
                mock_report,
            )

        with patch("src.engines.web_intelligence.crawler_service.crawl_domain", side_effect=fake_crawl):
            _collect_web(comp, org_id, 100, db)

        # Second crawl — title changes
        mock_page.title = "V2"
        mock_page.headlines = ["New"]
        mock_page.model_dump.return_value = {"title": "V2"}

        with patch("src.engines.web_intelligence.crawler_service.crawl_domain", side_effect=fake_crawl):
            _collect_web(comp, org_id, 100, db)

        items = db.query(CICanonicalItem).filter(
            CICanonicalItem.org_id == org_id,
            CICanonicalItem.competitor_id == comp.id,
        ).all()
        assert len(items) == 1
        assert items[0].title == "V2"


class TestCollectMetaAds:

    def test_collects_ads_and_creates_items(self, db):
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id, "Ad Corp")
        db.commit()

        mock_ad = MagicMock()
        mock_ad.id = "ad-001"
        mock_ad.platform = MagicMock(value="meta")
        mock_ad.advertiser = "Ad Corp"
        mock_ad.headline = "Best Product Ever"
        mock_ad.copy = "Buy now and save 50%"
        mock_ad.cta = "Shop Now"
        mock_ad.format = MagicMock(value="image")
        mock_ad.country = "US"
        mock_ad.landing_url = "https://adcorp.com/lp"
        mock_ad.media_url = "https://cdn.adcorp.com/img.jpg"
        mock_ad.fingerprint = "fp_abc123def456"
        mock_ad.model_dump.return_value = {"id": "ad-001", "platform": "meta"}

        mock_report = MagicMock()
        mock_report.ads_collected = 1
        mock_report.ads_new = 1

        mock_engine = MagicMock()

        async def fake_run_source(*args, **kwargs):
            return mock_report

        mock_engine.run_source = fake_run_source
        mock_engine.get_ads.return_value = [mock_ad]

        with patch("src.engines.ads_intelligence.core.ads_engine.AdsIntelligenceEngine", return_value=mock_engine):
            result = _collect_meta_ads(comp, org_id, 100, db)

        assert len(result) == 1
        item = result[0]
        assert item.item_type == CIItemType.AD
        assert item.title == "Best Product Ever"
        assert item.body_text == "Buy now and save 50%"
        assert item.canonical_json["competitor"] == "Ad Corp"
        assert item.canonical_json["fingerprint"] == "fp_abc123def456"

    def test_ads_engine_error_returns_empty(self, db):
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id, "Failing Ads Corp")
        db.commit()

        mock_engine = MagicMock()

        async def failing_run(*args, **kwargs):
            raise ConnectionError("Meta API unreachable")

        mock_engine.run_source = failing_run

        with patch("src.engines.ads_intelligence.core.ads_engine.AdsIntelligenceEngine", return_value=mock_engine):
            result = _collect_meta_ads(comp, org_id, 100, db)

        assert result == []

    def test_respects_max_items_limit(self, db):
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id, "Many Ads Corp")
        db.commit()

        # Create 5 mock ads
        mock_ads = []
        for i in range(5):
            ad = MagicMock()
            ad.id = f"ad-{i:03d}"
            ad.platform = MagicMock(value="meta")
            ad.advertiser = "Many Ads Corp"
            ad.headline = f"Ad {i}"
            ad.copy = f"Copy {i}"
            ad.cta = "Buy"
            ad.format = MagicMock(value="image")
            ad.country = "US"
            ad.landing_url = f"https://example.com/lp{i}"
            ad.media_url = ""
            ad.fingerprint = f"fp_{i:08d}abcdef"
            ad.model_dump.return_value = {"id": f"ad-{i:03d}"}
            mock_ads.append(ad)

        mock_report = MagicMock()
        mock_report.ads_collected = 5
        mock_report.ads_new = 5

        mock_engine = MagicMock()

        async def fake_run_source(*args, **kwargs):
            return mock_report

        mock_engine.run_source = fake_run_source
        mock_engine.get_ads.return_value = mock_ads

        with patch("src.engines.ads_intelligence.core.ads_engine.AdsIntelligenceEngine", return_value=mock_engine):
            result = _collect_meta_ads(comp, org_id, 2, db)

        assert len(result) == 2

    def test_uses_competitor_country_from_meta_json(self, db):
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id, "Argentina Corp")
        comp.meta_json = {"country": "AR"}
        db.commit()

        captured_kwargs = {}
        mock_engine = MagicMock()

        async def fake_run_source(source, query="", country="US"):
            captured_kwargs["country"] = country
            return MagicMock(ads_collected=0, ads_new=0)

        mock_engine.run_source = fake_run_source
        mock_engine.get_ads.return_value = []

        with patch("src.engines.ads_intelligence.core.ads_engine.AdsIntelligenceEngine", return_value=mock_engine):
            _collect_meta_ads(comp, org_id, 100, db)

        assert captured_kwargs["country"] == "AR"

    def test_ad_upsert_deduplicates_by_fingerprint(self, db):
        """Second collection of same ad fingerprint should update, not duplicate."""
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id, "Dedup Ad Corp")
        db.commit()

        mock_ad = MagicMock()
        mock_ad.id = "ad-dedup"
        mock_ad.platform = MagicMock(value="meta")
        mock_ad.advertiser = "Dedup Ad Corp"
        mock_ad.headline = "V1 Headline"
        mock_ad.copy = "V1 copy"
        mock_ad.cta = "Buy"
        mock_ad.format = MagicMock(value="image")
        mock_ad.country = "US"
        mock_ad.landing_url = "https://dedup-ad.com"
        mock_ad.media_url = ""
        mock_ad.fingerprint = "fp_dedup_12345678"
        mock_ad.model_dump.return_value = {"id": "ad-dedup"}

        mock_report = MagicMock()
        mock_report.ads_collected = 1
        mock_report.ads_new = 1

        mock_engine = MagicMock()

        async def fake_run_source(*args, **kwargs):
            return mock_report

        mock_engine.run_source = fake_run_source
        mock_engine.get_ads.return_value = [mock_ad]

        with patch("src.engines.ads_intelligence.core.ads_engine.AdsIntelligenceEngine", return_value=mock_engine):
            _collect_meta_ads(comp, org_id, 100, db)

        # Second pass — headline changes but fingerprint is same
        mock_ad.headline = "V2 Headline"

        with patch("src.engines.ads_intelligence.core.ads_engine.AdsIntelligenceEngine", return_value=mock_engine):
            _collect_meta_ads(comp, org_id, 100, db)

        items = db.query(CICanonicalItem).filter(
            CICanonicalItem.org_id == org_id,
            CICanonicalItem.competitor_id == comp.id,
            CICanonicalItem.item_type == CIItemType.AD,
        ).all()
        assert len(items) == 1
        assert items[0].title == "V2 Headline"


class TestCollectEndToEnd:

    @patch("backend.src.ci.ci_tasks._collect_web")
    def test_ingest_web_calls_collect_web(self, mock_collect, db):
        """Full run_ci_ingest → _collect_web integration."""
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id)
        db.commit()

        mock_item = MagicMock()
        mock_collect.return_value = [mock_item]

        run_ci_ingest(org_id, {"source": "web", "max_competitors": 3, "max_items": 100}, db)

        mock_collect.assert_called_once()
        run = db.query(CIRun).filter(CIRun.org_id == org_id).first()
        assert run.status == CIRunStatus.SUCCEEDED
        assert run.items_collected == 1

    @patch("backend.src.ci.ci_tasks._collect_meta_ads")
    def test_ingest_meta_ads_calls_collect_meta_ads(self, mock_collect, db):
        """Full run_ci_ingest → _collect_meta_ads integration."""
        org_id = _create_org(db)
        comp = _create_competitor(db, org_id)
        db.commit()

        mock_items = [MagicMock(), MagicMock()]
        mock_collect.return_value = mock_items

        run_ci_ingest(org_id, {"source": "meta_ads", "max_competitors": 3, "max_items": 100}, db)

        mock_collect.assert_called_once()
        run = db.query(CIRun).filter(CIRun.org_id == org_id).first()
        assert run.status == CIRunStatus.SUCCEEDED
        assert run.items_collected == 2
