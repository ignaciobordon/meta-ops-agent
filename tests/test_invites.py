"""
Invite System Tests
Tests invite creation, acceptance, expiration, revocation, and RBAC enforcement.
Minimum 6 tests covering the full invite lifecycle.
"""
import os
import secrets
import pytest
from uuid import uuid4, UUID
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.main import app
from backend.src.database.models import Base, Organization, User, UserOrgRole, RoleEnum, Invite
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
def seed_org_admin(db_session, override_db):
    """Seed organization + admin user + UserOrgRole (admin role). Returns dict with org_id, user_id, token."""
    org_id = uuid4()
    org = Organization(
        id=org_id,
        name="Invite Test Corp",
        slug="invite-test",
        operator_armed=False,
        created_at=datetime.utcnow(),
    )
    db_session.add(org)

    user_id = uuid4()
    user = User(
        id=user_id,
        email="admin@invite-test.com",
        name="Admin User",
        password_hash=hash_password("admin-pass-123"),
        created_at=datetime.utcnow(),
    )
    db_session.add(user)

    role = UserOrgRole(
        id=uuid4(),
        user_id=user_id,
        org_id=org_id,
        role=RoleEnum.ADMIN,
        assigned_at=datetime.utcnow(),
    )
    db_session.add(role)

    db_session.commit()

    token = create_access_token(
        user_id=str(user_id),
        email="admin@invite-test.com",
        role="admin",
        org_id=str(org_id),
    )

    return {
        "org_id": str(org_id),
        "user_id": str(user_id),
        "token": token,
    }


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_invite_in_db(db_session, org_id: str, user_id: str, email: str, role: RoleEnum, expires_at: datetime) -> str:
    """Helper: create an Invite directly in the DB. Returns the invite token string."""
    invite_token = secrets.token_urlsafe(48)
    invite = Invite(
        id=uuid4(),
        org_id=UUID(org_id),
        invited_by_user_id=UUID(user_id),
        email=email,
        role=role,
        token=invite_token,
        expires_at=expires_at,
        created_at=datetime.utcnow(),
    )
    db_session.add(invite)
    db_session.commit()
    return invite_token


# ── Tests ────────────────────────────────────────────────────────────────────


