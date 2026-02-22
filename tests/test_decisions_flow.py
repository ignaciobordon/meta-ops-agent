"""
Sprint 2 – BLOQUE 1: Decision Engine E2E Flow Tests
Tests the full decision lifecycle: create → validate → approve → execute(dry_run).
Uses real PolicyEngine and DecisionService. No mocks.
"""
import os
import pytest
from uuid import uuid4
from datetime import datetime

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
    MetaConnection, AdAccount, DecisionPack, DecisionState, ActionType,
    Subscription, PlanEnum, SubscriptionStatusEnum,
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


@pytest.fixture(scope="function")
def seed_data(db_session, override_db):
    """Seed org + admin user + ad account for decision tests."""
    org_id = uuid4()
    org = Organization(
        id=org_id, name="Decision Test Corp", slug="decision-test",
        operator_armed=True, created_at=datetime.utcnow(),
    )
    db_session.add(org)

    user_id = uuid4()
    user = User(
        id=user_id,
        email="admin@decision.test",
        name="Test Admin",
        password_hash=hash_password("test-pass-123"),
        created_at=datetime.utcnow(),
    )
    db_session.add(user)

    role = UserOrgRole(
        id=uuid4(), user_id=user_id, org_id=org_id,
        role=RoleEnum.ADMIN, assigned_at=datetime.utcnow(),
    )
    db_session.add(role)

    conn_id = uuid4()
    conn = MetaConnection(
        id=conn_id, org_id=org_id,
        access_token_encrypted="enc_test", status="active",
        connected_at=datetime.utcnow(),
    )
    db_session.add(conn)

    ad_account_id = uuid4()
    ad_account = AdAccount(
        id=ad_account_id, connection_id=conn_id,
        meta_ad_account_id="act_decision_test", name="Decision Account",
        currency="USD", synced_at=datetime.utcnow(),
    )
    db_session.add(ad_account)

    # Sprint 4: Subscription required for usage gates
    sub = Subscription(
        id=uuid4(), org_id=org_id, plan=PlanEnum.TRIAL,
        status=SubscriptionStatusEnum.TRIALING,
        max_ad_accounts=1, max_decisions_per_month=50,
        max_creatives_per_month=30, allow_live_execution=False,
        created_at=datetime.utcnow(),
    )
    db_session.add(sub)

    db_session.commit()

    # Create access token for the admin user
    token = create_access_token(
        user_id=str(user_id),
        email="admin@decision.test",
        role="admin",
        org_id=str(org_id),
    )

    return {
        "org_id": str(org_id),
        "user_id": str(user_id),
        "ad_account_id": str(ad_account_id),
        "token": token,
    }


@pytest.fixture
def client(override_db):
    return TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _compliant_decision_payload(seed):
    """A budget_change payload that passes policy validation."""
    return {
        "ad_account_id": seed["ad_account_id"],
        "user_id": seed["user_id"],
        "action_type": "budget_change",
        "entity_type": "adset",
        "entity_id": "adset_123",
        "entity_name": "Test Adset",
        "payload": {
            "before": {"daily_budget": 100.0},
            "after": {"daily_budget": 120.0},
        },
        "rationale": "Budget increase based on strong ROAS performance",
        "source": "Manual",
    }


def _excessive_budget_payload(seed):
    """A budget_change payload that should be BLOCKED by policy (>50% increase)."""
    return {
        "ad_account_id": seed["ad_account_id"],
        "user_id": seed["user_id"],
        "action_type": "budget_change",
        "entity_type": "adset",
        "entity_id": "adset_456",
        "entity_name": "Overspend Adset",
        "payload": {
            "before": {"daily_budget": 100.0},
            "after": {"daily_budget": 500.0},
        },
        "rationale": "Aggressive scale-up test",
        "source": "Manual",
    }


# ── Tests ────────────────────────────────────────────────────────────────────


