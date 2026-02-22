"""
Sprint 11 -- Report Export Endpoint Tests.
Tests the GET /api/reports/decisions/{id}/docx and /xlsx endpoints.
6 tests covering content-type, valid file bytes, 404 handling, and org scoping.
"""
import os
import pytest
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
    Organization,
    MetaConnection,
    AdAccount,
    DecisionPack,
    ConnectionStatus,
    ActionType,
)
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user, require_any_authenticated


# ── Constants ─────────────────────────────────────────────────────────────────

ORG_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_ORG_ID = UUID("00000000-0000-0000-0000-000000000002")


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
            "id": "test-user-id",
            "email": "test@test.com",
            "role": "admin",
            "org_id": "00000000-0000-0000-0000-000000000001",
        }

    def fake_auth():
        return None

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[require_any_authenticated] = fake_auth
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _seed_decision(db_session, org_id=ORG_ID):
    """Create full chain: Organization -> MetaConnection -> AdAccount -> DecisionPack.
    Returns the DecisionPack id."""
    org = Organization(id=org_id, name="Test Org", slug=f"test-org-{org_id}")
    db_session.add(org)
    db_session.flush()

    conn_id = uuid4()
    conn = MetaConnection(
        id=conn_id,
        org_id=org_id,
        meta_user_id="meta-user-123",
        access_token_encrypted="encrypted-token",
        status=ConnectionStatus.ACTIVE,
    )
    db_session.add(conn)
    db_session.flush()

    account_id = uuid4()
    account = AdAccount(
        id=account_id,
        connection_id=conn_id,
        meta_ad_account_id=f"act_{uuid4().hex[:8]}",
        name="Test Ad Account",
        currency="USD",
    )
    db_session.add(account)
    db_session.flush()

    decision_id = uuid4()
    decision = DecisionPack(
        id=decision_id,
        ad_account_id=account_id,
        trace_id=f"trace-{uuid4().hex[:12]}",
        action_type=ActionType.ADSET_PAUSE,
        entity_type="adset",
        entity_id="adset_123456",
        entity_name="Test AdSet",
        action_request={"action": "pause", "entity_id": "adset_123456"},
        rationale="Performance below threshold.",
        source="SaturationEngine",
    )
    db_session.add(decision)
    db_session.commit()

    return decision_id


# ── 1. test_docx_content_type ────────────────────────────────────────────────


class TestDocxContentType:

    def test_docx_content_type(self, client, db_session):
        """GET /api/reports/decisions/{id}/docx returns 200 with DOCX content-type."""
        decision_id = _seed_decision(db_session)

        resp = client.get(f"/api/reports/decisions/{decision_id}/docx")

        assert resp.status_code == 200
        assert "wordprocessingml.document" in resp.headers["content-type"]


# ── 2. test_xlsx_content_type ────────────────────────────────────────────────


class TestXlsxContentType:

    def test_xlsx_content_type(self, client, db_session):
        """GET /api/reports/decisions/{id}/xlsx returns 200 with XLSX content-type."""
        decision_id = _seed_decision(db_session)

        resp = client.get(f"/api/reports/decisions/{decision_id}/xlsx")

        assert resp.status_code == 200
        assert "spreadsheetml.sheet" in resp.headers["content-type"]


# ── 3. test_docx_valid_file ─────────────────────────────────────────────────


class TestDocxValidFile:

    def test_docx_valid_file(self, client, db_session):
        """DOCX response body is non-empty and starts with PK zip signature."""
        decision_id = _seed_decision(db_session)

        resp = client.get(f"/api/reports/decisions/{decision_id}/docx")

        assert resp.status_code == 200
        assert len(resp.content) > 0
        assert resp.content[:2] == b"PK"


# ── 4. test_xlsx_valid_file ─────────────────────────────────────────────────


class TestXlsxValidFile:

    def test_xlsx_valid_file(self, client, db_session):
        """XLSX response body is non-empty and starts with PK zip signature."""
        decision_id = _seed_decision(db_session)

        resp = client.get(f"/api/reports/decisions/{decision_id}/xlsx")

        assert resp.status_code == 200
        assert len(resp.content) > 0
        assert resp.content[:2] == b"PK"


# ── 5. test_404_nonexistent ─────────────────────────────────────────────────


class TestNotFoundNonexistent:

    def test_404_nonexistent_docx(self, client, db_session):
        """GET with a random UUID returns 404 for DOCX."""
        # Seed the org so the user's org exists (otherwise ad_account_ids is empty).
        org = Organization(id=ORG_ID, name="Test Org", slug="test-org-404")
        db_session.add(org)
        db_session.commit()

        random_id = uuid4()
        resp = client.get(f"/api/reports/decisions/{random_id}/docx")

        assert resp.status_code == 404

    def test_404_nonexistent_xlsx(self, client, db_session):
        """GET with a random UUID returns 404 for XLSX."""
        org = Organization(id=ORG_ID, name="Test Org", slug="test-org-404x")
        db_session.add(org)
        db_session.commit()

        random_id = uuid4()
        resp = client.get(f"/api/reports/decisions/{random_id}/xlsx")

        assert resp.status_code == 404


# ── 6. test_org_scoping ─────────────────────────────────────────────────────


class TestOrgScoping:

    def test_org_scoping_docx(self, client, db_session):
        """Decision under a DIFFERENT org's ad account returns 404 (user cannot access)."""
        # Seed a decision under OTHER_ORG_ID (not the authenticated user's org).
        decision_id = _seed_decision(db_session, org_id=OTHER_ORG_ID)

        resp = client.get(f"/api/reports/decisions/{decision_id}/docx")

        assert resp.status_code == 404

    def test_org_scoping_xlsx(self, client, db_session):
        """Decision under a DIFFERENT org's ad account returns 404 (user cannot access)."""
        decision_id = _seed_decision(db_session, org_id=OTHER_ORG_ID)

        resp = client.get(f"/api/reports/decisions/{decision_id}/xlsx")

        assert resp.status_code == 404
