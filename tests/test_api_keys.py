"""
API Key Management Tests
Tests CRUD operations for API keys: creation, listing, revocation,
RBAC enforcement, org-scoped isolation, and key format validation.
Minimum 8 tests covering all /api/keys endpoints.
"""
import os
import re
import pytest
from uuid import UUID, uuid4
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
    ApiKey, Subscription, PlanEnum, SubscriptionStatusEnum,
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
    """Override ONLY get_db — real auth is exercised via JWT tokens."""
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
def seed_admin(db_session, override_db):
    """
    Seed a single organization with an admin user.
    Returns dict with org_id, user_id, and a valid admin JWT token.
    """
    org_id = uuid4()
    org = Organization(
        id=org_id,
        name="API Key Test Corp",
        slug="apikey-test",
        operator_armed=True,
        created_at=datetime.utcnow(),
    )
    db_session.add(org)

    user_id = uuid4()
    user = User(
        id=user_id,
        email="admin@apikey-test.com",
        name="Admin User",
        password_hash=hash_password("test-password-123"),
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
        email="admin@apikey-test.com",
        role="admin",
        org_id=str(org_id),
    )

    return {
        "org_id": str(org_id),
        "user_id": str(user_id),
        "token": token,
    }


def _auth(token: str) -> dict:
    """Build Authorization header from token."""
    return {"Authorization": f"Bearer {token}"}


# ── Tests ────────────────────────────────────────────────────────────────────


