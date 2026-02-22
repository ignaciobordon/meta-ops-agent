"""
Sprint 8 -- Migration 006: Schema Verification Tests.
Verifies that all Sprint 8 models (OnboardingState, OrgTemplate, OrgConfig,
OrgBenchmark, ProductEvent) create their tables correctly and that the
MetaAlert.status column extension works as expected.
~7 tests against an in-memory SQLite database (no FastAPI TestClient).
"""
import os
import pytest
from datetime import datetime
from uuid import uuid4

from sqlalchemy import create_engine, String, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.src.database.models import (
    Base, Organization, OnboardingState, OnboardingStatusEnum,
    OrgTemplate, OrgConfig, OrgBenchmark, ProductEvent,
    MetaAlert, AlertSeverity, MetaAdAccount,
)


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


# ── Tests ────────────────────────────────────────────────────────────────────


class TestSprint8Tables:

    def test_onboarding_state_table_exists(self, db_engine):
        """Verify 'onboarding_states' table is created by Base.metadata.create_all."""
        inspector = inspect(db_engine)
        table_names = inspector.get_table_names()
        assert "onboarding_states" in table_names

    def test_org_template_table_exists(self, db_engine):
        """Verify 'org_templates' table is created by Base.metadata.create_all."""
        inspector = inspect(db_engine)
        table_names = inspector.get_table_names()
        assert "org_templates" in table_names

    def test_org_config_table_exists(self, db_engine):
        """Verify 'org_configs' table is created by Base.metadata.create_all."""
        inspector = inspect(db_engine)
        table_names = inspector.get_table_names()
        assert "org_configs" in table_names

    def test_org_benchmark_table_exists(self, db_engine):
        """Verify 'org_benchmarks' table is created by Base.metadata.create_all."""
        inspector = inspect(db_engine)
        table_names = inspector.get_table_names()
        assert "org_benchmarks" in table_names

    def test_product_event_table_exists(self, db_engine):
        """Verify 'product_events' table is created by Base.metadata.create_all."""
        inspector = inspect(db_engine)
        table_names = inspector.get_table_names()
        assert "product_events" in table_names

    def test_meta_alert_has_status_column(self, db_session):
        """Create a MetaAlert with status='active', verify it saves and reads back."""
        org_id = uuid4()
        org = Organization(id=org_id, name="Test Org", slug="test-org")
        db_session.add(org)
        db_session.commit()

        alert = MetaAlert(
            id=uuid4(),
            org_id=org_id,
            alert_type="ctr_low",
            severity=AlertSeverity.MEDIUM,
            message="Test alert with status",
            status="active",
            detected_at=datetime.utcnow(),
        )
        db_session.add(alert)
        db_session.commit()

        fetched = db_session.query(MetaAlert).filter(
            MetaAlert.org_id == org_id,
        ).first()
        assert fetched is not None
        assert fetched.status == "active"
        assert fetched.message == "Test alert with status"
        assert fetched.severity == AlertSeverity.MEDIUM

    def test_create_all_sprint8_models(self, db_session):
        """Create one instance of each Sprint 8 model, commit, and verify query-back."""
        org_id = uuid4()
        org = Organization(id=org_id, name="Test", slug="test")
        db_session.add(org)

        template = OrgTemplate(
            id=uuid4(),
            slug="test",
            name="Test",
            description="desc",
            vertical="test",
            default_config_json={},
        )
        db_session.add(template)

        state = OnboardingState(
            id=uuid4(),
            org_id=org_id,
            current_step=OnboardingStatusEnum.PENDING,
        )
        db_session.add(state)

        config = OrgConfig(
            id=uuid4(),
            org_id=org_id,
            config_json={"key": "value"},
        )
        db_session.add(config)

        # For OrgBenchmark, need a MetaAdAccount
        ad_acc = MetaAdAccount(
            id=uuid4(),
            org_id=org_id,
            meta_account_id="act_test",
        )
        db_session.add(ad_acc)

        benchmark = OrgBenchmark(
            id=uuid4(),
            org_id=org_id,
            ad_account_id=ad_acc.id,
            metric_name="spend",
            baseline_value=100.0,
            current_value=120.0,
            delta_pct=20.0,
        )
        db_session.add(benchmark)

        event = ProductEvent(
            id=uuid4(),
            org_id=org_id,
            event_name="test_event",
            properties_json={"foo": "bar"},
        )
        db_session.add(event)

        db_session.commit()

        # Verify all can be queried
        assert db_session.query(OnboardingState).count() == 1
        assert db_session.query(OrgTemplate).count() == 1
        assert db_session.query(OrgConfig).count() == 1
        assert db_session.query(OrgBenchmark).count() == 1
        assert db_session.query(ProductEvent).count() == 1
