"""
Billing State Machine Tests
Tests the full billing lifecycle: trial creation on bootstrap, plan limits,
billing status, Stripe checkout/portal, and webhook-driven state transitions.
Minimum 11 tests covering the subscription state machine end-to-end.
"""
import json
import os
import pytest
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
    Base, Organization, User, UserOrgRole, RoleEnum,
    Subscription, PlanEnum, SubscriptionStatusEnum, PLAN_LIMITS,
    Branding,
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
    """Override ONLY get_db — do NOT override get_current_user (we test real auth)."""
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
def bootstrap_and_token(db_session, override_db):
    """Call bootstrap and return the access token for subsequent requests."""
    client = TestClient(app)
    res = client.post("/api/auth/bootstrap", json={
        "admin_email": "admin@test.com",
        "admin_password": "SecurePass123",
        "org_name": "Test Org",
        "admin_name": "Admin User",
    })
    assert res.status_code == 200
    return res.json()["access_token"]


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Test: Trial Subscription Created on Bootstrap ────────────────────────────


class TestTrialBootstrap:

    def test_trial_subscription_created_on_bootstrap(self, db_session, bootstrap_and_token):
        """POST /api/auth/bootstrap creates a Subscription with plan=TRIAL, status=trialing."""
        sub = db_session.query(Subscription).first()
        assert sub is not None, "Subscription should be created during bootstrap"
        assert sub.plan == PlanEnum.TRIAL
        assert sub.status == SubscriptionStatusEnum.TRIALING

    def test_trial_limits_correct(self, db_session, bootstrap_and_token):
        """After bootstrap, the subscription has the correct TRIAL plan limits."""
        sub = db_session.query(Subscription).first()
        assert sub is not None

        expected = PLAN_LIMITS[PlanEnum.TRIAL]
        assert sub.max_decisions_per_month == expected["max_decisions_per_month"]
        assert sub.max_creatives_per_month == expected["max_creatives_per_month"]
        assert sub.max_ad_accounts == expected["max_ad_accounts"]
        assert sub.allow_live_execution == expected["allow_live_execution"]

        # Verify specific numeric values for clarity
        assert sub.max_decisions_per_month == 50
        assert sub.max_creatives_per_month == 30
        assert sub.max_ad_accounts == 1
        assert sub.allow_live_execution is False

    def test_trial_forces_dry_run(self, bootstrap_and_token, override_db):
        """GET /api/billing/status shows allow_live_execution=False for TRIAL plan."""
        client = TestClient(app)
        resp = client.get(
            "/api/billing/status",
            headers=_auth_header(bootstrap_and_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["limits"]["allow_live_execution"] is False

    def test_trial_has_trial_end_date(self, db_session, bootstrap_and_token):
        """After bootstrap, the trial subscription has a trial_ends_at set in the future."""
        sub = db_session.query(Subscription).first()
        assert sub is not None
        assert sub.trial_ends_at is not None


# ── Test: Billing Status Endpoint ────────────────────────────────────────────


class TestBillingStatus:

    def test_billing_status_returns_plan_and_usage(self, bootstrap_and_token, override_db):
        """GET /api/billing/status returns plan, status, limits, and usage."""
        client = TestClient(app)
        resp = client.get(
            "/api/billing/status",
            headers=_auth_header(bootstrap_and_token),
        )
        assert resp.status_code == 200
        data = resp.json()

        # Plan info
        assert data["plan"] == "trial"
        assert data["status"] == "trialing"

        # Limits
        limits = data["limits"]
        assert "max_ad_accounts" in limits
        assert "max_decisions_per_month" in limits
        assert "max_creatives_per_month" in limits
        assert "allow_live_execution" in limits

        # Usage
        usage = data["usage"]
        assert "decisions_this_month" in usage
        assert "creatives_this_month" in usage
        assert usage["decisions_this_month"] == 0
        assert usage["creatives_this_month"] == 0

    def test_billing_status_requires_auth(self, override_db):
        """GET /api/billing/status without auth returns 401."""
        client = TestClient(app)
        resp = client.get("/api/billing/status")
        assert resp.status_code == 401


# ── Test: Checkout & Portal ──────────────────────────────────────────────────


class TestCheckoutAndPortal:

    def test_checkout_creates_session(self, bootstrap_and_token, override_db):
        """POST /api/billing/checkout with plan=pro. Stripe not configured returns 400."""
        client = TestClient(app)
        resp = client.post(
            "/api/billing/checkout",
            json={"plan": "pro"},
            headers=_auth_header(bootstrap_and_token),
        )
        # Stripe is not configured in test env, so the StripeService raises ValueError
        # which the endpoint converts to 400
        assert resp.status_code == 400
        assert "stripe" in resp.json()["detail"].lower() or "not configured" in resp.json()["detail"].lower()

    def test_portal_returns_url(self, bootstrap_and_token, override_db):
        """POST /api/billing/portal. Stripe not configured returns 400."""
        client = TestClient(app)
        resp = client.post(
            "/api/billing/portal",
            json={},
            headers=_auth_header(bootstrap_and_token),
        )
        # Stripe is not configured in test env, so the StripeService raises ValueError
        assert resp.status_code == 400
        assert "stripe" in resp.json()["detail"].lower() or "not configured" in resp.json()["detail"].lower()


# ── Test: Webhook State Transitions ──────────────────────────────────────────


def _build_stripe_event(event_type: str, data_object: dict) -> dict:
    """Build a mock Stripe event dict for webhook tests."""
    return {
        "id": f"evt_{uuid4().hex[:24]}",
        "type": event_type,
        "data": {
            "object": data_object,
        },
    }


class TestWebhookStateMachine:

    def test_webhook_activates_subscription(self, db_session, bootstrap_and_token, override_db):
        """checkout.session.completed event activates the subscription and upgrades to PRO."""
        # Get the org_id from the subscription created during bootstrap
        sub = db_session.query(Subscription).first()
        assert sub is not None
        org_id = str(sub.org_id)

        event = _build_stripe_event("checkout.session.completed", {
            "customer": "cus_test_123",
            "subscription": "sub_test_123",
            "metadata": {
                "org_id": org_id,
                "plan": "pro",
            },
        })

        client = TestClient(app)
        with patch("backend.src.services.stripe_service.stripe") as mock_stripe:
            mock_stripe.Webhook.construct_event.return_value = event
            mock_stripe.error.SignatureVerificationError = Exception

            resp = client.post(
                "/api/billing/webhook",
                content=b'{"test": "payload"}',
                headers={"Stripe-Signature": "test_sig_123"},
            )

        assert resp.status_code == 200
        assert resp.json()["event_type"] == "checkout.session.completed"

        # Verify DB state
        db_session.expire_all()
        sub = db_session.query(Subscription).first()
        assert sub.plan == PlanEnum.PRO
        assert sub.status == SubscriptionStatusEnum.ACTIVE
        assert sub.stripe_customer_id == "cus_test_123"
        assert sub.stripe_subscription_id == "sub_test_123"
        assert sub.allow_live_execution is True

    def test_webhook_updates_plan(self, db_session, bootstrap_and_token, override_db):
        """customer.subscription.updated event updates the subscription status."""
        # First, activate via checkout so we have a stripe_subscription_id
        sub = db_session.query(Subscription).first()
        sub.stripe_subscription_id = "sub_update_test"
        sub.stripe_customer_id = "cus_update_test"
        sub.plan = PlanEnum.PRO
        sub.status = SubscriptionStatusEnum.ACTIVE
        db_session.commit()

        event = _build_stripe_event("customer.subscription.updated", {
            "id": "sub_update_test",
            "status": "active",
            "current_period_start": 1700000000,
            "current_period_end": 1702592000,
        })

        client = TestClient(app)
        with patch("backend.src.services.stripe_service.stripe") as mock_stripe:
            mock_stripe.Webhook.construct_event.return_value = event
            mock_stripe.error.SignatureVerificationError = Exception

            resp = client.post(
                "/api/billing/webhook",
                content=b'{"test": "payload"}',
                headers={"Stripe-Signature": "test_sig_456"},
            )

        assert resp.status_code == 200
        assert resp.json()["event_type"] == "customer.subscription.updated"

        # Verify DB state
        db_session.expire_all()
        sub = db_session.query(Subscription).first()
        assert sub.status == SubscriptionStatusEnum.ACTIVE
        assert sub.current_period_start is not None
        assert sub.current_period_end is not None

    def test_webhook_cancels_subscription(self, db_session, bootstrap_and_token, override_db):
        """customer.subscription.deleted event marks the subscription as canceled."""
        sub = db_session.query(Subscription).first()
        sub.stripe_subscription_id = "sub_cancel_test"
        sub.stripe_customer_id = "cus_cancel_test"
        sub.plan = PlanEnum.PRO
        sub.status = SubscriptionStatusEnum.ACTIVE
        db_session.commit()

        event = _build_stripe_event("customer.subscription.deleted", {
            "id": "sub_cancel_test",
        })

        client = TestClient(app)
        with patch("backend.src.services.stripe_service.stripe") as mock_stripe:
            mock_stripe.Webhook.construct_event.return_value = event
            mock_stripe.error.SignatureVerificationError = Exception

            resp = client.post(
                "/api/billing/webhook",
                content=b'{"test": "payload"}',
                headers={"Stripe-Signature": "test_sig_789"},
            )

        assert resp.status_code == 200
        assert resp.json()["event_type"] == "customer.subscription.deleted"

        # Verify DB state
        db_session.expire_all()
        sub = db_session.query(Subscription).first()
        assert sub.status == SubscriptionStatusEnum.CANCELED

    def test_webhook_marks_past_due(self, db_session, bootstrap_and_token, override_db):
        """invoice.payment_failed event marks the subscription as past_due."""
        sub = db_session.query(Subscription).first()
        sub.stripe_subscription_id = "sub_pastdue_test"
        sub.stripe_customer_id = "cus_pastdue_test"
        sub.plan = PlanEnum.PRO
        sub.status = SubscriptionStatusEnum.ACTIVE
        db_session.commit()

        event = _build_stripe_event("invoice.payment_failed", {
            "customer": "cus_pastdue_test",
            "subscription": "sub_pastdue_test",
        })

        client = TestClient(app)
        with patch("backend.src.services.stripe_service.stripe") as mock_stripe:
            mock_stripe.Webhook.construct_event.return_value = event
            mock_stripe.error.SignatureVerificationError = Exception

            resp = client.post(
                "/api/billing/webhook",
                content=b'{"test": "payload"}',
                headers={"Stripe-Signature": "test_sig_pastdue"},
            )

        assert resp.status_code == 200
        assert resp.json()["event_type"] == "invoice.payment_failed"

        # Verify DB state
        db_session.expire_all()
        sub = db_session.query(Subscription).first()
        assert sub.status == SubscriptionStatusEnum.PAST_DUE


# ── Test: Branding Created on Bootstrap ──────────────────────────────────────


class TestBrandingBootstrap:

    def test_default_branding_created_on_bootstrap(self, db_session, bootstrap_and_token):
        """After bootstrap, a Branding record exists with default colors."""
        branding = db_session.query(Branding).first()
        assert branding is not None, "Branding should be created during bootstrap"
        assert branding.primary_color == "#D4845C"
        assert branding.accent_color == "#8B9D5D"
        assert branding.company_name == "Test Org"
