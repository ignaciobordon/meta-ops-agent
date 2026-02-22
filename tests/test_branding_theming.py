"""
Branding & Theming Tests
Verifies branding CRUD endpoints, default fallback values,
org-scoped isolation, admin-only writes, and hex color validation.
"""
import os
import pytest
from uuid import uuid4, UUID as _UUID
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.main import app
from backend.src.database.models import Base, Organization, User, UserOrgRole, RoleEnum, Branding
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
def seed_org_admin(db_session, override_db):
    """Seed an organization with an admin user and UserOrgRole.

    Returns a dict with org_id, user_id, and admin JWT token.
    """
    org_id = uuid4()
    org = Organization(
        id=org_id,
        name="Branding Test Corp",
        slug="branding-test",
        operator_armed=True,
        created_at=datetime.utcnow(),
    )
    db_session.add(org)

    user_id = uuid4()
    user = User(
        id=user_id,
        email="admin@branding-test.com",
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
        email="admin@branding-test.com",
        role="admin",
        org_id=str(org_id),
    )

    return {
        "org_id": str(org_id),
        "user_id": str(user_id),
        "token": token,
    }


@pytest.fixture(scope="function")
def seed_org_viewer(db_session, seed_org_admin):
    """Create a viewer user in the SAME org as seed_org_admin.

    Returns a dict with user_id and viewer JWT token (org_id matches seed_org_admin).
    """
    org_id = seed_org_admin["org_id"]

    user_id = uuid4()
    user = User(
        id=user_id,
        email="viewer@branding-test.com",
        name="Viewer User",
        password_hash=hash_password("test-password-123"),
        created_at=datetime.utcnow(),
    )
    db_session.add(user)

    role = UserOrgRole(
        id=uuid4(),
        user_id=user_id,
        org_id=_UUID(org_id),
        role=RoleEnum.VIEWER,
        assigned_at=datetime.utcnow(),
    )
    db_session.add(role)

    db_session.commit()

    token = create_access_token(
        user_id=str(user_id),
        email="viewer@branding-test.com",
        role="viewer",
        org_id=org_id,
    )

    return {
        "org_id": org_id,
        "user_id": str(user_id),
        "token": token,
    }


@pytest.fixture
def client(override_db):
    return TestClient(app)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Tests ────────────────────────────────────────────────────────────────────


