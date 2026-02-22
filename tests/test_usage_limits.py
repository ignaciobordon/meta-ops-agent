"""
Sprint 4 – BLOQUE C: Usage & Limits Tests
Tests UsageService: plan limits, usage tracking, execution mode enforcement.
Minimum 12 tests covering check_limit, record_usage, enforce_execution_mode,
check_ad_account_limit, and edge cases for canceled/past_due subscriptions.
"""
import os
import pytest
from uuid import uuid4, UUID
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from fastapi import HTTPException

from backend.main import app
from backend.src.database.models import (
    Base, Organization, User, UserOrgRole, RoleEnum,
    Subscription, PlanEnum, SubscriptionStatusEnum, PLAN_LIMITS,
    UsageEvent, MetaConnection, AdAccount,
)
from backend.src.database.session import get_db
from backend.src.middleware.auth import create_access_token, hash_password
from backend.src.services.usage_service import UsageService


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


@pytest.fixture(scope="function")
def seed_org_with_subscription(db_session, override_db):
    """
    Factory fixture: creates Organization, User (admin), UserOrgRole, and Subscription.
    Default plan is TRIAL. Pass plan= and/or status= to customize.
    Returns a callable; call it to get a dict with org_id, user_id, token.
    """
    def _factory(
        plan: PlanEnum = PlanEnum.TRIAL,
        status: SubscriptionStatusEnum = SubscriptionStatusEnum.TRIALING,
    ):
        org_id = uuid4()
        org = Organization(
            id=org_id, name="Usage Test Corp", slug=f"usage-test-{uuid4().hex[:8]}",
            operator_armed=True, created_at=datetime.utcnow(),
        )
        db_session.add(org)

        user_id = uuid4()
        user = User(
            id=user_id,
            email=f"admin-{uuid4().hex[:8]}@test.com",
            name="Test Admin",
            password_hash=hash_password("test-password-123"),
            created_at=datetime.utcnow(),
        )
        db_session.add(user)

        role = UserOrgRole(
            id=uuid4(), user_id=user_id, org_id=org_id,
            role=RoleEnum.ADMIN, assigned_at=datetime.utcnow(),
        )
        db_session.add(role)

        limits = PLAN_LIMITS[plan]
        sub = Subscription(
            id=uuid4(), org_id=org_id,
            plan=plan, status=status,
            max_ad_accounts=limits["max_ad_accounts"],
            max_decisions_per_month=limits["max_decisions_per_month"],
            max_creatives_per_month=limits["max_creatives_per_month"],
            allow_live_execution=limits["allow_live_execution"],
            created_at=datetime.utcnow(),
        )
        db_session.add(sub)
        db_session.commit()

        token = create_access_token(
            user_id=str(user_id),
            email=user.email,
            role="admin",
            org_id=str(org_id),
        )

        return {
            "org_id": str(org_id),
            "user_id": str(user_id),
            "token": token,
        }

    return _factory


# ── Tests: check_limit ───────────────────────────────────────────────────────


class TestCheckLimit:

    def test_decision_within_limit_allowed(self, db_session, seed_org_with_subscription):
        """TRIAL plan allows decision_create when usage is under the 50/month limit."""
        data = seed_org_with_subscription(plan=PlanEnum.TRIAL)
        svc = UsageService(db_session)

        result = svc.check_limit(data["org_id"], "decision_create")

        assert result["allowed"] is True
        assert result["current"] == 0
        assert result["limit"] == PLAN_LIMITS[PlanEnum.TRIAL]["max_decisions_per_month"]
        assert result["plan"] == "trial"

    def test_decision_over_limit_blocked(self, db_session, seed_org_with_subscription):
        """TRIAL plan blocks decision_create when usage reaches the 50/month limit (403)."""
        data = seed_org_with_subscription(plan=PlanEnum.TRIAL)
        org_uuid = UUID(data["org_id"])
        svc = UsageService(db_session)

        # Seed usage at the TRIAL limit
        period_start = UsageService._current_period_start()
        db_session.add(UsageEvent(
            id=uuid4(), org_id=org_uuid,
            event_type="decision_create", count=50,
            period_start=period_start,
            created_at=datetime.now(timezone.utc),
        ))
        db_session.flush()

        with pytest.raises(HTTPException) as exc_info:
            svc.check_limit(data["org_id"], "decision_create")

        assert exc_info.value.status_code == 403
        assert "limit reached" in exc_info.value.detail.lower()

    def test_creative_within_limit_allowed(self, db_session, seed_org_with_subscription):
        """TRIAL plan allows creative_generate when usage is under the 30/month limit."""
        data = seed_org_with_subscription(plan=PlanEnum.TRIAL)
        svc = UsageService(db_session)

        result = svc.check_limit(data["org_id"], "creative_generate")

        assert result["allowed"] is True
        assert result["current"] == 0
        assert result["limit"] == PLAN_LIMITS[PlanEnum.TRIAL]["max_creatives_per_month"]
        assert result["plan"] == "trial"

    def test_creative_over_limit_blocked(self, db_session, seed_org_with_subscription):
        """TRIAL plan blocks creative_generate when usage reaches the 30/month limit (403)."""
        data = seed_org_with_subscription(plan=PlanEnum.TRIAL)
        org_uuid = UUID(data["org_id"])
        svc = UsageService(db_session)

        period_start = UsageService._current_period_start()
        db_session.add(UsageEvent(
            id=uuid4(), org_id=org_uuid,
            event_type="creative_generate", count=30,
            period_start=period_start,
            created_at=datetime.now(timezone.utc),
        ))
        db_session.flush()

        with pytest.raises(HTTPException) as exc_info:
            svc.check_limit(data["org_id"], "creative_generate")

        assert exc_info.value.status_code == 403
        assert "limit reached" in exc_info.value.detail.lower()


