"""
Stripe Webhook Tests
Verifies webhook signature validation, event dispatch, and subscription
lifecycle updates for all supported Stripe event types.
"""
import os
import pytest
import stripe
from uuid import uuid4, UUID
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.main import app
from backend.src.database.models import (
    Base, Organization, Subscription, PlanEnum, SubscriptionStatusEnum, PLAN_LIMITS,
)
from backend.src.database.session import get_db


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


@pytest.fixture
def client(override_db):
    return TestClient(app)


@pytest.fixture
def org_with_subscription(db_session, override_db):
    """Create an organization with a TRIAL subscription linked to Stripe IDs."""
    org_id = uuid4()
    org = Organization(
        id=org_id,
        name="Test Org",
        slug="test-org",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(org)

    sub = Subscription(
        id=uuid4(),
        org_id=org_id,
        plan=PlanEnum.TRIAL,
        status=SubscriptionStatusEnum.TRIALING,
        stripe_subscription_id="sub_test123",
        stripe_customer_id="cus_test123",
        max_ad_accounts=1,
        max_decisions_per_month=50,
        max_creatives_per_month=30,
        allow_live_execution=False,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(sub)
    db_session.commit()

    return {"org_id": str(org_id), "sub_id": str(sub.id)}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _build_checkout_event(org_id: str, plan: str = "pro") -> dict:
    """Build a mock checkout.session.completed event."""
    return {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "metadata": {"org_id": org_id, "plan": plan},
                "customer": "cus_test123",
                "subscription": "sub_test123",
            }
        },
    }


def _build_subscription_updated_event(
    status: str = "active",
    period_start: int = 1700000000,
    period_end: int = 1703000000,
) -> dict:
    """Build a mock customer.subscription.updated event."""
    return {
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_test123",
                "status": status,
                "current_period_start": period_start,
                "current_period_end": period_end,
            }
        },
    }


def _build_subscription_deleted_event() -> dict:
    """Build a mock customer.subscription.deleted event."""
    return {
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_test123",
                "status": "canceled",
                "current_period_start": 1700000000,
                "current_period_end": 1703000000,
            }
        },
    }


def _build_invoice_failed_event(customer_id: str = "cus_test123") -> dict:
    """Build a mock invoice.payment_failed event."""
    return {
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "id": "in_test456",
                "customer": customer_id,
                "subscription": "sub_test123",
                "amount_due": 4900,
                "currency": "usd",
            }
        },
    }


# ── Tests ────────────────────────────────────────────────────────────────────


