"""
FASE 5.4: Meta OAuth + Multi-Account Tests
Tests: token encryption (AES-GCM), OAuth flow (mocked), RBAC, ad account management.
Minimum 18 tests.
"""
import os
import time
import base64
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

# Set secrets before importing app
os.environ["JWT_SECRET"] = "test-secret-key-for-meta-oauth-tests"
os.environ["META_TOKEN_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(b"test-encryption-key-exactly-32b!").decode()
os.environ["META_APP_ID"] = "test_app_id_12345"
os.environ["META_APP_SECRET"] = "test_app_secret_67890"

from backend.main import app
from backend.src.database.models import (
    Base, Organization, User, UserOrgRole, RoleEnum,
    MetaConnection, AdAccount, ConnectionStatus,
)
from backend.src.database.session import get_db
from backend.src.middleware.auth import (
    create_access_token, hash_password, UserRole, get_current_user,
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
    """Override get_db only — real auth tested."""
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
    """Seed org + 3 users (admin, operator, viewer) + connection + ad account."""
    org_id = uuid4()
    org = Organization(
        id=org_id, name="Meta OAuth Test Corp", slug="meta-oauth-test",
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

    # Add a Meta connection + ad account
    conn_id = uuid4()
    conn = MetaConnection(
        id=conn_id, org_id=org_id,
        access_token_encrypted="enc_test_token", status="active",
        connected_at=datetime.utcnow(),
    )
    db_session.add(conn)

    ad_account_id = uuid4()
    ad_account = AdAccount(
        id=ad_account_id, connection_id=conn_id,
        meta_ad_account_id="act_meta_test_001", name="Meta Test Account",
        currency="USD", synced_at=datetime.utcnow(),
    )
    db_session.add(ad_account)

    db_session.commit()

    return {
        "org_id": str(org_id),
        "users": users,
        "ad_account_id": str(ad_account_id),
        "connection_id": str(conn_id),
    }


@pytest.fixture(scope="function")
def seed_empty_org(db_session, override_db):
    """Seed org with user but NO connections or ad accounts."""
    org_id = uuid4()
    org = Organization(
        id=org_id, name="Empty Org", slug="empty-org-meta",
        operator_armed=False, created_at=datetime.utcnow(),
    )
    db_session.add(org)

    user_id = uuid4()
    user = User(
        id=user_id, email="admin@emptyorg.com", name="Empty Admin",
        password_hash=hash_password("test-password-123"),
        created_at=datetime.utcnow(),
    )
    db_session.add(user)

    role = UserOrgRole(
        id=uuid4(), user_id=user_id, org_id=org_id,
        role=RoleEnum.ADMIN, assigned_at=datetime.utcnow(),
    )
    db_session.add(role)

    db_session.commit()

    return {
        "org_id": str(org_id),
        "user_id": str(user_id),
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


# ── Test: Token Encryption (AES-GCM) ────────────────────────────────────────


class TestTokenEncryption:
    """Test AES-256-GCM encrypt/decrypt utility."""

    def test_encrypt_decrypt_roundtrip(self):
        """Encrypt then decrypt returns original token."""
        from backend.src.utils.token_crypto import encrypt_token, decrypt_token
        original = "EAABsbCS1iZAtesttoken12345_longlivedtoken"
        encrypted = encrypt_token(original)
        assert encrypted != original
        assert decrypt_token(encrypted) == original

    def test_different_encryptions_produce_different_ciphertext(self):
        """Two encryptions of same plaintext should differ (unique nonce)."""
        from backend.src.utils.token_crypto import encrypt_token
        token = "same-token-encrypted-twice"
        enc1 = encrypt_token(token)
        enc2 = encrypt_token(token)
        assert enc1 != enc2  # Different nonce each time

    def test_decrypt_corrupted_data_raises(self):
        """Corrupted base64 input should raise."""
        from backend.src.utils.token_crypto import decrypt_token
        with pytest.raises(Exception):
            decrypt_token("not-valid-encrypted-data!!!")

    def test_decrypt_tampered_ciphertext_raises(self):
        """Tampered ciphertext should fail GCM authentication."""
        from backend.src.utils.token_crypto import encrypt_token, decrypt_token
        encrypted = encrypt_token("real-secret-token")
        raw = bytearray(base64.urlsafe_b64decode(encrypted))
        raw[15] ^= 0xFF  # Flip a byte in the ciphertext area
        tampered = base64.urlsafe_b64encode(bytes(raw)).decode()
        with pytest.raises(Exception):
            decrypt_token(tampered)


# ── Test: OAuth RBAC ─────────────────────────────────────────────────────────


class TestOAuthRBAC:
    """Test that only admins can initiate OAuth, but all roles can view/select."""

    def test_viewer_cannot_start_oauth(self, client, seed_org_and_users):
        """Viewer should get 403 on /oauth/start."""
        token = _get_token(client, "viewer@test.com")
        resp = client.get("/api/meta/oauth/start", headers=_auth_header(token))
        assert resp.status_code == 403

    def test_operator_cannot_start_oauth(self, client, seed_org_and_users):
        """Operator should get 403 on /oauth/start."""
        token = _get_token(client, "operator@test.com")
        resp = client.get("/api/meta/oauth/start", headers=_auth_header(token))
        assert resp.status_code == 403

    def test_admin_can_start_oauth(self, client, seed_org_and_users):
        """Admin should get 200 with authorization_url on /oauth/start."""
        token = _get_token(client, "admin@test.com")
        resp = client.get("/api/meta/oauth/start", headers=_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert "authorization_url" in data
        assert "facebook.com" in data["authorization_url"]
        assert "ads_read" in data["authorization_url"]

    def test_viewer_can_list_accounts(self, client, seed_org_and_users):
        """Any authenticated user can list ad accounts."""
        token = _get_token(client, "viewer@test.com")
        resp = client.get("/api/meta/adaccounts", headers=_auth_header(token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_viewer_can_view_active_account(self, client, seed_org_and_users):
        """Any authenticated user can view active account."""
        token = _get_token(client, "viewer@test.com")
        resp = client.get("/api/meta/adaccounts/active", headers=_auth_header(token))
        assert resp.status_code == 200

    def test_viewer_can_select_account(self, client, seed_org_and_users):
        """Any authenticated user can select an ad account."""
        token = _get_token(client, "viewer@test.com")
        resp = client.post(
            "/api/meta/adaccounts/select",
            json={"ad_account_id": seed_org_and_users["ad_account_id"]},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_ad_account_id"] == seed_org_and_users["ad_account_id"]


# ── Test: Ad Account Management ──────────────────────────────────────────────


class TestAdAccountManagement:
    """Test ad account listing, selection, active account."""

    def test_list_accounts_returns_seeded_accounts(self, client, seed_org_and_users):
        """Should return the seeded ad account."""
        token = _get_token(client, "admin@test.com")
        resp = client.get("/api/meta/adaccounts", headers=_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["meta_ad_account_id"] == "act_meta_test_001"

    def test_list_accounts_empty_org(self, client, seed_empty_org):
        """Org with no connections should return empty list."""
        token = _get_token(client, "admin@emptyorg.com")
        resp = client.get("/api/meta/adaccounts", headers=_auth_header(token))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_select_nonexistent_account_returns_400(self, client, seed_org_and_users):
        """Selecting a non-existent account should return 400."""
        token = _get_token(client, "admin@test.com")
        resp = client.post(
            "/api/meta/adaccounts/select",
            json={"ad_account_id": str(uuid4())},
            headers=_auth_header(token),
        )
        assert resp.status_code == 400

    def test_active_account_initially_none(self, client, seed_org_and_users):
        """Before selecting, active account should be null."""
        token = _get_token(client, "admin@test.com")
        resp = client.get("/api/meta/adaccounts/active", headers=_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_active_account"] is False
        assert data["ad_account_id"] is None

    def test_select_then_get_active(self, client, seed_org_and_users):
        """After selecting, active account should match."""
        token = _get_token(client, "admin@test.com")
        ad_id = seed_org_and_users["ad_account_id"]

        # Select
        resp = client.post(
            "/api/meta/adaccounts/select",
            json={"ad_account_id": ad_id},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200

        # Get active
        resp = client.get("/api/meta/adaccounts/active", headers=_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_active_account"] is True
        assert data["ad_account_id"] == ad_id
        assert data["name"] == "Meta Test Account"

    def test_list_accounts_marks_active(self, client, seed_org_and_users):
        """After selecting, list should mark the active account."""
        token = _get_token(client, "admin@test.com")
        ad_id = seed_org_and_users["ad_account_id"]

        # Select first
        client.post(
            "/api/meta/adaccounts/select",
            json={"ad_account_id": ad_id},
            headers=_auth_header(token),
        )

        # List
        resp = client.get("/api/meta/adaccounts", headers=_auth_header(token))
        data = resp.json()
        assert len(data) == 1
        assert data[0]["is_active"] is True


# ── Test: OAuth Callback ─────────────────────────────────────────────────────


class TestOAuthCallback:
    """Test OAuth callback with mocked Meta API."""

    def test_callback_with_invalid_state_redirects_with_error(self, client, seed_org_and_users):
        """Invalid state should redirect to frontend with error."""
        resp = client.get(
            "/api/meta/oauth/callback",
            params={"code": "test-code", "state": "invalid-state-12345"},
            follow_redirects=False,
        )
        assert resp.status_code in [302, 307]
        location = resp.headers.get("location", "")
        assert "meta_error" in location

    @patch("backend.src.adapters.meta_oauth.MetaOAuthAdapter.exchange_code_for_token", new_callable=AsyncMock)
    @patch("backend.src.adapters.meta_oauth.MetaOAuthAdapter.exchange_for_long_lived_token", new_callable=AsyncMock)
    @patch("backend.src.adapters.meta_oauth.MetaOAuthAdapter.get_user_info", new_callable=AsyncMock)
    @patch("backend.src.adapters.meta_oauth.MetaOAuthAdapter.list_ad_accounts", new_callable=AsyncMock)
    def test_callback_success_with_mocked_meta(
        self, mock_list, mock_user, mock_long, mock_exchange,
        client, seed_org_and_users,
    ):
        """Successful OAuth callback should redirect with meta_connected=true."""
        mock_exchange.return_value = {"access_token": "short_token_abc", "expires_in": 3600}
        mock_long.return_value = {"access_token": "long_token_xyz", "expires_in": 5184000}
        mock_user.return_value = {"id": "meta_user_123", "name": "Test Meta User"}
        mock_list.return_value = [
            {"id": "act_new_111", "name": "New Test Account", "currency": "USD"},
        ]

        # Generate a valid state by calling oauth/start
        from backend.src.services.meta_service import _oauth_states
        state = "test-valid-state-mocked-123"
        _oauth_states[state] = {
            "org_id": seed_org_and_users["org_id"],
            "user_id": seed_org_and_users["users"]["admin"]["id"],
            "created_at": time.time(),
        }

        resp = client.get(
            "/api/meta/oauth/callback",
            params={"code": "valid-auth-code", "state": state},
            follow_redirects=False,
        )
        assert resp.status_code in [302, 307]
        location = resp.headers.get("location", "")
        assert "meta_connected=true" in location


# ── Test: No Auth Returns 401 ────────────────────────────────────────────────


class TestNoAuthRequired:
    """Verify unauthenticated access is blocked on protected Meta endpoints."""

    def test_no_token_on_start_returns_401(self, client, seed_org_and_users):
        """oauth/start without token returns 401."""
        resp = client.get("/api/meta/oauth/start")
        assert resp.status_code == 401

    def test_no_token_on_list_returns_401(self, client, seed_org_and_users):
        """adaccounts list without token returns 401."""
        resp = client.get("/api/meta/adaccounts")
        assert resp.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