class TestBrandingTheming:

    def test_default_branding_returned(self, client, seed_org_admin):
        """GET /api/orgs/branding with no branding row in DB returns default colors."""
        resp = client.get("/api/orgs/branding", headers=_auth(seed_org_admin["token"]))
        assert resp.status_code == 200

        data = resp.json()
        assert data["id"] == ""
        assert data["primary_color"] == "#D4845C"
        assert data["accent_color"] == "#8B9D5D"
        assert data["logo_url"] is None
        assert data["company_name"] is None

    def test_get_branding_with_existing(self, client, seed_org_admin, db_session):
        """GET /api/orgs/branding returns stored branding when a row exists in DB."""
        branding = Branding(
            id=uuid4(),
            org_id=_UUID(seed_org_admin["org_id"]),
            logo_url="https://example.com/logo.png",
            primary_color="#112233",
            accent_color="#445566",
            company_name="Stored Corp",
            custom_domain="brand.example.com",
            created_at=datetime.utcnow(),
        )
        db_session.add(branding)
        db_session.commit()

        resp = client.get("/api/orgs/branding", headers=_auth(seed_org_admin["token"]))
        assert resp.status_code == 200

        data = resp.json()
        assert data["id"] != ""
        assert data["primary_color"] == "#112233"
        assert data["accent_color"] == "#445566"
        assert data["logo_url"] == "https://example.com/logo.png"
        assert data["company_name"] == "Stored Corp"
        assert data["custom_domain"] == "brand.example.com"

    def test_update_branding(self, client, seed_org_admin):
        """PUT /api/orgs/branding creates/updates branding, then GET reflects new values."""
        put_resp = client.put(
            "/api/orgs/branding",
            json={
                "primary_color": "#FF0000",
                "accent_color": "#00FF00",
                "company_name": "My Co",
            },
            headers=_auth(seed_org_admin["token"]),
        )
        assert put_resp.status_code == 200

        put_data = put_resp.json()
        assert put_data["primary_color"] == "#FF0000"
        assert put_data["accent_color"] == "#00FF00"
        assert put_data["company_name"] == "My Co"
        assert put_data["id"] != ""

        # Verify via GET that it persisted
        get_resp = client.get("/api/orgs/branding", headers=_auth(seed_org_admin["token"]))
        assert get_resp.status_code == 200

        get_data = get_resp.json()
        assert get_data["primary_color"] == "#FF0000"
        assert get_data["accent_color"] == "#00FF00"
        assert get_data["company_name"] == "My Co"

    def test_branding_scoped_to_org(self, client, db_session, override_db):
        """Two orgs each with different branding. User from org1 only sees org1 branding."""
        # ── Org 1 ────────────────────────────────────────────────────────────
        org1_id = uuid4()
        org1 = Organization(
            id=org1_id, name="Org One", slug="org-one",
            operator_armed=True, created_at=datetime.utcnow(),
        )
        db_session.add(org1)

        user1_id = uuid4()
        user1 = User(
            id=user1_id,
            email="user1@org-one.test",
            name="User One",
            password_hash=hash_password("test-password-123"),
            created_at=datetime.utcnow(),
        )
        db_session.add(user1)

        role1 = UserOrgRole(
            id=uuid4(), user_id=user1_id, org_id=org1_id,
            role=RoleEnum.ADMIN, assigned_at=datetime.utcnow(),
        )
        db_session.add(role1)

        branding1 = Branding(
            id=uuid4(), org_id=org1_id,
            primary_color="#AA0000", accent_color="#00AA00",
            company_name="Org One Inc",
            created_at=datetime.utcnow(),
        )
        db_session.add(branding1)

        # ── Org 2 ────────────────────────────────────────────────────────────
        org2_id = uuid4()
        org2 = Organization(
            id=org2_id, name="Org Two", slug="org-two",
            operator_armed=True, created_at=datetime.utcnow(),
        )
        db_session.add(org2)

        user2_id = uuid4()
        user2 = User(
            id=user2_id,
            email="user2@org-two.test",
            name="User Two",
            password_hash=hash_password("test-password-123"),
            created_at=datetime.utcnow(),
        )
        db_session.add(user2)

        role2 = UserOrgRole(
            id=uuid4(), user_id=user2_id, org_id=org2_id,
            role=RoleEnum.ADMIN, assigned_at=datetime.utcnow(),
        )
        db_session.add(role2)

        branding2 = Branding(
            id=uuid4(), org_id=org2_id,
            primary_color="#BB0000", accent_color="#00BB00",
            company_name="Org Two LLC",
            created_at=datetime.utcnow(),
        )
        db_session.add(branding2)

        db_session.commit()

        token1 = create_access_token(
            user_id=str(user1_id),
            email="user1@org-one.test",
            role="admin",
            org_id=str(org1_id),
        )
        token2 = create_access_token(
            user_id=str(user2_id),
            email="user2@org-two.test",
            role="admin",
            org_id=str(org2_id),
        )

        # User 1 sees org1 branding only
        resp1 = client.get("/api/orgs/branding", headers=_auth(token1))
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["primary_color"] == "#AA0000"
        assert data1["accent_color"] == "#00AA00"
        assert data1["company_name"] == "Org One Inc"

        # User 2 sees org2 branding only
        resp2 = client.get("/api/orgs/branding", headers=_auth(token2))
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["primary_color"] == "#BB0000"
        assert data2["accent_color"] == "#00BB00"
        assert data2["company_name"] == "Org Two LLC"

    def test_branding_only_admin(self, client, seed_org_admin, seed_org_viewer):
        """Viewer user tries PUT /api/orgs/branding and receives 403."""
        resp = client.put(
            "/api/orgs/branding",
            json={
                "primary_color": "#000000",
                "accent_color": "#FFFFFF",
                "company_name": "Unauthorized Update",
            },
            headers=_auth(seed_org_viewer["token"]),
        )
        assert resp.status_code == 403

    def test_branding_hex_validation(self, client, seed_org_admin):
        """PUT with invalid hex color returns 400."""
        resp = client.put(
            "/api/orgs/branding",
            json={
                "primary_color": "not-a-color",
                "accent_color": "#00FF00",
            },
            headers=_auth(seed_org_admin["token"]),
        )
        assert resp.status_code == 400
        assert "primary_color" in resp.json()["detail"].lower()

    def test_branding_hex_validation_accent(self, client, seed_org_admin):
        """PUT with invalid accent_color hex returns 400."""
        resp = client.put(
            "/api/orgs/branding",
            json={
                "primary_color": "#FF0000",
                "accent_color": "rgb(0,255,0)",
            },
            headers=_auth(seed_org_admin["token"]),
        )
        assert resp.status_code == 400
        assert "accent_color" in resp.json()["detail"].lower()

    def test_update_branding_partial(self, client, seed_org_admin):
        """PUT with only primary_color updates that field and leaves others at defaults."""
        # First set full branding
        client.put(
            "/api/orgs/branding",
            json={
                "primary_color": "#111111",
                "accent_color": "#222222",
                "company_name": "Full Branding",
            },
            headers=_auth(seed_org_admin["token"]),
        )

        # Now update only company_name
        resp = client.put(
            "/api/orgs/branding",
            json={"company_name": "Updated Name Only"},
            headers=_auth(seed_org_admin["token"]),
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["company_name"] == "Updated Name Only"
        # Previous colors should be preserved
        assert data["primary_color"] == "#111111"
        assert data["accent_color"] == "#222222"

    def test_unauthenticated_branding_returns_401(self, client, seed_org_admin):
        """GET /api/orgs/branding without auth header returns 401."""
        resp = client.get("/api/orgs/branding")
        assert resp.status_code == 401

    def test_update_branding_idempotent(self, client, seed_org_admin):
        """Calling PUT /api/orgs/branding twice with the same data is idempotent."""
        payload = {
            "primary_color": "#AABBCC",
            "accent_color": "#DDEEFF",
            "company_name": "Idempotent Co",
        }

        resp1 = client.put(
            "/api/orgs/branding",
            json=payload,
            headers=_auth(seed_org_admin["token"]),
        )
        assert resp1.status_code == 200
        branding_id = resp1.json()["id"]

        resp2 = client.put(
            "/api/orgs/branding",
            json=payload,
            headers=_auth(seed_org_admin["token"]),
        )
        assert resp2.status_code == 200
        # Same branding row is updated, not duplicated
        assert resp2.json()["id"] == branding_id
        assert resp2.json()["primary_color"] == "#AABBCC"
        assert resp2.json()["accent_color"] == "#DDEEFF"
        assert resp2.json()["company_name"] == "Idempotent Co"