class TestStripeWebhook:

    @patch("backend.src.services.stripe_service.stripe.Webhook.construct_event")
    def test_webhook_valid_signature(self, mock_construct, client, org_with_subscription):
        """Valid signature returns 200 with status ok."""
        mock_construct.return_value = _build_checkout_event(org_with_subscription["org_id"])

        resp = client.post(
            "/api/billing/webhook",
            content=b'{"test": "payload"}',
            headers={"Stripe-Signature": "t=123,v1=abc"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["event_type"] == "checkout.session.completed"
        mock_construct.assert_called_once()

    @patch("backend.src.services.stripe_service.stripe.Webhook.construct_event")
    def test_webhook_invalid_signature(self, mock_construct, client):
        """Invalid signature raises ValueError via service, returns 400."""
        mock_construct.side_effect = stripe.error.SignatureVerificationError(
            "bad sig", "sig_header"
        )

        resp = client.post(
            "/api/billing/webhook",
            content=b'{"test": "payload"}',
            headers={"Stripe-Signature": "t=123,v1=invalid"},
        )

        assert resp.status_code == 400
        assert "signature" in resp.json()["detail"].lower()

    @patch("backend.src.services.stripe_service.stripe.Webhook.construct_event")
    def test_webhook_checkout_completed(self, mock_construct, client, org_with_subscription, db_session):
        """checkout.session.completed activates subscription with PRO limits."""
        org_id = org_with_subscription["org_id"]
        mock_construct.return_value = _build_checkout_event(org_id, plan="pro")

        resp = client.post(
            "/api/billing/webhook",
            content=b'{"type": "checkout.session.completed"}',
            headers={"Stripe-Signature": "t=123,v1=valid"},
        )

        assert resp.status_code == 200

        # Refresh session to see changes committed by the service
        db_session.expire_all()
        sub = db_session.query(Subscription).filter(
            Subscription.org_id == UUID(org_id)
        ).first()

        assert sub is not None
        assert sub.plan == PlanEnum.PRO
        assert sub.status == SubscriptionStatusEnum.ACTIVE
        assert sub.stripe_customer_id == "cus_test123"
        assert sub.stripe_subscription_id == "sub_test123"

        # Verify PRO limits applied
        pro_limits = PLAN_LIMITS[PlanEnum.PRO]
        assert sub.max_ad_accounts == pro_limits["max_ad_accounts"]
        assert sub.max_decisions_per_month == pro_limits["max_decisions_per_month"]
        assert sub.max_creatives_per_month == pro_limits["max_creatives_per_month"]
        assert sub.allow_live_execution == pro_limits["allow_live_execution"]

    @patch("backend.src.services.stripe_service.stripe.Webhook.construct_event")
    def test_webhook_subscription_updated(self, mock_construct, client, org_with_subscription, db_session):
        """customer.subscription.updated syncs status and billing period."""
        mock_construct.return_value = _build_subscription_updated_event(
            status="active",
            period_start=1700000000,
            period_end=1703000000,
        )

        resp = client.post(
            "/api/billing/webhook",
            content=b'{"type": "customer.subscription.updated"}',
            headers={"Stripe-Signature": "t=123,v1=valid"},
        )

        assert resp.status_code == 200

        db_session.expire_all()
        sub = db_session.query(Subscription).filter(
            Subscription.stripe_subscription_id == "sub_test123"
        ).first()

        assert sub is not None
        assert sub.status == SubscriptionStatusEnum.ACTIVE
        assert sub.current_period_start is not None
        assert sub.current_period_end is not None
        # Verify timestamps were converted from unix epoch (SQLite drops tzinfo)
        expected_start = datetime.fromtimestamp(1700000000, tz=timezone.utc).replace(tzinfo=None)
        expected_end = datetime.fromtimestamp(1703000000, tz=timezone.utc).replace(tzinfo=None)
        actual_start = sub.current_period_start.replace(tzinfo=None) if sub.current_period_start.tzinfo else sub.current_period_start
        actual_end = sub.current_period_end.replace(tzinfo=None) if sub.current_period_end.tzinfo else sub.current_period_end
        assert actual_start == expected_start
        assert actual_end == expected_end

    @patch("backend.src.services.stripe_service.stripe.Webhook.construct_event")
    def test_webhook_subscription_deleted(self, mock_construct, client, org_with_subscription, db_session):
        """customer.subscription.deleted marks subscription as CANCELED."""
        mock_construct.return_value = _build_subscription_deleted_event()

        resp = client.post(
            "/api/billing/webhook",
            content=b'{"type": "customer.subscription.deleted"}',
            headers={"Stripe-Signature": "t=123,v1=valid"},
        )

        assert resp.status_code == 200

        db_session.expire_all()
        sub = db_session.query(Subscription).filter(
            Subscription.stripe_subscription_id == "sub_test123"
        ).first()

        assert sub is not None
        assert sub.status == SubscriptionStatusEnum.CANCELED

    @patch("backend.src.services.stripe_service.stripe.Webhook.construct_event")
    def test_webhook_invoice_failed(self, mock_construct, client, org_with_subscription, db_session):
        """invoice.payment_failed marks subscription as PAST_DUE."""
        mock_construct.return_value = _build_invoice_failed_event(customer_id="cus_test123")

        resp = client.post(
            "/api/billing/webhook",
            content=b'{"type": "invoice.payment_failed"}',
            headers={"Stripe-Signature": "t=123,v1=valid"},
        )

        assert resp.status_code == 200

        db_session.expire_all()
        sub = db_session.query(Subscription).filter(
            Subscription.stripe_customer_id == "cus_test123"
        ).first()

        assert sub is not None
        assert sub.status == SubscriptionStatusEnum.PAST_DUE

    @patch("backend.src.services.stripe_service.stripe.Webhook.construct_event")
    def test_webhook_unknown_event_ignored(self, mock_construct, client, org_with_subscription, db_session):
        """Unknown event type returns 200 without modifying the database."""
        # Capture the original subscription state before the webhook
        sub_before = db_session.query(Subscription).filter(
            Subscription.stripe_subscription_id == "sub_test123"
        ).first()
        original_status = sub_before.status
        original_plan = sub_before.plan

        mock_construct.return_value = {
            "type": "unknown.event",
            "data": {
                "object": {"id": "obj_unknown"},
            },
        }

        resp = client.post(
            "/api/billing/webhook",
            content=b'{"type": "unknown.event"}',
            headers={"Stripe-Signature": "t=123,v1=valid"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["event_type"] == "unknown.event"

        # Verify no changes to the subscription
        db_session.expire_all()
        sub_after = db_session.query(Subscription).filter(
            Subscription.stripe_subscription_id == "sub_test123"
        ).first()

        assert sub_after.status == original_status
        assert sub_after.plan == original_plan

    @patch("backend.src.services.stripe_service.stripe.Webhook.construct_event")
    def test_webhook_idempotent(self, mock_construct, client, org_with_subscription, db_session):
        """Sending checkout.session.completed twice results in only one subscription."""
        org_id = org_with_subscription["org_id"]
        mock_construct.return_value = _build_checkout_event(org_id, plan="pro")

        # First call
        resp1 = client.post(
            "/api/billing/webhook",
            content=b'{"type": "checkout.session.completed"}',
            headers={"Stripe-Signature": "t=123,v1=valid"},
        )
        assert resp1.status_code == 200

        # Second call — same event
        resp2 = client.post(
            "/api/billing/webhook",
            content=b'{"type": "checkout.session.completed"}',
            headers={"Stripe-Signature": "t=123,v1=valid"},
        )
        assert resp2.status_code == 200

        # Verify only one subscription exists for this org
        db_session.expire_all()
        subs = db_session.query(Subscription).filter(
            Subscription.org_id == UUID(org_id)
        ).all()

        assert len(subs) == 1
        assert subs[0].plan == PlanEnum.PRO
        assert subs[0].status == SubscriptionStatusEnum.ACTIVE

    @patch("backend.src.services.stripe_service.stripe.Webhook.construct_event")
    def test_webhook_checkout_creates_subscription_when_none_exists(
        self, mock_construct, client, db_session, override_db
    ):
        """checkout.session.completed creates a new subscription if org has none."""
        # Create an org WITHOUT a subscription
        org_id = uuid4()
        org = Organization(
            id=org_id,
            name="New Org",
            slug="new-org",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(org)
        db_session.commit()

        # Verify no subscription exists
        assert db_session.query(Subscription).filter(
            Subscription.org_id == org_id
        ).first() is None

        mock_construct.return_value = _build_checkout_event(str(org_id), plan="pro")

        resp = client.post(
            "/api/billing/webhook",
            content=b'{"type": "checkout.session.completed"}',
            headers={"Stripe-Signature": "t=123,v1=valid"},
        )

        assert resp.status_code == 200

        db_session.expire_all()
        sub = db_session.query(Subscription).filter(
            Subscription.org_id == org_id
        ).first()

        assert sub is not None
        assert sub.plan == PlanEnum.PRO
        assert sub.status == SubscriptionStatusEnum.ACTIVE
        assert sub.stripe_customer_id == "cus_test123"
        assert sub.stripe_subscription_id == "sub_test123"
        assert sub.allow_live_execution is True

    @patch("backend.src.services.stripe_service.stripe.Webhook.construct_event")
    def test_webhook_subscription_updated_not_found(
        self, mock_construct, client, db_session, override_db
    ):
        """subscription.updated for unknown stripe ID returns 200 but makes no DB changes."""
        mock_construct.return_value = {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_nonexistent",
                    "status": "active",
                    "current_period_start": 1700000000,
                    "current_period_end": 1703000000,
                },
            },
        }

        resp = client.post(
            "/api/billing/webhook",
            content=b'{"type": "customer.subscription.updated"}',
            headers={"Stripe-Signature": "t=123,v1=valid"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

        # Verify no subscription was created
        sub = db_session.query(Subscription).filter(
            Subscription.stripe_subscription_id == "sub_nonexistent"
        ).first()
        assert sub is None

    @patch("backend.src.services.stripe_service.stripe.Webhook.construct_event")
    def test_webhook_missing_signature_header(self, mock_construct, client):
        """Request without Stripe-Signature header still calls construct_event (which would fail)."""
        mock_construct.side_effect = stripe.error.SignatureVerificationError(
            "No signature header", ""
        )

        resp = client.post(
            "/api/billing/webhook",
            content=b'{"test": "payload"}',
        )

        assert resp.status_code == 400

    @patch("backend.src.services.stripe_service.stripe.Webhook.construct_event")
    def test_webhook_subscription_deleted_not_found(
        self, mock_construct, client, db_session, override_db
    ):
        """subscription.deleted for unknown stripe ID returns 200 gracefully."""
        mock_construct.return_value = {
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": "sub_nonexistent",
                    "status": "canceled",
                    "current_period_start": 1700000000,
                    "current_period_end": 1703000000,
                },
            },
        }

        resp = client.post(
            "/api/billing/webhook",
            content=b'{"type": "customer.subscription.deleted"}',
            headers={"Stripe-Signature": "t=123,v1=valid"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["event_type"] == "customer.subscription.deleted"