# ── Tests: check_ad_account_limit ────────────────────────────────────────────


class TestAdAccountLimit:

    def test_ad_account_within_limit_allowed(self, db_session, seed_org_with_subscription):
        """TRIAL plan allows adding ad accounts when count is under the max (1)."""
        data = seed_org_with_subscription(plan=PlanEnum.TRIAL)
        svc = UsageService(db_session)

        result = svc.check_ad_account_limit(data["org_id"])

        assert result["allowed"] is True
        assert result["current"] == 0
        assert result["limit"] == PLAN_LIMITS[PlanEnum.TRIAL]["max_ad_accounts"]
        assert result["plan"] == "trial"

    def test_ad_account_over_limit_blocked(self, db_session, seed_org_with_subscription):
        """TRIAL plan blocks adding ad accounts when limit (1) is reached (403)."""
        data = seed_org_with_subscription(plan=PlanEnum.TRIAL)
        org_uuid = UUID(data["org_id"])
        svc = UsageService(db_session)

        # Create a MetaConnection + AdAccount to fill the TRIAL limit of 1
        conn_id = uuid4()
        conn = MetaConnection(
            id=conn_id, org_id=org_uuid,
            access_token_encrypted="enc_test", status="active",
            connected_at=datetime.utcnow(),
        )
        db_session.add(conn)

        ad_account = AdAccount(
            id=uuid4(), connection_id=conn_id,
            meta_ad_account_id=f"act_limit_{uuid4().hex[:8]}",
            name="Limit Test Account",
            currency="USD", synced_at=datetime.utcnow(),
        )
        db_session.add(ad_account)
        db_session.flush()

        with pytest.raises(HTTPException) as exc_info:
            svc.check_ad_account_limit(data["org_id"])

        assert exc_info.value.status_code == 403
        assert "ad account limit reached" in exc_info.value.detail.lower()


# ── Tests: enforce_execution_mode ────────────────────────────────────────────


class TestEnforceExecutionMode:

    def test_trial_forces_dry_run_on_execute(self, db_session, seed_org_with_subscription):
        """TRIAL subscription forces dry_run=True even when user requests live execution."""
        data = seed_org_with_subscription(plan=PlanEnum.TRIAL)
        svc = UsageService(db_session)

        result = svc.enforce_execution_mode(data["org_id"], requested_dry_run=False)

        assert result is True  # Forced to dry_run

    def test_pro_allows_live_execution(self, db_session, seed_org_with_subscription):
        """PRO subscription allows live execution (dry_run=False passes through)."""
        data = seed_org_with_subscription(
            plan=PlanEnum.PRO,
            status=SubscriptionStatusEnum.ACTIVE,
        )
        svc = UsageService(db_session)

        result = svc.enforce_execution_mode(data["org_id"], requested_dry_run=False)

        assert result is False  # Live execution allowed

    def test_pro_respects_dry_run_request(self, db_session, seed_org_with_subscription):
        """PRO subscription respects dry_run=True when explicitly requested."""
        data = seed_org_with_subscription(
            plan=PlanEnum.PRO,
            status=SubscriptionStatusEnum.ACTIVE,
        )
        svc = UsageService(db_session)

        result = svc.enforce_execution_mode(data["org_id"], requested_dry_run=True)

        assert result is True  # User requested dry_run, honored


# ── Tests: Subscription status enforcement ───────────────────────────────────


