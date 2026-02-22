"""
Multi-Tenant Isolation Tests
Verifies that users from one organization cannot see or access
data belonging to another organization.
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

from backend.main import app
from backend.src.database.models import (
    Base, Organization, User, UserOrgRole, RoleEnum,
    MetaConnection, AdAccount,
    DecisionPack, DecisionState, ActionType,
    Creative,
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
    """Seed two separate organizations, each with their own user, connection, and ad account."""

    # ── Org 1 ─────────────────────────────────────────────────────────────
    org1_id = uuid4()
    org1 = Organization(
        id=org1_id, name="Org Alpha", slug="org-alpha",
        operator_armed=True, created_at=datetime.utcnow(),
    )
    db_session.add(org1)

    user1_id = uuid4()
    user1 = User(
        id=user1_id,
        email="alice@org-alpha.test",
        name="Alice Alpha",
        password_hash=hash_password("pass-alpha-123"),
        created_at=datetime.utcnow(),
    )
    db_session.add(user1)

    role1 = UserOrgRole(
        id=uuid4(), user_id=user1_id, org_id=org1_id,
        role=RoleEnum.OPERATOR, assigned_at=datetime.utcnow(),
    )
    db_session.add(role1)

    conn1_id = uuid4()
    conn1 = MetaConnection(
        id=conn1_id, org_id=org1_id,
        access_token_encrypted="enc_test", status="active",
        connected_at=datetime.utcnow(),
    )
    db_session.add(conn1)

    ad_account1_id = uuid4()
    ad_account1 = AdAccount(
        id=ad_account1_id, connection_id=conn1_id,
        meta_ad_account_id="act_alpha_001", name="Alpha Ad Account",
        currency="USD", synced_at=datetime.utcnow(),
    )
    db_session.add(ad_account1)

    # ── Org 2 ─────────────────────────────────────────────────────────────
    org2_id = uuid4()
    org2 = Organization(
        id=org2_id, name="Org Beta", slug="org-beta",
        operator_armed=True, created_at=datetime.utcnow(),
    )
    db_session.add(org2)

    user2_id = uuid4()
    user2 = User(
        id=user2_id,
        email="bob@org-beta.test",
        name="Bob Beta",
        password_hash=hash_password("pass-beta-456"),
        created_at=datetime.utcnow(),
    )
    db_session.add(user2)

    role2 = UserOrgRole(
        id=uuid4(), user_id=user2_id, org_id=org2_id,
        role=RoleEnum.OPERATOR, assigned_at=datetime.utcnow(),
    )
    db_session.add(role2)

    conn2_id = uuid4()
    conn2 = MetaConnection(
        id=conn2_id, org_id=org2_id,
        access_token_encrypted="enc_test", status="active",
        connected_at=datetime.utcnow(),
    )
    db_session.add(conn2)

    ad_account2_id = uuid4()
    ad_account2 = AdAccount(
        id=ad_account2_id, connection_id=conn2_id,
        meta_ad_account_id="act_beta_001", name="Beta Ad Account",
        currency="USD", synced_at=datetime.utcnow(),
    )
    db_session.add(ad_account2)

    db_session.commit()

    # ── Tokens ────────────────────────────────────────────────────────────
    token1 = create_access_token(
        user_id=str(user1_id),
        email="alice@org-alpha.test",
        role="operator",
        org_id=str(org1_id),
    )
    token2 = create_access_token(
        user_id=str(user2_id),
        email="bob@org-beta.test",
        role="operator",
        org_id=str(org2_id),
    )

    return {
        "org1": {
            "org_id": str(org1_id),
            "user_id": str(user1_id),
            "ad_account_id": str(ad_account1_id),
            "token": token1,
        },
        "org2": {
            "org_id": str(org2_id),
            "user_id": str(user2_id),
            "ad_account_id": str(ad_account2_id),
            "token": token2,
        },
    }


@pytest.fixture
def client(override_db):
    return TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── Tests ────────────────────────────────────────────────────────────────────


class TestMultiTenantIsolation:

    def test_user_sees_only_own_org_decisions(self, client, seed_data, db_session):
        """User A (org1) creates a DecisionPack. User B (org2) cannot see it, User A can."""
        org1 = seed_data["org1"]
        org2 = seed_data["org2"]

        # Seed a DecisionPack belonging to org1's ad account
        decision = DecisionPack(
            ad_account_id=UUID(org1["ad_account_id"]),
            created_by_user_id=UUID(org1["user_id"]),
            state=DecisionState.DRAFT,
            trace_id=f"trace-{uuid4().hex[:12]}",
            action_type=ActionType.BID_CHANGE,
            entity_type="campaign",
            entity_id="camp_123",
            entity_name="Test Campaign",
            action_request={"bid": 1.5},
            rationale="test multitenancy",
            source="test",
            before_snapshot={"bid": 1.0},
            after_proposal={"bid": 1.5},
            created_at=datetime.utcnow(),
        )
        db_session.add(decision)
        db_session.commit()

        # User B (org2) should see empty list
        resp_b = client.get("/api/decisions/", headers=_auth(org2["token"]))
        assert resp_b.status_code == 200
        assert resp_b.json() == []

        # User A (org1) should see the decision
        resp_a = client.get("/api/decisions/", headers=_auth(org1["token"]))
        assert resp_a.status_code == 200
        decisions_a = resp_a.json()
        assert len(decisions_a) == 1
        assert decisions_a[0]["entity_name"] == "Test Campaign"

    def test_user_sees_only_own_org_creatives(self, client, seed_data, db_session):
        """Creative in org1's ad_account is invisible to org2, visible to org1."""
        org1 = seed_data["org1"]
        org2 = seed_data["org2"]

        # Seed a Creative belonging to org1's ad account
        creative = Creative(
            ad_account_id=UUID(org1["ad_account_id"]),
            name="Test Creative",
            ad_copy="Test copy",
            tags=[{"l1": "angle", "l2": "test_angle", "confidence": 1.0, "source": "test"}],
            overall_score=0.8,
            meta_ad_id="meta_123",
            created_at=datetime.utcnow(),
        )
        db_session.add(creative)
        db_session.commit()

        # User B (org2) should see empty list
        resp_b = client.get("/api/creatives/", headers=_auth(org2["token"]))
        assert resp_b.status_code == 200
        assert resp_b.json() == []

        # User A (org1) should see the creative
        resp_a = client.get("/api/creatives/", headers=_auth(org1["token"]))
        assert resp_a.status_code == 200
        creatives_a = resp_a.json()
        assert len(creatives_a) == 1
        assert creatives_a[0]["angle_name"] == "Test Creative"

    def test_user_sees_only_own_org_audit(self, client, seed_data, db_session):
        """Executed DecisionPack in org1 is invisible in org2's audit log."""
        org1 = seed_data["org1"]
        org2 = seed_data["org2"]

        # Seed an executed DecisionPack belonging to org1
        decision = DecisionPack(
            ad_account_id=UUID(org1["ad_account_id"]),
            created_by_user_id=UUID(org1["user_id"]),
            state=DecisionState.EXECUTED,
            trace_id=f"trace-{uuid4().hex[:12]}",
            action_type=ActionType.BID_CHANGE,
            entity_type="campaign",
            entity_id="camp_456",
            entity_name="Executed Campaign",
            action_request={"bid": 2.0},
            rationale="test audit isolation",
            source="test",
            before_snapshot={"bid": 1.0},
            after_proposal={"bid": 2.0},
            executed_at=datetime.utcnow(),
            execution_result={"success": True},
            created_at=datetime.utcnow(),
        )
        db_session.add(decision)
        db_session.commit()

        # User B (org2) should see empty audit list
        resp_b = client.get("/api/audit/", headers=_auth(org2["token"]))
        assert resp_b.status_code == 200
        assert resp_b.json() == []

        # User A (org1) should see the executed entry
        resp_a = client.get("/api/audit/", headers=_auth(org1["token"]))
        assert resp_a.status_code == 200
        audit_a = resp_a.json()
        assert len(audit_a) == 1
        assert audit_a[0]["entity_id"] == "camp_456"
        assert audit_a[0]["status"] == "success"

    def test_user_sees_only_own_org_dashboard(self, client, seed_data, db_session):
        """Dashboard KPIs for org2 show 0 when all decisions belong to org1."""
        org1 = seed_data["org1"]
        org2 = seed_data["org2"]

        # Seed DecisionPacks belonging to org1
        for i in range(3):
            dp = DecisionPack(
                ad_account_id=UUID(org1["ad_account_id"]),
                created_by_user_id=UUID(org1["user_id"]),
                state=DecisionState.PENDING_APPROVAL,
                trace_id=f"trace-dash-{uuid4().hex[:12]}",
                action_type=ActionType.BUDGET_CHANGE,
                entity_type="campaign",
                entity_id=f"camp_dash_{i}",
                entity_name=f"Dashboard Campaign {i}",
                action_request={"budget": 100 + i},
                rationale="dashboard test",
                source="test",
                before_snapshot={},
                after_proposal={},
                created_at=datetime.utcnow(),
            )
            db_session.add(dp)
        db_session.commit()

        # User B (org2) dashboard should show all zeros
        resp_b = client.get("/api/dashboard/kpis", headers=_auth(org2["token"]))
        assert resp_b.status_code == 200
        data_b = resp_b.json()
        summary_b = data_b["summary"]
        assert summary_b["total_decisions"] == 0
        assert summary_b["success_rate"] == 0

        # User A (org1) dashboard should show real values
        resp_a = client.get("/api/dashboard/kpis", headers=_auth(org1["token"]))
        assert resp_a.status_code == 200
        data_a = resp_a.json()
        summary_a = data_a["summary"]
        assert summary_a["total_decisions"] == 3

    def test_cross_org_decision_access_blocked(self, client, seed_data, db_session):
        """User B cannot access org1's decision by ID — returns 404."""
        org1 = seed_data["org1"]
        org2 = seed_data["org2"]

        # Seed a DecisionPack belonging to org1
        decision = DecisionPack(
            ad_account_id=UUID(org1["ad_account_id"]),
            created_by_user_id=UUID(org1["user_id"]),
            state=DecisionState.DRAFT,
            trace_id=f"trace-{uuid4().hex[:12]}",
            action_type=ActionType.BID_CHANGE,
            entity_type="campaign",
            entity_id="camp_789",
            entity_name="Private Campaign",
            action_request={"bid": 3.0},
            rationale="cross-org test",
            source="test",
            before_snapshot={},
            after_proposal={},
            created_at=datetime.utcnow(),
        )
        db_session.add(decision)
        db_session.commit()
        db_session.refresh(decision)
        decision_id = str(decision.id)

        # User B (org2) tries to access org1's decision by ID — should get 404
        resp_b = client.get(f"/api/decisions/{decision_id}", headers=_auth(org2["token"]))
        assert resp_b.status_code == 404

        # User A (org1) can access their own decision by ID
        resp_a = client.get(f"/api/decisions/{decision_id}", headers=_auth(org1["token"]))
        assert resp_a.status_code == 200
        assert resp_a.json()["entity_name"] == "Private Campaign"