class TestApiKeyCreation:

    def test_create_api_key(self, seed_admin):
        """POST /api/keys returns a new key with moa_ prefix and all expected fields."""
        client = TestClient(app)
        resp = client.post(
            "/api/keys/",
            json={"name": "My Key", "scopes": ["read"]},
            headers=_auth(seed_admin["token"]),
        )
        assert resp.status_code == 200, f"Unexpected status: {resp.status_code} — {resp.text}"
        data = resp.json()

        # All expected fields present
        assert "id" in data
        assert "name" in data
        assert "key" in data
        assert "key_prefix" in data
        assert "scopes" in data
        assert "created_at" in data

        # Values
        assert data["name"] == "My Key"
        assert data["scopes"] == ["read"]
        assert data["key"].startswith("moa_")

    def test_key_has_correct_prefix(self, seed_admin):
        """Created key starts with 'moa_' followed by 32 hex chars; key_prefix is first 8 chars."""
        client = TestClient(app)
        resp = client.post(
            "/api/keys/",
            json={"name": "Prefix Check", "scopes": ["read", "write"]},
            headers=_auth(seed_admin["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()

        raw_key = data["key"]
        # Format: moa_ + 32 hex chars
        assert re.fullmatch(r"moa_[0-9a-f]{32}", raw_key), (
            f"Key format mismatch: {raw_key}"
        )
        # key_prefix is first 8 characters of the full key
        assert data["key_prefix"] == raw_key[:8]


class TestApiKeyListing:

    def test_key_not_returned_again(self, seed_admin):
        """GET /api/keys does NOT include the plaintext 'key' field."""
        client = TestClient(app)

        # Create a key first
        create_resp = client.post(
            "/api/keys/",
            json={"name": "Secret Key", "scopes": ["read"]},
            headers=_auth(seed_admin["token"]),
        )
        assert create_resp.status_code == 200

        # List keys
        list_resp = client.get(
            "/api/keys/",
            headers=_auth(seed_admin["token"]),
        )
        assert list_resp.status_code == 200
        keys = list_resp.json()
        assert len(keys) >= 1

        for key_item in keys:
            assert "key" not in key_item, (
                "Plaintext key must NOT appear in list response"
            )
            # Should still have the masked prefix
            assert "key_prefix" in key_item

    def test_list_keys(self, seed_admin):
        """After creating 2 keys, GET /api/keys returns exactly 2 items."""
        client = TestClient(app)
        headers = _auth(seed_admin["token"])

        # Create two keys
        resp1 = client.post(
            "/api/keys/",
            json={"name": "Key Alpha", "scopes": ["read"]},
            headers=headers,
        )
        assert resp1.status_code == 200

        resp2 = client.post(
            "/api/keys/",
            json={"name": "Key Beta", "scopes": ["read", "write"]},
            headers=headers,
        )
        assert resp2.status_code == 200

        # List
        list_resp = client.get("/api/keys/", headers=headers)
        assert list_resp.status_code == 200
        keys = list_resp.json()
        assert len(keys) == 2

        names = {k["name"] for k in keys}
        assert names == {"Key Alpha", "Key Beta"}


class TestApiKeyRevocation:

    def test_delete_key(self, seed_admin):
        """DELETE /api/keys/{id} returns 200 and the key no longer appears in the list."""
        client = TestClient(app)
        headers = _auth(seed_admin["token"])

        # Create a key
        create_resp = client.post(
            "/api/keys/",
            json={"name": "Doomed Key", "scopes": ["read"]},
            headers=headers,
        )
        assert create_resp.status_code == 200
        key_id = create_resp.json()["id"]

        # Delete it
        del_resp = client.delete(f"/api/keys/{key_id}", headers=headers)
        assert del_resp.status_code == 200

        # Verify it is gone from the list
        list_resp = client.get("/api/keys/", headers=headers)
        assert list_resp.status_code == 200
        remaining_ids = [k["id"] for k in list_resp.json()]
        assert key_id not in remaining_ids

    def test_revoked_key_not_listed(self, seed_admin):
        """After revoking a key, GET /api/keys does not include the revoked key."""
        client = TestClient(app)
        headers = _auth(seed_admin["token"])

        # Create two keys
        resp_keep = client.post(
            "/api/keys/",
            json={"name": "Keep Me", "scopes": ["read"]},
            headers=headers,
        )
        resp_revoke = client.post(
            "/api/keys/",
            json={"name": "Revoke Me", "scopes": ["read"]},
            headers=headers,
        )
        assert resp_keep.status_code == 200
        assert resp_revoke.status_code == 200

        keep_id = resp_keep.json()["id"]
        revoke_id = resp_revoke.json()["id"]

        # Revoke one
        del_resp = client.delete(f"/api/keys/{revoke_id}", headers=headers)
        assert del_resp.status_code == 200

        # List should only contain the kept key
        list_resp = client.get("/api/keys/", headers=headers)
        assert list_resp.status_code == 200
        keys = list_resp.json()
        listed_ids = [k["id"] for k in keys]
        assert keep_id in listed_ids
        assert revoke_id not in listed_ids


class TestApiKeyRBAC:

    def test_non_admin_cannot_create(self, db_session, override_db, seed_admin):
        """A viewer user receives 403 when attempting to create an API key."""
        client = TestClient(app)
        org_id = seed_admin["org_id"]

        # Create a viewer user in the same org
        viewer_id = uuid4()
        viewer = User(
            id=viewer_id,
            email="viewer@apikey-test.com",
            name="Viewer User",
            password_hash=hash_password("test-password-123"),
            created_at=datetime.utcnow(),
        )
        db_session.add(viewer)

        viewer_role = UserOrgRole(
            id=uuid4(),
            user_id=viewer_id,
            org_id=UUID(org_id),
            role=RoleEnum.VIEWER,
            assigned_at=datetime.utcnow(),
        )
        db_session.add(viewer_role)
        db_session.commit()

        viewer_token = create_access_token(
            user_id=str(viewer_id),
            email="viewer@apikey-test.com",
            role="viewer",
            org_id=org_id,
        )

        resp = client.post(
            "/api/keys/",
            json={"name": "Sneaky Key", "scopes": ["read"]},
            headers=_auth(viewer_token),
        )
        assert resp.status_code == 403

    def test_non_admin_cannot_revoke(self, db_session, override_db, seed_admin):
        """A viewer user receives 403 when attempting to revoke an API key."""
        client = TestClient(app)
        org_id = seed_admin["org_id"]
        admin_headers = _auth(seed_admin["token"])

        # Admin creates a key
        create_resp = client.post(
            "/api/keys/",
            json={"name": "Admin Key", "scopes": ["read"]},
            headers=admin_headers,
        )
        assert create_resp.status_code == 200
        key_id = create_resp.json()["id"]

        # Create a viewer user in the same org
        viewer_id = uuid4()
        viewer = User(
            id=viewer_id,
            email="viewer-revoke@apikey-test.com",
            name="Viewer Revoker",
            password_hash=hash_password("test-password-123"),
            created_at=datetime.utcnow(),
        )
        db_session.add(viewer)

        viewer_role = UserOrgRole(
            id=uuid4(),
            user_id=viewer_id,
            org_id=UUID(org_id),
            role=RoleEnum.VIEWER,
            assigned_at=datetime.utcnow(),
        )
        db_session.add(viewer_role)
        db_session.commit()

        viewer_token = create_access_token(
            user_id=str(viewer_id),
            email="viewer-revoke@apikey-test.com",
            role="viewer",
            org_id=org_id,
        )

        # Viewer tries to revoke — should get 403
        resp = client.delete(
            f"/api/keys/{key_id}",
            headers=_auth(viewer_token),
        )
        assert resp.status_code == 403


class TestApiKeyOrgIsolation:

    def test_key_scoped_to_org(self, db_session, override_db, seed_admin):
        """
        Keys created in org1 are invisible when listing from org2.
        Ensures strict org-scoped tenant isolation.
        """
        client = TestClient(app)

        # ── Org1 admin creates a key ─────────────────────────────────────
        org1_headers = _auth(seed_admin["token"])
        create_resp = client.post(
            "/api/keys/",
            json={"name": "Org1 Key", "scopes": ["read"]},
            headers=org1_headers,
        )
        assert create_resp.status_code == 200

        # ── Create Org2 with its own admin ───────────────────────────────
        org2_id = uuid4()
        org2 = Organization(
            id=org2_id,
            name="Other Corp",
            slug="other-corp",
            operator_armed=False,
            created_at=datetime.utcnow(),
        )
        db_session.add(org2)

        user2_id = uuid4()
        user2 = User(
            id=user2_id,
            email="admin@other-corp.com",
            name="Other Admin",
            password_hash=hash_password("test-password-123"),
            created_at=datetime.utcnow(),
        )
        db_session.add(user2)

        role2 = UserOrgRole(
            id=uuid4(),
            user_id=user2_id,
            org_id=org2_id,
            role=RoleEnum.ADMIN,
            assigned_at=datetime.utcnow(),
        )
        db_session.add(role2)
        db_session.commit()

        token2 = create_access_token(
            user_id=str(user2_id),
            email="admin@other-corp.com",
            role="admin",
            org_id=str(org2_id),
        )

        # ── Org2 admin lists keys — should see zero ──────────────────────
        list_resp = client.get("/api/keys/", headers=_auth(token2))
        assert list_resp.status_code == 200
        assert list_resp.json() == [], (
            "Org2 should see no keys — org1's key must be invisible"
        )

        # ── Org1 admin still sees its own key ────────────────────────────
        list_resp_org1 = client.get("/api/keys/", headers=org1_headers)
        assert list_resp_org1.status_code == 200
        assert len(list_resp_org1.json()) == 1

    def test_cross_org_revoke_returns_404(self, db_session, override_db, seed_admin):
        """
        An admin from org2 cannot revoke a key belonging to org1.
        The endpoint should return 404 (key not found in their org scope).
        """
        client = TestClient(app)

        # Org1 admin creates a key
        create_resp = client.post(
            "/api/keys/",
            json={"name": "Protected Key", "scopes": ["read"]},
            headers=_auth(seed_admin["token"]),
        )
        assert create_resp.status_code == 200
        key_id = create_resp.json()["id"]

        # Create org2 + admin
        org2_id = uuid4()
        org2 = Organization(
            id=org2_id,
            name="Attacker Corp",
            slug="attacker-corp",
            operator_armed=False,
            created_at=datetime.utcnow(),
        )
        db_session.add(org2)

        user2_id = uuid4()
        user2 = User(
            id=user2_id,
            email="admin@attacker-corp.com",
            name="Attacker Admin",
            password_hash=hash_password("test-password-123"),
            created_at=datetime.utcnow(),
        )
        db_session.add(user2)

        role2 = UserOrgRole(
            id=uuid4(),
            user_id=user2_id,
            org_id=org2_id,
            role=RoleEnum.ADMIN,
            assigned_at=datetime.utcnow(),
        )
        db_session.add(role2)
        db_session.commit()

        token2 = create_access_token(
            user_id=str(user2_id),
            email="admin@attacker-corp.com",
            role="admin",
            org_id=str(org2_id),
        )

        # Org2 admin tries to revoke org1's key — should get 404
        resp = client.delete(
            f"/api/keys/{key_id}",
            headers=_auth(token2),
        )
        assert resp.status_code == 404

        # Verify org1's key is still active
        list_resp = client.get("/api/keys/", headers=_auth(seed_admin["token"]))
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1