class TestInvites:

    def test_create_invite(self, seed_org_admin):
        """Admin creates an invite -> 200, returns invite with email and role."""
        client = TestClient(app)
        resp = client.post(
            "/api/orgs/invites",
            json={"email": "newuser@test.com", "role": "viewer"},
            headers=_auth(seed_org_admin["token"]),
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["email"] == "newuser@test.com"
        assert data["role"] == "viewer"
        assert "id" in data
        assert "token" in data
        assert "expires_at" in data
        assert "created_at" in data

    def test_accept_invite_creates_user(self, seed_org_admin, db_session):
        """Create invite in DB, then POST /api/auth/accept-invite/{token} -> 200, returns tokens. Verify user exists."""
        client = TestClient(app)

        # Create invite directly in DB with naive datetime (SQLite compat)
        invite_token = _create_invite_in_db(
            db_session,
            org_id=seed_org_admin["org_id"],
            user_id=seed_org_admin["user_id"],
            email="accepted@test.com",
            role=RoleEnum.OPERATOR,
            expires_at=datetime.utcnow() + timedelta(days=7),
        )

        # Accept the invite (public endpoint, no auth needed).
        # Patch datetime.now in the auth module so the naive-vs-aware comparison works
        # (SQLite strips timezone from stored datetimes; the accept endpoint uses aware now()).
        with patch("backend.src.api.auth.datetime") as mock_dt:
            mock_dt.now.return_value = datetime.utcnow()
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            accept_resp = client.post(
                f"/api/auth/accept-invite/{invite_token}",
                json={"name": "New User", "password": "pass123"},
            )

        assert accept_resp.status_code == 200, f"Expected 200, got {accept_resp.status_code}: {accept_resp.text}"
        accept_data = accept_resp.json()
        assert "access_token" in accept_data
        assert "refresh_token" in accept_data
        assert accept_data["user"]["email"] == "accepted@test.com"
        assert accept_data["user"]["role"] == "operator"

        # Verify user exists in DB
        new_user = db_session.query(User).filter(User.email == "accepted@test.com").first()
        assert new_user is not None
        assert new_user.name == "New User"

    def test_expired_invite_rejected(self, seed_org_admin, db_session):
        """An invite with expires_at in the past cannot be accepted -> 400."""
        client = TestClient(app)

        # Create invite directly in DB with expired naive datetime
        invite_token = _create_invite_in_db(
            db_session,
            org_id=seed_org_admin["org_id"],
            user_id=seed_org_admin["user_id"],
            email="expired@test.com",
            role=RoleEnum.VIEWER,
            expires_at=datetime.utcnow() - timedelta(days=1),
        )

        # Try to accept the expired invite.
        # Patch datetime.now to return naive utcnow for SQLite compatibility.
        with patch("backend.src.api.auth.datetime") as mock_dt:
            mock_dt.now.return_value = datetime.utcnow()
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            resp = client.post(
                f"/api/auth/accept-invite/{invite_token}",
                json={"name": "Late User", "password": "pass123"},
            )

        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
        assert "expired" in resp.json()["detail"].lower()

    def test_duplicate_invite_rejected(self, seed_org_admin):
        """Creating an invite for the same email twice -> 400."""
        client = TestClient(app)

        # First invite
        resp1 = client.post(
            "/api/orgs/invites",
            json={"email": "duplicate@test.com", "role": "viewer"},
            headers=_auth(seed_org_admin["token"]),
        )
        assert resp1.status_code == 200

        # Second invite for the same email
        resp2 = client.post(
            "/api/orgs/invites",
            json={"email": "duplicate@test.com", "role": "operator"},
            headers=_auth(seed_org_admin["token"]),
        )
        assert resp2.status_code == 400, f"Expected 400, got {resp2.status_code}: {resp2.text}"
        assert "pending invite" in resp2.json()["detail"].lower()

    def test_revoke_invite(self, seed_org_admin):
        """Create invite, DELETE it, verify it is gone from list."""
        client = TestClient(app)

        # Create invite
        create_resp = client.post(
            "/api/orgs/invites",
            json={"email": "revokeme@test.com", "role": "viewer"},
            headers=_auth(seed_org_admin["token"]),
        )
        assert create_resp.status_code == 200
        invite_id = create_resp.json()["id"]

        # Delete (revoke) the invite
        delete_resp = client.delete(
            f"/api/orgs/invites/{invite_id}",
            headers=_auth(seed_org_admin["token"]),
        )
        assert delete_resp.status_code == 200, f"Expected 200, got {delete_resp.status_code}: {delete_resp.text}"

        # Verify invite is no longer in the list
        list_resp = client.get(
            "/api/orgs/invites",
            headers=_auth(seed_org_admin["token"]),
        )
        assert list_resp.status_code == 200
        emails = [inv["email"] for inv in list_resp.json()]
        assert "revokeme@test.com" not in emails

    def test_non_admin_cant_invite(self, seed_org_admin, db_session):
        """A viewer user cannot create invites -> 403."""
        client = TestClient(app)

        # Create a viewer user in the same org
        viewer_id = uuid4()
        viewer = User(
            id=viewer_id,
            email="viewer@invite-test.com",
            name="Viewer User",
            password_hash=hash_password("viewer-pass-123"),
            created_at=datetime.utcnow(),
        )
        db_session.add(viewer)

        viewer_role = UserOrgRole(
            id=uuid4(),
            user_id=viewer_id,
            org_id=UUID(seed_org_admin["org_id"]),
            role=RoleEnum.VIEWER,
            assigned_at=datetime.utcnow(),
        )
        db_session.add(viewer_role)
        db_session.commit()

        viewer_token = create_access_token(
            user_id=str(viewer_id),
            email="viewer@invite-test.com",
            role="viewer",
            org_id=seed_org_admin["org_id"],
        )

        # Viewer tries to create invite
        resp = client.post(
            "/api/orgs/invites",
            json={"email": "sneaky@test.com", "role": "viewer"},
            headers=_auth(viewer_token),
        )
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

    def test_list_pending_invites(self, seed_org_admin):
        """Admin can list all pending invites for the org."""
        client = TestClient(app)

        # Create two invites
        resp1 = client.post(
            "/api/orgs/invites",
            json={"email": "listtest1@test.com", "role": "viewer"},
            headers=_auth(seed_org_admin["token"]),
        )
        assert resp1.status_code == 200

        resp2 = client.post(
            "/api/orgs/invites",
            json={"email": "listtest2@test.com", "role": "operator"},
            headers=_auth(seed_org_admin["token"]),
        )
        assert resp2.status_code == 200

        # List invites
        resp = client.get(
            "/api/orgs/invites",
            headers=_auth(seed_org_admin["token"]),
        )
        assert resp.status_code == 200
        invites = resp.json()
        emails = [inv["email"] for inv in invites]
        assert "listtest1@test.com" in emails
        assert "listtest2@test.com" in emails
        assert len(invites) >= 2

    def test_non_admin_cant_revoke_invite(self, seed_org_admin, db_session):
        """A viewer user cannot revoke (delete) invites -> 403."""
        client = TestClient(app)

        # Admin creates an invite
        create_resp = client.post(
            "/api/orgs/invites",
            json={"email": "cantrevoke@test.com", "role": "viewer"},
            headers=_auth(seed_org_admin["token"]),
        )
        assert create_resp.status_code == 200
        invite_id = create_resp.json()["id"]

        # Create a viewer user
        viewer_id = uuid4()
        viewer = User(
            id=viewer_id,
            email="viewer-revoke@invite-test.com",
            name="Viewer Revoker",
            password_hash=hash_password("viewer-pass-123"),
            created_at=datetime.utcnow(),
        )
        db_session.add(viewer)

        viewer_role = UserOrgRole(
            id=uuid4(),
            user_id=viewer_id,
            org_id=UUID(seed_org_admin["org_id"]),
            role=RoleEnum.VIEWER,
            assigned_at=datetime.utcnow(),
        )
        db_session.add(viewer_role)
        db_session.commit()

        viewer_token = create_access_token(
            user_id=str(viewer_id),
            email="viewer-revoke@invite-test.com",
            role="viewer",
            org_id=seed_org_admin["org_id"],
        )

        # Viewer tries to revoke the invite
        resp = client.delete(
            f"/api/orgs/invites/{invite_id}",
            headers=_auth(viewer_token),
        )
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
