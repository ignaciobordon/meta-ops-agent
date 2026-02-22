"""
Sprint 1: Auth Security Hardening Tests
Tests token revocation, sessions, refresh rotation, rate limiting,
security headers, and bootstrap hardening.
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

os.environ["JWT_SECRET"] = "test-secret-key-for-jwt-testing-only"

from backend.main import app
from backend.src.database.models import (
    Base, Organization, User, UserOrgRole, RoleEnum,
    MetaConnection, AdAccount, RevokedToken, UserSession,
)
from backend.src.database.session import get_db
import jwt as pyjwt
from backend.src.middleware.auth import (
    create_access_token, create_refresh_token, decode_token,
    hash_password, JWT_ACCESS_TTL_MINUTES, JWT_SECRET, JWT_ALGORITHM,
)
from backend.src.middleware.rate_limit import login_limiter


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
    """Seed org + admin user with real password."""
    org_id = uuid4()
    org = Organization(
        id=org_id, name="Hardening Test Corp", slug="hardening-test",
        operator_armed=True, created_at=datetime.utcnow(),
    )
    db_session.add(org)

    user_id = uuid4()
    user = User(
        id=user_id,
        email="admin@hardening.test",
        name="Test Admin",
        password_hash=hash_password("secure-pass-123"),
        created_at=datetime.utcnow(),
    )
    db_session.add(user)

    role = UserOrgRole(
        id=uuid4(), user_id=user_id, org_id=org_id,
        role=RoleEnum.ADMIN, assigned_at=datetime.utcnow(),
    )
    db_session.add(role)

    # Ad account for completeness
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
        meta_ad_account_id="act_hardening_test", name="Hardening Account",
        currency="USD", synced_at=datetime.utcnow(),
    )
    db_session.add(ad_account)

    db_session.commit()

    return {
        "org_id": str(org_id),
        "user_id": str(user_id),
        "email": "admin@hardening.test",
        "password": "secure-pass-123",
        "ad_account_id": str(ad_account_id),
    }


@pytest.fixture
def client(override_db):
    return TestClient(app)


def _login(client, email, password):
    """Login and return full token response."""
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, f"Login failed: {resp.json()}"
    return resp.json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── Token Revocation Tests ───────────────────────────────────────────────────


class TestTokenRevocation:

    def test_access_token_includes_jti(self, client, seed_data):
        """Access tokens should include a jti claim."""
        data = _login(client, seed_data["email"], seed_data["password"])
        payload = decode_token(data["access_token"])
        assert "jti" in payload
        assert len(payload["jti"]) == 36  # UUID format

    def test_refresh_token_includes_jti(self, client, seed_data):
        """Refresh tokens should include a jti claim."""
        data = _login(client, seed_data["email"], seed_data["password"])
        payload = decode_token(data["refresh_token"])
        assert "jti" in payload

    def test_logout_revokes_token(self, client, seed_data):
        """After logout, the revoked access token should be rejected."""
        data = _login(client, seed_data["email"], seed_data["password"])
        token = data["access_token"]

        # Logout
        resp = client.post("/api/auth/logout", headers=_auth(token))
        assert resp.status_code == 200

        # Try using the revoked token
        resp = client.get("/api/auth/me", headers=_auth(token))
        assert resp.status_code == 401
        assert "revoked" in resp.json()["detail"].lower()

    def test_old_token_without_jti_still_works(self, client, seed_data, db_session):
        """Tokens without jti (backward compat) should still be accepted."""
        secret = JWT_SECRET or os.environ.get("JWT_SECRET", "test-secret-key-for-jwt-testing-only")
        payload = {
            "sub": seed_data["user_id"],
            "email": seed_data["email"],
            "role": "admin",
            "org_id": seed_data["org_id"],
            "type": "access",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        old_token = pyjwt.encode(payload, secret, algorithm=JWT_ALGORITHM)

        resp = client.get("/api/auth/me", headers=_auth(old_token))
        assert resp.status_code == 200, f"Backward compat failed: {resp.json()}"


# ── Session Tests ────────────────────────────────────────────────────────────


class TestSessions:

    def test_login_creates_session(self, client, seed_data, db_session):
        """Login should create a session row in the database."""
        _login(client, seed_data["email"], seed_data["password"])

        from uuid import UUID
        sessions = db_session.query(UserSession).filter(
            UserSession.user_id == UUID(seed_data["user_id"])
        ).all()
        assert len(sessions) >= 1
        assert sessions[0].revoked_at is None

    def test_list_sessions_returns_active(self, client, seed_data):
        """GET /auth/sessions should return active sessions."""
        data = _login(client, seed_data["email"], seed_data["password"])
        token = data["access_token"]

        resp = client.get("/api/auth/sessions", headers=_auth(token))
        assert resp.status_code == 200
        sessions = resp.json()
        assert len(sessions) >= 1
        assert sessions[0]["is_current"] is True

    def test_revoke_session(self, client, seed_data):
        """DELETE /auth/sessions/{id} should revoke a session."""
        data = _login(client, seed_data["email"], seed_data["password"])
        token = data["access_token"]

        # List sessions
        resp = client.get("/api/auth/sessions", headers=_auth(token))
        sessions = resp.json()
        session_id = sessions[0]["id"]

        # Revoke
        resp = client.delete(f"/api/auth/sessions/{session_id}", headers=_auth(token))
        assert resp.status_code == 200

        # List again — should be empty
        resp = client.get("/api/auth/sessions", headers=_auth(token))
        assert len(resp.json()) == 0

    def test_multiple_sessions_allowed(self, client, seed_data):
        """Multiple logins should create multiple sessions."""
        data1 = _login(client, seed_data["email"], seed_data["password"])
        data2 = _login(client, seed_data["email"], seed_data["password"])

        resp = client.get("/api/auth/sessions", headers=_auth(data2["access_token"]))
        sessions = resp.json()
        assert len(sessions) >= 2


# ── Refresh Rotation Tests ───────────────────────────────────────────────────


class TestRefreshRotation:

    def test_refresh_returns_new_tokens(self, client, seed_data):
        """Refresh should return new access and refresh tokens."""
        data = _login(client, seed_data["email"], seed_data["password"])
        old_access = data["access_token"]
        old_refresh = data["refresh_token"]

        resp = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
        assert resp.status_code == 200
        new_data = resp.json()
        assert new_data["access_token"] != old_access
        assert new_data["refresh_token"] != old_refresh

    def test_old_refresh_token_rejected_after_rotation(self, client, seed_data):
        """After rotation, using the old refresh token should fail."""
        data = _login(client, seed_data["email"], seed_data["password"])
        old_refresh = data["refresh_token"]

        # First refresh (rotates)
        resp = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
        assert resp.status_code == 200

        # Second use of OLD token (should be rejected — theft detection)
        resp = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
        assert resp.status_code == 401
        assert "reuse" in resp.json()["detail"].lower() or "revoked" in resp.json()["detail"].lower()

    def test_reused_rotated_token_revokes_all_sessions(self, client, seed_data):
        """If a rotated refresh token is reused, ALL sessions should be revoked."""
        # Login twice (2 sessions)
        data1 = _login(client, seed_data["email"], seed_data["password"])
        data2 = _login(client, seed_data["email"], seed_data["password"])

        old_refresh = data1["refresh_token"]

        # Rotate first session's token
        resp = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
        assert resp.status_code == 200

        # Reuse old token (theft detection)
        resp = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
        assert resp.status_code == 401

        # Both sessions should now be revoked
        resp = client.get("/api/auth/sessions", headers=_auth(data2["access_token"]))
        sessions = resp.json()
        assert len(sessions) == 0  # All sessions revoked


# ── Rate Limiting Tests ──────────────────────────────────────────────────────


class TestLoginRateLimit:

    @pytest.fixture(autouse=True)
    def reset_limiter(self):
        """Reset the login rate limiter between tests."""
        login_limiter.attempts.clear()
        yield
        login_limiter.attempts.clear()

    def test_login_rate_limit_after_5_failures(self, client, seed_data):
        """After 5 failed logins, the 6th should return 429."""
        login_limiter.attempts.clear()

        for i in range(5):
            resp = client.post("/api/auth/login", json={
                "email": seed_data["email"], "password": "wrong-password",
            })
            assert resp.status_code == 401, f"Attempt {i+1} should fail with 401"

        # 6th attempt should be rate limited
        resp = client.post("/api/auth/login", json={
            "email": seed_data["email"], "password": "wrong-password",
        })
        assert resp.status_code == 429
        assert "too many" in resp.json()["detail"].lower()

    def test_successful_login_resets_rate_limit(self, client, seed_data):
        """A successful login should reset the rate limit counter."""
        login_limiter.attempts.clear()

        # 4 failed attempts
        for _ in range(4):
            client.post("/api/auth/login", json={
                "email": seed_data["email"], "password": "wrong-password",
            })

        # Successful login
        resp = client.post("/api/auth/login", json={
            "email": seed_data["email"], "password": seed_data["password"],
        })
        assert resp.status_code == 200

        # Should be able to fail again without hitting rate limit immediately
        resp = client.post("/api/auth/login", json={
            "email": seed_data["email"], "password": "wrong-password",
        })
        assert resp.status_code == 401  # Not 429


# ── Security Headers Tests ───────────────────────────────────────────────────


class TestSecurityHeaders:

    def test_security_headers_present(self, client, seed_data):
        """All required security headers should be present on responses."""
        resp = client.get("/api/health")
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-XSS-Protection") == "1; mode=block"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "camera=()" in resp.headers.get("Permissions-Policy", "")

    def test_hsts_only_in_production(self, client, seed_data):
        """HSTS header should NOT be present in development."""
        resp = client.get("/api/health")
        assert "Strict-Transport-Security" not in resp.headers


# ── Bootstrap Hardening Tests ────────────────────────────────────────────────


class TestBootstrapHardening:

    def test_bootstrap_disabled_via_env_flag(self, client, override_db):
        """Bootstrap should return 403 when BOOTSTRAP_ENABLED=false."""
        original = os.environ.get("BOOTSTRAP_ENABLED")
        try:
            os.environ["BOOTSTRAP_ENABLED"] = "false"
            resp = client.post("/api/auth/bootstrap", json={
                "org_name": "Should Fail",
                "admin_email": "fail@test.com",
                "admin_password": "password123",
                "admin_name": "Fail",
            })
            assert resp.status_code == 403
            assert "disabled" in resp.json()["detail"].lower()
        finally:
            if original is not None:
                os.environ["BOOTSTRAP_ENABLED"] = original
            else:
                os.environ.pop("BOOTSTRAP_ENABLED", None)

    def test_bootstrap_blocked_after_first_org(self, client, seed_data):
        """Bootstrap should fail when organizations already exist."""
        resp = client.post("/api/auth/bootstrap", json={
            "org_name": "Second Org",
            "admin_email": "second@test.com",
            "admin_password": "password123",
            "admin_name": "Admin 2",
        })
        assert resp.status_code == 400
        assert "already exist" in resp.json()["detail"].lower()


# ── Sessions API Tests ───────────────────────────────────────────────────────


class TestSessionsAPI:

    def test_sessions_list_endpoint(self, client, seed_data):
        """GET /auth/sessions should return session list for authenticated user."""
        data = _login(client, seed_data["email"], seed_data["password"])
        resp = client.get("/api/auth/sessions", headers=_auth(data["access_token"]))
        assert resp.status_code == 200
        sessions = resp.json()
        assert isinstance(sessions, list)
        assert len(sessions) >= 1
        session = sessions[0]
        assert "id" in session
        assert "device_info" in session
        assert "ip_address" in session
        assert "created_at" in session
        assert "is_current" in session

    def test_sessions_revoke_endpoint(self, client, seed_data):
        """DELETE /auth/sessions/{id} should revoke the session."""
        data = _login(client, seed_data["email"], seed_data["password"])
        token = data["access_token"]

        resp = client.get("/api/auth/sessions", headers=_auth(token))
        session_id = resp.json()[0]["id"]

        resp = client.delete(f"/api/auth/sessions/{session_id}", headers=_auth(token))
        assert resp.status_code == 200
        assert "revoked" in resp.json()["message"].lower()

    def test_sessions_unauthenticated_returns_401(self, client, override_db):
        """Sessions endpoint without auth should return 401."""
        resp = client.get("/api/auth/sessions")
        assert resp.status_code == 401