class TestSubscriptionStatus:

    def test_canceled_blocks_writes(self, db_session, seed_org_with_subscription):
        """Canceled subscription raises 403 on check_limit (write operations blocked)."""
        data = seed_org_with_subscription(
            plan=PlanEnum.PRO,
            status=SubscriptionStatusEnum.CANCELED,
        )
        svc = UsageService(db_session)

        with pytest.raises(HTTPException) as exc_info:
            svc.check_limit(data["org_id"], "decision_create")

        assert exc_info.value.status_code == 403
        assert "canceled" in exc_info.value.detail.lower()

    def test_past_due_blocks_writes(self, db_session, seed_org_with_subscription):
        """Past-due subscription raises 402 on check_limit (payment required)."""
        data = seed_org_with_subscription(
            plan=PlanEnum.PRO,
            status=SubscriptionStatusEnum.PAST_DUE,
        )
        svc = UsageService(db_session)

        with pytest.raises(HTTPException) as exc_info:
            svc.check_limit(data["org_id"], "decision_create")

        assert exc_info.value.status_code == 402
        assert "past due" in exc_info.value.detail.lower()

    def test_canceled_blocks_execution(self, db_session, seed_org_with_subscription):
        """Canceled subscription raises 403 on enforce_execution_mode."""
        data = seed_org_with_subscription(
            plan=PlanEnum.PRO,
            status=SubscriptionStatusEnum.CANCELED,
        )
        svc = UsageService(db_session)

        with pytest.raises(HTTPException) as exc_info:
            svc.enforce_execution_mode(data["org_id"], requested_dry_run=True)

        assert exc_info.value.status_code == 403
        assert "canceled" in exc_info.value.detail.lower()

    def test_past_due_blocks_execution(self, db_session, seed_org_with_subscription):
        """Past-due subscription raises 402 on enforce_execution_mode."""
        data = seed_org_with_subscription(
            plan=PlanEnum.PRO,
            status=SubscriptionStatusEnum.PAST_DUE,
        )
        svc = UsageService(db_session)

        with pytest.raises(HTTPException) as exc_info:
            svc.enforce_execution_mode(data["org_id"], requested_dry_run=True)

        assert exc_info.value.status_code == 402
        assert "past due" in exc_info.value.detail.lower()


# ── Tests: record_usage & counter behavior ───────────────────────────────────


class TestRecordUsage:

    def test_usage_counter_increments(self, db_session, seed_org_with_subscription):
        """Calling record_usage twice increments the counter to 2."""
        data = seed_org_with_subscription(plan=PlanEnum.TRIAL)
        org_uuid = UUID(data["org_id"])
        svc = UsageService(db_session)

        svc.record_usage(data["org_id"], "decision_create")
        svc.record_usage(data["org_id"], "decision_create")

        period_start = UsageService._current_period_start()
        usage = db_session.query(UsageEvent).filter(
            UsageEvent.org_id == org_uuid,
            UsageEvent.event_type == "decision_create",
            UsageEvent.period_start == period_start,
        ).first()

        assert usage is not None
        assert usage.count == 2

    def test_usage_resets_new_month(self, db_session, seed_org_with_subscription):
        """Usage from a previous month does not affect current month; new record is created."""
        data = seed_org_with_subscription(plan=PlanEnum.TRIAL)
        org_uuid = UUID(data["org_id"])
        svc = UsageService(db_session)

        # Insert usage for a previous period (January 2024)
        old_period = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        db_session.add(UsageEvent(
            id=uuid4(), org_id=org_uuid,
            event_type="decision_create", count=45,
            period_start=old_period,
            created_at=datetime.now(timezone.utc),
        ))
        db_session.flush()

        # Record new usage — should create a new entry for the current period
        svc.record_usage(data["org_id"], "decision_create")

        current_period = UsageService._current_period_start()
        current_usage = db_session.query(UsageEvent).filter(
            UsageEvent.org_id == org_uuid,
            UsageEvent.event_type == "decision_create",
            UsageEvent.period_start == current_period,
        ).first()

        assert current_usage is not None
        assert current_usage.count == 1  # Fresh counter for the new period

        # Old period usage remains untouched
        old_usage = db_session.query(UsageEvent).filter(
            UsageEvent.org_id == org_uuid,
            UsageEvent.event_type == "decision_create",
            UsageEvent.period_start == old_period,
        ).first()

        assert old_usage is not None
        assert old_usage.count == 45

    def test_record_usage_different_event_types_independent(self, db_session, seed_org_with_subscription):
        """Usage counters for different event types are tracked independently."""
        data = seed_org_with_subscription(plan=PlanEnum.TRIAL)
        org_uuid = UUID(data["org_id"])
        svc = UsageService(db_session)

        svc.record_usage(data["org_id"], "decision_create")
        svc.record_usage(data["org_id"], "decision_create")
        svc.record_usage(data["org_id"], "creative_generate")

        period_start = UsageService._current_period_start()

        decision_usage = db_session.query(UsageEvent).filter(
            UsageEvent.org_id == org_uuid,
            UsageEvent.event_type == "decision_create",
            UsageEvent.period_start == period_start,
        ).first()

        creative_usage = db_session.query(UsageEvent).filter(
            UsageEvent.org_id == org_uuid,
            UsageEvent.event_type == "creative_generate",
            UsageEvent.period_start == period_start,
        ).first()

        assert decision_usage.count == 2
        assert creative_usage.count == 1


# ── Tests: No subscription ──────────────────────────────────────────────────


class TestNoSubscription:

    def test_check_limit_no_subscription_raises_403(self, db_session, override_db):
        """Org without any subscription raises 403 on check_limit."""
        org_id = uuid4()
        org = Organization(
            id=org_id, name="No Sub Org", slug="no-sub-org",
            operator_armed=True, created_at=datetime.utcnow(),
        )
        db_session.add(org)
        db_session.commit()

        svc = UsageService(db_session)

        with pytest.raises(HTTPException) as exc_info:
            svc.check_limit(str(org_id), "decision_create")

        assert exc_info.value.status_code == 403
        assert "no active subscription" in exc_info.value.detail.lower()