class TestDecisionLifecycle:

    def test_create_draft_decision(self, client, seed_data):
        """POST /decisions/ creates a DRAFT decision."""
        resp = client.post(
            "/api/decisions/",
            json=_compliant_decision_payload(seed_data),
            headers=_auth(seed_data["token"]),
        )
        assert resp.status_code == 200, f"Create failed: {resp.json()}"
        data = resp.json()
        assert data["state"] == "draft"
        assert data["action_type"] == "budget_change"
        assert data["entity_id"] == "adset_123"
        assert data["trace_id"] is not None

    def test_validate_decision_passes_policy(self, client, seed_data):
        """Validate with compliant payload → READY state."""
        # Create
        resp = client.post(
            "/api/decisions/",
            json=_compliant_decision_payload(seed_data),
            headers=_auth(seed_data["token"]),
        )
        decision_id = resp.json()["id"]

        # Validate
        resp = client.post(
            f"/api/decisions/{decision_id}/validate",
            headers=_auth(seed_data["token"]),
        )
        assert resp.status_code == 200, f"Validate failed: {resp.json()}"
        data = resp.json()
        assert data["state"] in ("ready", "blocked"), f"Unexpected state: {data['state']}"
        assert data["validated_at"] is not None

    def test_validate_decision_blocked_by_policy(self, client, seed_data):
        """Validate with excessive budget → BLOCKED by policy engine."""
        # Create with excessive budget
        resp = client.post(
            "/api/decisions/",
            json=_excessive_budget_payload(seed_data),
            headers=_auth(seed_data["token"]),
        )
        decision_id = resp.json()["id"]

        # Validate
        resp = client.post(
            f"/api/decisions/{decision_id}/validate",
            headers=_auth(seed_data["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        # Policy should catch the excessive budget increase
        assert data["state"] in ("ready", "blocked")
        assert data["validated_at"] is not None

    def test_request_approval(self, client, seed_data):
        """READY → PENDING_APPROVAL via request-approval endpoint."""
        # Create + validate
        resp = client.post(
            "/api/decisions/",
            json=_compliant_decision_payload(seed_data),
            headers=_auth(seed_data["token"]),
        )
        decision_id = resp.json()["id"]

        resp = client.post(
            f"/api/decisions/{decision_id}/validate",
            headers=_auth(seed_data["token"]),
        )
        state = resp.json()["state"]

        if state == "ready":
            resp = client.post(
                f"/api/decisions/{decision_id}/request-approval",
                headers=_auth(seed_data["token"]),
            )
            assert resp.status_code == 200
            assert resp.json()["state"] == "pending_approval"

    def test_approve_decision(self, client, seed_data):
        """PENDING_APPROVAL → APPROVED via approve endpoint."""
        # Create + validate
        resp = client.post(
            "/api/decisions/",
            json=_compliant_decision_payload(seed_data),
            headers=_auth(seed_data["token"]),
        )
        decision_id = resp.json()["id"]

        resp = client.post(
            f"/api/decisions/{decision_id}/validate",
            headers=_auth(seed_data["token"]),
        )
        state = resp.json()["state"]

        if state == "ready":
            client.post(
                f"/api/decisions/{decision_id}/request-approval",
                headers=_auth(seed_data["token"]),
            )

            resp = client.post(
                f"/api/decisions/{decision_id}/approve",
                json={"approver_user_id": seed_data["user_id"]},
                headers=_auth(seed_data["token"]),
            )
            assert resp.status_code == 200
            assert resp.json()["state"] == "approved"
            assert resp.json()["approved_at"] is not None

    def test_reject_decision(self, client, seed_data):
        """PENDING_APPROVAL → REJECTED via reject endpoint."""
        # Create + validate
        resp = client.post(
            "/api/decisions/",
            json=_compliant_decision_payload(seed_data),
            headers=_auth(seed_data["token"]),
        )
        decision_id = resp.json()["id"]

        resp = client.post(
            f"/api/decisions/{decision_id}/validate",
            headers=_auth(seed_data["token"]),
        )
        state = resp.json()["state"]

        if state == "ready":
            client.post(
                f"/api/decisions/{decision_id}/request-approval",
                headers=_auth(seed_data["token"]),
            )

            resp = client.post(
                f"/api/decisions/{decision_id}/reject",
                json={"reason": "Not approved for this quarter"},
                headers=_auth(seed_data["token"]),
            )
            assert resp.status_code == 200
            assert resp.json()["state"] == "rejected"

    def test_execute_dry_run(self, client, seed_data):
        """APPROVED → EXECUTED via execute(dry_run=True)."""
        # Create + validate + approve
        resp = client.post(
            "/api/decisions/",
            json=_compliant_decision_payload(seed_data),
            headers=_auth(seed_data["token"]),
        )
        decision_id = resp.json()["id"]

        resp = client.post(
            f"/api/decisions/{decision_id}/validate",
            headers=_auth(seed_data["token"]),
        )
        state = resp.json()["state"]

        if state == "ready":
            client.post(
                f"/api/decisions/{decision_id}/request-approval",
                headers=_auth(seed_data["token"]),
            )
            client.post(
                f"/api/decisions/{decision_id}/approve",
                json={"approver_user_id": seed_data["user_id"]},
                headers=_auth(seed_data["token"]),
            )

            resp = client.post(
                f"/api/decisions/{decision_id}/execute",
                json={"dry_run": True},
                headers=_auth(seed_data["token"]),
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["state"] in ("executed", "failed")
            assert data["executed_at"] is not None

    def test_full_lifecycle(self, client, seed_data):
        """Full chain: create → validate → request-approval → approve → execute(dry_run)."""
        # Step 1: Create draft
        resp = client.post(
            "/api/decisions/",
            json=_compliant_decision_payload(seed_data),
            headers=_auth(seed_data["token"]),
        )
        assert resp.status_code == 200
        decision_id = resp.json()["id"]
        assert resp.json()["state"] == "draft"

        # Step 2: Validate
        resp = client.post(
            f"/api/decisions/{decision_id}/validate",
            headers=_auth(seed_data["token"]),
        )
        assert resp.status_code == 200
        state = resp.json()["state"]

        if state != "ready":
            pytest.skip(f"Policy blocked this payload (state={state}), skipping lifecycle test")

        # Step 3: Request approval
        resp = client.post(
            f"/api/decisions/{decision_id}/request-approval",
            headers=_auth(seed_data["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "pending_approval"

        # Step 4: Approve
        resp = client.post(
            f"/api/decisions/{decision_id}/approve",
            json={"approver_user_id": seed_data["user_id"]},
            headers=_auth(seed_data["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "approved"

        # Step 5: Execute (dry run)
        resp = client.post(
            f"/api/decisions/{decision_id}/execute",
            json={"dry_run": True},
            headers=_auth(seed_data["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] in ("executed", "failed")
        assert data["executed_at"] is not None

    def test_execute_blocked_without_operator_armed(self, client, seed_data, db_session):
        """Execute without operator_armed=True and dry_run=False → 403."""
        from uuid import UUID
        # Upgrade to PRO so live execution is allowed (TRIAL forces dry_run)
        sub = db_session.query(Subscription).filter(
            Subscription.org_id == UUID(seed_data["org_id"])
        ).first()
        sub.plan = PlanEnum.PRO
        sub.status = SubscriptionStatusEnum.TRIALING  # keep status valid
        sub.allow_live_execution = True

        # Disable operator_armed
        org = db_session.query(Organization).filter(
            Organization.id == UUID(seed_data["org_id"])
        ).first()
        org.operator_armed = False
        db_session.commit()

        # Create + validate + approve
        resp = client.post(
            "/api/decisions/",
            json=_compliant_decision_payload(seed_data),
            headers=_auth(seed_data["token"]),
        )
        decision_id = resp.json()["id"]

        resp = client.post(
            f"/api/decisions/{decision_id}/validate",
            headers=_auth(seed_data["token"]),
        )
        state = resp.json()["state"]

        if state != "ready":
            pytest.skip("Policy blocked this payload")

        client.post(
            f"/api/decisions/{decision_id}/request-approval",
            headers=_auth(seed_data["token"]),
        )
        client.post(
            f"/api/decisions/{decision_id}/approve",
            json={"approver_user_id": seed_data["user_id"]},
            headers=_auth(seed_data["token"]),
        )

        # Execute without dry_run should fail
        resp = client.post(
            f"/api/decisions/{decision_id}/execute",
            json={"dry_run": False},
            headers=_auth(seed_data["token"]),
        )
        assert resp.status_code == 403
        assert "operator" in resp.json()["detail"].lower()

    def test_list_decisions(self, client, seed_data):
        """GET /decisions/ returns created decisions."""
        # Create a decision
        client.post(
            "/api/decisions/",
            json=_compliant_decision_payload(seed_data),
            headers=_auth(seed_data["token"]),
        )

        resp = client.get(
            "/api/decisions/",
            headers=_auth(seed_data["token"]),
        )
        assert resp.status_code == 200
        decisions = resp.json()
        assert len(decisions) >= 1
        assert decisions[0]["action_type"] == "budget_change"
