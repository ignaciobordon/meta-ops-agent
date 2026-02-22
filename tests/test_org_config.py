"""
Sprint 8: OrgConfig Tests
Tests org config retrieval, update, merge behaviour, feature flags,
and template-default preservation.
7 tests covering /api/org-config and /api/templates install integration.
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
from backend.src.database.models import Base, Organization, OrgTemplate, OrgConfig
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
def mock_user(db_session):
    """Returns a mock user dict matching the shape returned by get_current_user."""
    # Seed an organization
    org_id = uuid4()
    org = Organization(
        id=org_id,
        name="Test Org",
        slug="test-org",
        created_at=datetime.utcnow(),
    )
    db_session.add(org)

    # Seed a template
    template = OrgTemplate(
        id=uuid4(),
        slug="test_tmpl",
        name="Test Template",
        description="desc",
        vertical="test",
        default_config_json={
            "sync_interval_minutes": 15,
            "alert_thresholds": {"ctr_low": 0.8},
        },
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db_session.add(template)
    db_session.commit()

    # Stash IDs on session for easy access in tests
    db_session._test_org_id = str(org_id)
    db_session._test_template_id = str(template.id)

    return {
        "user_id": str(uuid4()),
        "org_id": str(org_id),
        "role": "admin",
        "email": "admin@test-org.com",
    }


@pytest.fixture(scope="function")
def client(override_db, mock_user):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[require_admin] = lambda: mock_user
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


# ── Tests ────────────────────────────────────────────────────────────────────


class TestOrgConfig:

    def test_get_config_empty(self, client, db_session):
        """GET /api/org-config/ with no OrgConfig returns empty config."""
        resp = client.get("/api/org-config/")
        assert resp.status_code == 200

        data = resp.json()
        assert data["config"] == {}
        assert data["feature_flags"] == {}
        assert data["template_id"] is None

    def test_get_config_after_template_install(self, client, db_session):
        """Install template via POST /api/templates/{id}/install, then
        GET /api/org-config/ returns merged config."""
        template_id = db_session._test_template_id

        # Install template
        install_resp = client.post(f"/api/templates/{template_id}/install")
        assert install_resp.status_code == 200

        # Fetch org config
        resp = client.get("/api/org-config/")
        assert resp.status_code == 200

        data = resp.json()
        assert data["template_id"] == template_id
        assert data["config"]["sync_interval_minutes"] == 15
        assert data["config"]["alert_thresholds"]["ctr_low"] == 0.8
        assert "feature_flags" in data

    def test_update_config(self, client, db_session):
        """PUT /api/org-config/ with overrides patches config."""
        resp = client.put(
            "/api/org-config/",
            json={"overrides": {"sync_interval_minutes": 60}},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["config"]["sync_interval_minutes"] == 60

    def test_update_config_merges(self, client, db_session):
        """PUT twice with different keys, both keys present."""
        # First update
        resp1 = client.put(
            "/api/org-config/",
            json={"overrides": {"key_a": "value_a"}},
        )
        assert resp1.status_code == 200

        # Second update with a different key
        resp2 = client.put(
            "/api/org-config/",
            json={"overrides": {"key_b": "value_b"}},
        )
        assert resp2.status_code == 200

        data = resp2.json()
        assert data["config"]["key_a"] == "value_a"
        assert data["config"]["key_b"] == "value_b"

    def test_get_feature_flags_empty(self, client, db_session):
        """GET /api/org-config/feature-flags returns empty dict when no OrgConfig exists."""
        resp = client.get("/api/org-config/feature-flags")
        assert resp.status_code == 200

        data = resp.json()
        assert data == {}

    def test_get_feature_flags_with_data(self, client, db_session):
        """Create OrgConfig with feature_flags_json, verify GET returns them."""
        from uuid import UUID

        org_id = db_session._test_org_id
        org_config = OrgConfig(
            id=uuid4(),
            org_id=UUID(org_id),
            config_json={},
            feature_flags_json={
                "dark_mode": True,
                "beta_dashboard": False,
                "new_onboarding": True,
            },
            created_at=datetime.utcnow(),
        )
        db_session.add(org_config)
        db_session.commit()

        resp = client.get("/api/org-config/feature-flags")
        assert resp.status_code == 200

        data = resp.json()
        assert data["dark_mode"] is True
        assert data["beta_dashboard"] is False
        assert data["new_onboarding"] is True

    def test_config_preserves_template_defaults(self, client, db_session):
        """After install + update, template defaults not in overrides still present."""
        template_id = db_session._test_template_id

        # Install template (sets sync_interval_minutes=15, alert_thresholds.ctr_low=0.8)
        install_resp = client.post(f"/api/templates/{template_id}/install")
        assert install_resp.status_code == 200

        # Override only sync_interval_minutes and add a new key
        update_resp = client.put(
            "/api/org-config/",
            json={"overrides": {"sync_interval_minutes": 120, "custom_key": "custom_value"}},
        )
        assert update_resp.status_code == 200

        # Verify merged config
        get_resp = client.get("/api/org-config/")
        assert get_resp.status_code == 200

        data = get_resp.json()
        # Overridden value
        assert data["config"]["sync_interval_minutes"] == 120
        # New custom key
        assert data["config"]["custom_key"] == "custom_value"
        # Template default not overridden should still be present
        assert data["config"]["alert_thresholds"]["ctr_low"] == 0.8
        # Template association preserved
        assert data["template_id"] == template_id
