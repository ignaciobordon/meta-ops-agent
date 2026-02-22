"""
Enhanced Meta Verify Endpoint Tests.
Tests the GET /api/meta/verify endpoint for the new enhanced fields:
token_valid, scopes, recommended_fix.
4 tests covering: token_valid field, scopes field, recommended_fix field,
and all fields present when no connection exists.
"""
import os
import pytest
from unittest.mock import patch, MagicMock
from uuid import UUID, uuid4

from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PG_UUID BEFORE any model imports so SQLite can handle UUID columns.
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from fastapi.testclient import TestClient
from backend.main import app
from backend.src.database.models import (
    Base,
    AdAccount,
    ConnectionStatus,
    MetaConnection,
    Organization,
)
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user, require_any_authenticated


# ── Constants ────────────────────────────────────────────────────────────────

ORG_ID = "00000000-0000-0000-0000-000000000001"
USER_ID = "test-user-id"


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
def client(db_engine):
    """TestClient with get_db, get_current_user, and require_any_authenticated overridden."""
    SessionLocal = sessionmaker(bind=db_engine)

    def _override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def fake_user():
        return {
            "id": USER_ID,
            "email": "test@test.com",
            "role": "admin",
            "org_id": ORG_ID,
        }

    def fake_auth():
        return None

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[require_any_authenticated] = fake_auth
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def seed_organization(db_session):
    """Ensure the test Organization row exists for FK constraints."""
    org = Organization(
        id=UUID(ORG_ID),
        name="Test Org",
        slug="test-org",
    )
    db_session.add(org)
    db_session.commit()


# ── Helper ───────────────────────────────────────────────────────────────────


def _create_connection(db_session, *, status=ConnectionStatus.ACTIVE):
    """Insert a MetaConnection and return its id."""
    conn_id = uuid4()
    conn = MetaConnection(
        id=conn_id,
        org_id=UUID(ORG_ID),
        meta_user_id="meta-user-123",
        access_token_encrypted="encrypted-token-placeholder",
        status=status,
    )
    db_session.add(conn)
    db_session.commit()
    return conn_id


# ── 1. test_verify_returns_token_valid_field ──────────────────────────────────


class TestVerifyReturnsTokenValidField:

    @patch("backend.src.api.meta.MetaService")
    @patch("backend.src.api.meta._get_adapter")
    def test_verify_returns_token_valid_field(
        self, mock_get_adapter, mock_meta_service_cls, db_session, client
    ):
        """Response includes token_valid boolean field."""
        _create_connection(db_session, status=ConnectionStatus.ACTIVE)

        mock_adapter = MagicMock()
        mock_get_adapter.return_value = mock_adapter

        mock_service_instance = MagicMock()
        mock_service_instance.list_org_ad_accounts.return_value = []
        mock_meta_service_cls.return_value = mock_service_instance

        resp = client.get("/api/meta/verify")
        assert resp.status_code == 200

        data = resp.json()
        assert "token_valid" in data, "Response should include 'token_valid' field"
        assert isinstance(data["token_valid"], bool)


# ── 2. test_verify_returns_scopes_field ───────────────────────────────────────


class TestVerifyReturnsScopesField:

    @patch("backend.src.api.meta.MetaService")
    @patch("backend.src.api.meta._get_adapter")
    def test_verify_returns_scopes_field(
        self, mock_get_adapter, mock_meta_service_cls, db_session, client
    ):
        """Response includes scopes as a list."""
        _create_connection(db_session, status=ConnectionStatus.ACTIVE)

        mock_adapter = MagicMock()
        mock_get_adapter.return_value = mock_adapter

        mock_service_instance = MagicMock()
        mock_service_instance.list_org_ad_accounts.return_value = []
        mock_meta_service_cls.return_value = mock_service_instance

        resp = client.get("/api/meta/verify")
        assert resp.status_code == 200

        data = resp.json()
        assert "scopes" in data, "Response should include 'scopes' field"
        assert isinstance(data["scopes"], list)


# ── 3. test_verify_returns_recommended_fix_field ──────────────────────────────


class TestVerifyReturnsRecommendedFixField:

    @patch("backend.src.api.meta.MetaService")
    @patch("backend.src.api.meta._get_adapter")
    def test_verify_returns_recommended_fix_field(
        self, mock_get_adapter, mock_meta_service_cls, db_session, client
    ):
        """Response includes recommended_fix field (may be null when all is well)."""
        _create_connection(db_session, status=ConnectionStatus.ACTIVE)

        mock_adapter = MagicMock()
        mock_get_adapter.return_value = mock_adapter

        mock_service_instance = MagicMock()
        mock_service_instance.list_org_ad_accounts.return_value = []
        mock_meta_service_cls.return_value = mock_service_instance

        resp = client.get("/api/meta/verify")
        assert resp.status_code == 200

        data = resp.json()
        assert "recommended_fix" in data, (
            "Response should include 'recommended_fix' field"
        )
        # recommended_fix can be None or a string
        assert data["recommended_fix"] is None or isinstance(data["recommended_fix"], str)


# ── 4. test_verify_no_connection_has_all_fields ───────────────────────────────


class TestVerifyNoConnectionHasAllFields:

    def test_verify_no_connection_has_all_fields(self, client):
        """When no MetaConnection exists, response still includes all enhanced fields."""
        resp = client.get("/api/meta/verify")
        assert resp.status_code == 200

        data = resp.json()
        assert data["connected"] is False

        # All enhanced fields must be present
        assert "token_valid" in data, "Missing 'token_valid' in no-connection response"
        assert "scopes" in data, "Missing 'scopes' in no-connection response"
        assert "recommended_fix" in data, "Missing 'recommended_fix' in no-connection response"

        # Sensible defaults
        assert data["token_valid"] is False
        assert isinstance(data["scopes"], list)
