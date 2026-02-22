"""
Sprint 3 – BLOQUE 7: Rate Limiting Tests
Tests for rate limiting: 429 responses, Retry-After header, user-aware identification.
"""
import asyncio
import os
import pytest
from uuid import uuid4
from datetime import datetime
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.main import app
from backend.src.database.models import Base, Organization, User, UserOrgRole, RoleEnum
from backend.src.database.session import get_db
from backend.src.middleware.auth import create_access_token, hash_password
from backend.src.middleware.rate_limit import RateLimiter, RateLimitMiddleware


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
def client(override_db):
    return TestClient(app)


# ── Tests ────────────────────────────────────────────────────────────────────


class TestRateLimit:

    def test_rate_limit_returns_429(self):
        """After exhausting the allowed rate, the next call must be denied."""

        async def _run():
            limiter = RateLimiter(rate=3, window=60)

            # First 3 requests should be allowed
            for i in range(3):
                allowed, headers = await limiter.is_allowed("test-client")
                assert allowed is True, f"Request {i+1} should be allowed"

            # 4th request should be denied
            allowed, headers = await limiter.is_allowed("test-client")
            assert allowed is False, "4th request should be denied (rate=3)"

        asyncio.run(_run())

    def test_rate_limit_retry_after_header(self):
        """When rate limit is exceeded, headers must include Retry-After."""

        async def _run():
            limiter = RateLimiter(rate=3, window=60)

            # Exhaust the bucket
            for _ in range(3):
                await limiter.is_allowed("test-client")

            # The denied response should carry Retry-After
            allowed, headers = await limiter.is_allowed("test-client")
            assert allowed is False
            assert "Retry-After" in headers, "Denied response must include Retry-After header"
            retry_after = int(headers["Retry-After"])
            assert retry_after > 0, "Retry-After must be a positive integer"

        asyncio.run(_run())

    def test_rate_limit_by_user_id(self, db_session, override_db):
        """Middleware should identify authenticated users as 'user:<org>:<id>'."""
        # Seed an org + user so the JWT payload is valid
        org_id = uuid4()
        org = Organization(
            id=org_id, name="RL Test Corp", slug="rl-test",
            operator_armed=True, created_at=datetime.utcnow(),
        )
        db_session.add(org)

        user_id = uuid4()
        user = User(
            id=user_id,
            email="rl@test.com",
            name="Rate Limit User",
            password_hash=hash_password("pass123"),
            created_at=datetime.utcnow(),
        )
        db_session.add(user)

        role = UserOrgRole(
            id=uuid4(), user_id=user_id, org_id=org_id,
            role=RoleEnum.VIEWER, assigned_at=datetime.utcnow(),
        )
        db_session.add(role)
        db_session.commit()

        # Create a valid JWT for this user
        token = create_access_token(
            user_id=str(user_id),
            email="rl@test.com",
            role="viewer",
            org_id=str(org_id),
        )

        # Build a mock Request carrying the JWT
        mock_request = MagicMock()
        mock_request.headers = {"Authorization": f"Bearer {token}"}
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"

        middleware = RateLimitMiddleware(app)
        client_id = middleware._get_client_id(mock_request)

        assert client_id.startswith("user:"), (
            f"Authenticated request should be identified as 'user:…', got: {client_id}"
        )
        assert str(org_id) in client_id
        assert str(user_id) in client_id

    def test_rate_limit_excluded_paths(self, client):
        """Excluded paths (e.g. /api/health/live) must NOT carry rate-limit headers."""
        resp = client.get("/api/health/live")
        assert resp.status_code == 200

        assert "X-RateLimit-Limit" not in resp.headers, (
            "Excluded path should not have X-RateLimit-Limit header"
        )
        assert "X-RateLimit-Remaining" not in resp.headers, (
            "Excluded path should not have X-RateLimit-Remaining header"
        )
