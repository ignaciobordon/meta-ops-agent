"""
Meta Verify Endpoint Tests.
Tests the GET /api/meta/verify endpoint for connection health checks.
4 tests covering: connected state, no connection, API unreachable, ad account count.
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


def _create_ad_accounts(db_session, connection_id, count=1):
    """Insert *count* AdAccount rows linked to *connection_id*."""
    for i in range(count):
        acct = AdAccount(
            id=uuid4(),
            connection_id=connection_id,
            meta_ad_account_id=f"act_{uuid4().hex[:8]}",
            name=f"Ad Account {i + 1}",
            currency="USD",
        )
        db_session.add(acct)
    db_session.commit()


# ── 1. test_verify_connected ─────────────────────────────────────────────────


class TestVerifyConnected:

    @patch("backend.src.api.meta.MetaService")
    @patch("backend.src.api.meta._get_adapter")
    def test_verify_connected(
        self, mock_get_adapter, mock_meta_service_cls, db_session, client
    ):
        """Active connection with 2 ad accounts returns connected=True,
        ad_accounts_count=2, connection_status='active'."""
        conn_id = _create_connection(db_session, status=ConnectionStatus.ACTIVE)
        _create_ad_accounts(db_session, conn_id, count=2)

        mock_adapter = MagicMock()
        mock_get_adapter.return_value = mock_adapter

        mock_service_instance = MagicMock()
        mock_service_instance.list_org_ad_accounts.return_value = []
        mock_meta_service_cls.return_value = mock_service_instance

        resp = client.get("/api/meta/verify")
        assert resp.status_code == 200

        data = resp.json()
        assert data["connected"] is True
        assert data["ad_accounts_count"] == 2
        assert data["connection_status"] == "active"
        assert data["api_reachable"] is True
        assert data["error"] is None


# ── 2. test_verify_no_connection ─────────────────────────────────────────────


class TestVerifyNoConnection:

    def test_verify_no_connection(self, client):
        """When no MetaConnection exists, connected=False and error mentions
        'No Meta connection'."""
        resp = client.get("/api/meta/verify")
        assert resp.status_code == 200

        data = resp.json()
        assert data["connected"] is False
        assert "No Meta connection" in data["error"]


# ── 3. test_verify_api_unreachable ───────────────────────────────────────────


class TestVerifyApiUnreachable:

    @patch("backend.src.api.meta.MetaService")
    @patch("backend.src.api.meta._get_adapter")
    def test_verify_api_unreachable(
        self, mock_get_adapter, mock_meta_service_cls, db_session, client
    ):
        """When MetaService.list_org_ad_accounts raises, api_reachable=False
        and error is populated."""
        _create_connection(db_session, status=ConnectionStatus.ACTIVE)

        mock_adapter = MagicMock()
        mock_get_adapter.return_value = mock_adapter

        mock_service_instance = MagicMock()
        mock_service_instance.list_org_ad_accounts.side_effect = Exception(
            "Token expired or network error"
        )
        mock_meta_service_cls.return_value = mock_service_instance

        resp = client.get("/api/meta/verify")
        assert resp.status_code == 200

        data = resp.json()
        assert data["api_reachable"] is False
        assert data["error"] is not None


# ── 4. test_verify_ad_account_count ──────────────────────────────────────────


class TestVerifyAdAccountCount:

    @patch("backend.src.api.meta.MetaService")
    @patch("backend.src.api.meta._get_adapter")
    def test_verify_ad_account_count(
        self, mock_get_adapter, mock_meta_service_cls, db_session, client
    ):
        """Creating 3 ad accounts returns ad_accounts_count=3."""
        conn_id = _create_connection(db_session, status=ConnectionStatus.ACTIVE)
        _create_ad_accounts(db_session, conn_id, count=3)

        mock_adapter = MagicMock()
        mock_get_adapter.return_value = mock_adapter

        mock_service_instance = MagicMock()
        mock_service_instance.list_org_ad_accounts.return_value = []
        mock_meta_service_cls.return_value = mock_service_instance

        resp = client.get("/api/meta/verify")
        assert resp.status_code == 200

        data = resp.json()
        assert data["ad_accounts_count"] == 3
