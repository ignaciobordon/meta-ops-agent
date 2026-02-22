"""
FASE 5.3: Auth & RBAC Tests
Tests JWT authentication, role-based access control, token lifecycle.
Minimum 12 tests covering 401/403 by role.
"""
import os
import pytest
from uuid import uuid4
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

# Set JWT_SECRET before importing app (so auth module picks it up)
os.environ["JWT_SECRET"] = "test-secret-key-for-jwt-testing-only"

from backend.main import app
from backend.src.database.models import (
    Base, Organization, User, UserOrgRole, RoleEnum,
    MetaConnection, AdAccount,
    Subscription, PlanEnum, SubscriptionStatusEnum,
)
from backend.src.database.session import get_db
from backend.src.middleware.auth import (
    create_access_token, create_refresh_token, decode_token,
    hash_password, verify_password, UserRole,
    get_current_user, JWT_ACCESS_TTL_MINUTES,
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


@pytest.fixture(scope="function")
def seed_org_and_users(db_session, override_db):
    """Seed org + 3 users (admin, operator, viewer) with real passwords."""
    org_id = uuid4()
    org = Organization(
        id=org_id, name="Auth Test Corp", slug="auth-test",
        operator_armed=True, created_at=datetime.utcnow(),
    )
    db_session.add(org)

    users = {}
    for role_name in ["admin", "operator", "viewer"]:
        user_id = uuid4()
        user = User(
            id=user_id,
            email=f"{role_name}@test.com",
            name=f"Test {role_name.title()}",
            password_hash=hash_password("test-password-123"),
            created_at=datetime.utcnow(),
        )
        db_session.add(user)

        role_enum = RoleEnum(role_name)
        role = UserOrgRole(
            id=uuid4(), user_id=user_id, org_id=org_id,
            role=role_enum, assigned_at=datetime.utcnow(),
        )
        db_session.add(role)

        users[role_name] = {
            "id": str(user_id),
            "email": f"{role_name}@test.com",
        }

    # Add ad account for decision tests
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
        meta_ad_account_id="act_auth_test", name="Auth Test Account",
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

    return {
        "org_id": str(org_id),
        "users": users,
        "ad_account_id": str(ad_account_id),
    }


@pytest.fixture
def client(override_db):
    return TestClient(app)


def _get_token(client, email, password="test-password-123"):
    """Login and return access token."""
    resp = client.post("/api/auth/login", json={
        "email": email, "password": password,
    })
    assert resp.status_code == 200, f"Login failed for {email}: {resp.json()}"
    return resp.json()["access_token"]


def _auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# ── Test: Authentication (401) ───────────────────────────────────────────────


class TestAuthentication:

    def test_no_token_returns_401(self, client, seed_org_and_users):
        """Protected endpoint without token returns 401."""
        resp = client.get("/api/dashboard/kpis?days=1")
        assert resp.status_code == 401
        assert "Authentication required" in resp.json()["detail"]

    def test_invalid_token_returns_401(self, client, seed_org_and_users):
        """Garbage token returns 401."""
        resp = client.get(
            "/api/dashboard/kpis?days=1",
            headers={"Authorization": "Bearer garbage-token-123"},
        )
        assert resp.status_code == 401

    def test_expired_token_returns_401(self, client, seed_org_and_users):
        """Expired JWT returns 401."""
        users = seed_org_and_users["users"]
        # Create token that expired 1 hour ago
        token = create_access_token(
            user_id=users["admin"]["id"],
            email=users["admin"]["email"],
            role="admin",
            org_id=seed_org_and_users["org_id"],
            expires_delta=timedelta(seconds=-3600),  # Already expired
        )
        resp = client.get(
            "/api/dashboard/kpis?days=1",
            headers=_auth_header(token),
        )
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    def test_valid_login_returns_tokens(self, client, seed_org_and_users):
        """Valid credentials return access + refresh tokens."""
        resp = client.post("/api/auth/login", json={
            "email": "admin@test.com",
            "password": "test-password-123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == JWT_ACCESS_TTL_MINUTES * 60
        assert data["user"]["email"] == "admin@test.com"
        assert data["user"]["role"] == "admin"

    def test_wrong_password_returns_401(self, client, seed_org_and_users):
        """Wrong password returns 401."""
        resp = client.post("/api/auth/login", json={
            "email": "admin@test.com",
            "password": "wrong-password",
        })
        assert resp.status_code == 401

    def test_nonexistent_email_returns_401(self, client, seed_org_and_users):
        """Non-existent email returns 401."""
        resp = client.post("/api/auth/login", json={
            "email": "nobody@test.com",
            "password": "test-password-123",
        })
        assert resp.status_code == 401

    def test_health_endpoint_no_auth_required(self, client, seed_org_and_users):
        """Health endpoint is public — no auth required."""
        resp = client.get("/api/health")
        assert resp.status_code in [200, 207, 503]

    def test_auth_endpoints_no_auth_required(self, client, seed_org_and_users):
        """Login/register endpoints are public."""
        # Login endpoint returns 401 for bad creds, not for missing token
        resp = client.post("/api/auth/login", json={
            "email": "x@x.com", "password": "x",
        })
        # Should be 401 (bad creds), not 401 (missing token)
        assert resp.status_code == 401
        assert "email or password" in resp.json()["detail"].lower()


# ── Test: Token Lifecycle ────────────────────────────────────────────────────


class TestTokenLifecycle:

    def test_access_token_works_for_protected_endpoint(self, client, seed_org_and_users):
        """Valid access token grants access to protected endpoints."""
        token = _get_token(client, "admin@test.com")
        resp = client.get(
            "/api/dashboard/kpis?days=1",
            headers=_auth_header(token),
        )
        assert resp.status_code == 200

    def test_refresh_token_returns_new_tokens(self, client, seed_org_and_users):
        """Refresh token exchange returns new access + refresh tokens."""
        # Login first
        login_resp = client.post("/api/auth/login", json={
            "email": "admin@test.com",
            "password": "test-password-123",
        })
        refresh_token = login_resp.json()["refresh_token"]

        # Refresh
        resp = client.post("/api/auth/refresh", json={
            "refresh_token": refresh_token,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == "admin@test.com"
        assert data["expires_in"] > 0

    def test_me_endpoint_returns_user_info(self, client, seed_org_and_users):
        """/auth/me returns current user info."""
        token = _get_token(client, "operator@test.com")
        resp = client.get(
            "/api/auth/me",
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "operator@test.com"
        assert data["role"] == "operator"

    def test_refresh_with_access_token_fails(self, client, seed_org_and_users):
        """Using an access token for refresh should fail."""
        token = _get_token(client, "admin@test.com")
        resp = client.post("/api/auth/refresh", json={
            "refresh_token": token,  # This is an access token, not refresh
        })
        assert resp.status_code == 401


# ── Test: RBAC - Role-Based Access Control (403) ─────────────────────────────


class TestRBACViewer:
    """Viewer can read but cannot write."""

    def test_viewer_can_read_dashboard(self, client, seed_org_and_users):
        token = _get_token(client, "viewer@test.com")
        resp = client.get("/api/dashboard/kpis?days=1", headers=_auth_header(token))
        assert resp.status_code == 200

    def test_viewer_can_read_policies(self, client, seed_org_and_users):
        token = _get_token(client, "viewer@test.com")
        resp = client.get("/api/policies/rules", headers=_auth_header(token))
        assert resp.status_code == 200

    def test_viewer_can_read_audit(self, client, seed_org_and_users):
        token = _get_token(client, "viewer@test.com")
        resp = client.get("/api/audit/", headers=_auth_header(token))
        assert resp.status_code == 200

    def test_viewer_can_read_decisions(self, client, seed_org_and_users):
        token = _get_token(client, "viewer@test.com")
        resp = client.get("/api/decisions/", headers=_auth_header(token))
        assert resp.status_code == 200

    def test_viewer_cannot_create_decision(self, client, seed_org_and_users):
        """Viewer gets 403 trying to create a decision."""
        token = _get_token(client, "viewer@test.com")
        resp = client.post("/api/decisions/", json={
            "ad_account_id": seed_org_and_users["ad_account_id"],
            "user_id": seed_org_and_users["users"]["viewer"]["id"],
            "action_type": "budget_change",
            "entity_type": "adset",
            "entity_id": "adset_test",
            "entity_name": "Test",
            "payload": {"current_budget": 100, "new_budget": 110},
            "rationale": "test",
            "source": "test",
        }, headers=_auth_header(token))
        assert resp.status_code == 403

    def test_viewer_cannot_create_org(self, client, seed_org_and_users):
        """Viewer gets 403 trying to create an org."""
        token = _get_token(client, "viewer@test.com")
        resp = client.post("/api/orgs/", json={
            "name": "Unauthorized Org", "slug": "unauth-org",
        }, headers=_auth_header(token))
        assert resp.status_code == 403

    def test_viewer_cannot_toggle_operator_armed(self, client, seed_org_and_users):
        """Viewer gets 403 trying to toggle operator armed."""
        token = _get_token(client, "viewer@test.com")
        resp = client.post(
            f"/api/orgs/{seed_org_and_users['org_id']}/operator-armed",
            json={"enabled": False},
            headers=_auth_header(token),
        )
        assert resp.status_code == 403


class TestRBACOperator:
    """Operator can create/approve decisions but not execute live or manage orgs."""

    def test_operator_can_create_decision(self, client, seed_org_and_users):
        token = _get_token(client, "operator@test.com")
        resp = client.post("/api/decisions/", json={
            "ad_account_id": seed_org_and_users["ad_account_id"],
            "user_id": seed_org_and_users["users"]["operator"]["id"],
            "action_type": "budget_change",
            "entity_type": "adset",
            "entity_id": "adset_op_test",
            "entity_name": "Operator Test",
            "payload": {"current_budget": 100, "new_budget": 110},
            "rationale": "operator test",
            "source": "test",
        }, headers=_auth_header(token))
        assert resp.status_code == 200

    def test_operator_cannot_execute_decision(self, client, seed_org_and_users):
        """Operator gets 403 trying to execute (admin-only action)."""
        # First create + validate + approve as operator
        token = _get_token(client, "operator@test.com")
        create_resp = client.post("/api/decisions/", json={
            "ad_account_id": seed_org_and_users["ad_account_id"],
            "user_id": seed_org_and_users["users"]["operator"]["id"],
            "action_type": "budget_change",
            "entity_type": "adset",
            "entity_id": "adset_exec_test",
            "entity_name": "Exec Test",
            "payload": {"current_budget": 100, "new_budget": 110},
            "rationale": "test",
            "source": "test",
        }, headers=_auth_header(token))
        decision_id = create_resp.json()["id"]

        client.post(f"/api/decisions/{decision_id}/validate", headers=_auth_header(token))
        client.post(f"/api/decisions/{decision_id}/request-approval", headers=_auth_header(token))
        client.post(f"/api/decisions/{decision_id}/approve", json={
            "approver_user_id": seed_org_and_users["users"]["operator"]["id"],
        }, headers=_auth_header(token))

        # Execute — should be blocked for operator
        resp = client.post(f"/api/decisions/{decision_id}/execute", json={
            "dry_run": True,
        }, headers=_auth_header(token))
        assert resp.status_code == 403

    def test_operator_cannot_create_org(self, client, seed_org_and_users):
        """Operator gets 403 creating orgs."""
        token = _get_token(client, "operator@test.com")
        resp = client.post("/api/orgs/", json={
            "name": "Op Org", "slug": "op-org",
        }, headers=_auth_header(token))
        assert resp.status_code == 403


class TestRBACAdmin:
    """Admin can do everything."""

    def test_admin_can_execute_decision(self, client, seed_org_and_users):
        """Admin can execute decisions."""
        token = _get_token(client, "admin@test.com")
        create_resp = client.post("/api/decisions/", json={
            "ad_account_id": seed_org_and_users["ad_account_id"],
            "user_id": seed_org_and_users["users"]["admin"]["id"],
            "action_type": "budget_change",
            "entity_type": "adset",
            "entity_id": "adset_admin_exec",
            "entity_name": "Admin Exec Test",
            "payload": {"current_budget": 100, "new_budget": 110},
            "rationale": "admin test",
            "source": "test",
        }, headers=_auth_header(token))
        decision_id = create_resp.json()["id"]

        client.post(f"/api/decisions/{decision_id}/validate", headers=_auth_header(token))
        client.post(f"/api/decisions/{decision_id}/request-approval", headers=_auth_header(token))
        client.post(f"/api/decisions/{decision_id}/approve", json={
            "approver_user_id": seed_org_and_users["users"]["admin"]["id"],
        }, headers=_auth_header(token))

        resp = client.post(f"/api/decisions/{decision_id}/execute", json={
            "dry_run": True,
        }, headers=_auth_header(token))
        assert resp.status_code == 200

    def test_admin_can_create_org(self, client, seed_org_and_users):
        token = _get_token(client, "admin@test.com")
        resp = client.post("/api/orgs/", json={
            "name": "Admin Org", "slug": "admin-org",
        }, headers=_auth_header(token))
        assert resp.status_code == 200

    def test_admin_can_toggle_operator_armed(self, client, seed_org_and_users):
        token = _get_token(client, "admin@test.com")
        resp = client.post(
            f"/api/orgs/{seed_org_and_users['org_id']}/operator-armed",
            json={"enabled": False},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200


# ── Test: Registration ───────────────────────────────────────────────────────


class TestRegistration:

    def test_register_first_user_gets_admin(self, client, override_db):
        """First user in a new org gets admin role."""
        # Create org first (via direct DB since we need it for registration)
        # Use a different approach: register will fail without an org
        # So we need an org. Let's create one via API with auth bypass.
        from backend.src.middleware.auth import get_current_user as _gcu
        app.dependency_overrides[_gcu] = lambda: {
            "id": "bootstrap", "email": "x", "name": "x",
            "role": UserRole.ADMIN, "org_id": "x",
        }
        org_resp = client.post("/api/orgs/", json={
            "name": "Reg Test Org", "slug": "reg-test",
        })
        org_id = org_resp.json()["id"]
        del app.dependency_overrides[_gcu]

        # Register first user
        resp = client.post("/api/auth/register", json={
            "email": "first@reg.com",
            "name": "First User",
            "password": "secure-password-123",
            "org_id": org_id,
        })
        assert resp.status_code == 200
        assert resp.json()["user"]["role"] == "admin"

    def test_register_second_user_gets_viewer(self, client, seed_org_and_users):
        """Subsequent users get viewer role (not admin by default)."""
        resp = client.post("/api/auth/register", json={
            "email": "newuser@test.com",
            "name": "New User",
            "password": "secure-password-123",
            "org_id": seed_org_and_users["org_id"],
        })
        assert resp.status_code == 200
        assert resp.json()["user"]["role"] == "viewer"

    def test_register_duplicate_email_fails(self, client, seed_org_and_users):
        """Duplicate email returns 400."""
        resp = client.post("/api/auth/register", json={
            "email": "admin@test.com",  # Already exists
            "name": "Dup",
            "password": "secure-password-123",
            "org_id": seed_org_and_users["org_id"],
        })
        assert resp.status_code == 400
        assert "already registered" in resp.json()["detail"].lower()
