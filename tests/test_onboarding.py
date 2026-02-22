"""
Sprint 8 — Onboarding Flow Tests
Tests onboarding status retrieval, step advancement, step-order enforcement,
prerequisite validation, completion, and idempotent advances.
~10 tests covering the full onboarding wizard lifecycle.
"""
import os
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.main import app
from backend.src.database.models import Base, Organization, OnboardingState, OnboardingStatusEnum, OrgTemplate
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user, require_admin


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
def mock_user():
    org_id = uuid4()
    return {
        "id": str(uuid4()),
        "org_id": str(org_id),
        "role": "admin",
        "email": "admin@onboarding-test.com",
        "_org_uuid": org_id,
    }


@pytest.fixture(scope="function")
def client(override_db, db_session, mock_user):
    """TestClient with get_db, get_current_user, and require_admin overridden."""
    org_uuid = mock_user["_org_uuid"]

    # Seed the organization so FK constraints are satisfied
    org = Organization(id=org_uuid, name="Test Org", slug="test-org")
    db_session.add(org)
    db_session.commit()

    def fake_user():
        return mock_user

    def fake_admin():
        return None

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[require_admin] = fake_admin

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Tests ────────────────────────────────────────────────────────────────────


class TestOnboarding:

    def test_get_status_no_state(self, client):
        """GET /api/onboarding/status with no OnboardingState returns pending defaults."""
        resp = client.get("/api/onboarding/status")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        data = resp.json()
        assert data["current_step"] == "pending"
        assert data["meta_connected"] is False
        assert data["account_selected"] is False
        assert data["template_chosen"] is False
        assert data["completed"] is False

    def test_get_status_with_state(self, client, db_session, mock_user):
        """Create an OnboardingState at connect_meta, verify GET returns correct step."""
        from uuid import UUID as _UUID
        state = OnboardingState(
            id=uuid4(),
            org_id=_UUID(mock_user["org_id"]),
            user_id=_UUID(mock_user["id"]),
            current_step=OnboardingStatusEnum.CONNECT_META,
            meta_connected=True,
            account_selected=False,
            template_chosen=False,
        )
        db_session.add(state)
        db_session.commit()

        resp = client.get("/api/onboarding/status")
        assert resp.status_code == 200

        data = resp.json()
        assert data["current_step"] == "connect_meta"
        assert data["meta_connected"] is True
        assert data["account_selected"] is False
        assert data["template_chosen"] is False
        assert data["completed"] is False

    def test_advance_to_connect_meta(self, client):
        """POST /api/onboarding/step/connect_meta succeeds from pending."""
        resp = client.post("/api/onboarding/step/connect_meta")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        data = resp.json()
        assert data["current_step"] == "connect_meta"
        assert data["meta_connected"] is True

    def test_advance_step_order_enforced(self, client):
        """POST choose_template from pending fails because steps cannot be skipped."""
        resp = client.post("/api/onboarding/step/choose_template")
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"

    def test_advance_select_account_requires_meta(self, client, db_session, mock_user):
        """POST select_account without meta_connected fails with 400."""
        # Create state at pending (meta_connected=False) but try to jump to select_account
        from uuid import UUID as _UUID
        state = OnboardingState(
            id=uuid4(),
            org_id=_UUID(mock_user["org_id"]),
            user_id=_UUID(mock_user["id"]),
            current_step=OnboardingStatusEnum.PENDING,
            meta_connected=False,
            account_selected=False,
            template_chosen=False,
        )
        db_session.add(state)
        db_session.commit()

        resp = client.post("/api/onboarding/step/select_account")
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"

    def test_advance_choose_template(self, client, db_session, mock_user):
        """After advancing through prior steps, choose_template with template_id works."""
        # Create a template in the database
        template = OrgTemplate(
            id=uuid4(),
            slug="gym_fitness",
            name="Gym",
            description="test",
            vertical="fitness",
            default_config_json={},
        )
        db_session.add(template)
        db_session.commit()

        # Advance step-by-step: pending -> connect_meta -> select_account -> choose_template
        resp1 = client.post("/api/onboarding/step/connect_meta")
        assert resp1.status_code == 200

        resp2 = client.post("/api/onboarding/step/select_account")
        assert resp2.status_code == 200

        resp3 = client.post(
            "/api/onboarding/step/choose_template",
            json={"template_id": str(template.id)},
        )
        assert resp3.status_code == 200, f"Expected 200, got {resp3.status_code}: {resp3.text}"

        data = resp3.json()
        assert data["current_step"] == "choose_template"
        assert data["template_chosen"] is True
        assert data["selected_template_id"] == str(template.id)

    def test_advance_invalid_step(self, client):
        """POST /api/onboarding/step/invalid returns 400 for unknown step name."""
        resp = client.post("/api/onboarding/step/invalid")
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"

    def test_complete_onboarding(self, client, db_session, mock_user):
        """POST /api/onboarding/complete sets completed_at and marks completed=true."""
        # Advance to at least one step so an OnboardingState exists
        client.post("/api/onboarding/step/connect_meta")

        resp = client.post("/api/onboarding/complete")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        data = resp.json()
        assert data["completed"] is True
        assert data["current_step"] == "completed"

        # Verify completed_at is set in the database
        from uuid import UUID as _UUID
        state = db_session.query(OnboardingState).filter(
            OnboardingState.org_id == _UUID(mock_user["org_id"]),
        ).first()
        assert state is not None
        assert state.completed_at is not None

    def test_status_shows_completed(self, client):
        """After complete, GET /api/onboarding/status shows completed=true."""
        # Advance and complete
        client.post("/api/onboarding/step/connect_meta")
        client.post("/api/onboarding/complete")

        resp = client.get("/api/onboarding/status")
        assert resp.status_code == 200

        data = resp.json()
        assert data["completed"] is True
        assert data["current_step"] == "completed"

    def test_idempotent_step_advance(self, client):
        """Advancing to the same step twice is idempotent (no error on repeat)."""
        resp1 = client.post("/api/onboarding/step/connect_meta")
        assert resp1.status_code == 200

        # Advance to connect_meta again — should be idempotent
        resp2 = client.post("/api/onboarding/step/connect_meta")
        assert resp2.status_code == 200

        data = resp2.json()
        assert data["current_step"] == "connect_meta"
        assert data["meta_connected"] is True
