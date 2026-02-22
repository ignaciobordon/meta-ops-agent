"""
Sprint 8: Templates + Org Config Tests
Tests template listing, detail, install, org config retrieval and update.
8 tests covering /api/templates and /api/org-config endpoints.
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

    # Seed an organization
    org_id = uuid4()
    org = Organization(
        id=org_id,
        name="Test Org",
        slug="test-org",
        created_at=datetime.utcnow(),
    )
    session.add(org)

    # Seed templates
    template_fitness = OrgTemplate(
        id=uuid4(),
        slug="gym_fitness",
        name="Gym / Fitness",
        description="Gym template",
        vertical="fitness",
        default_config_json={
            "sync_interval_minutes": 15,
            "alert_thresholds": {"ctr_low": 0.8},
        },
        is_active=True,
        created_at=datetime.utcnow(),
    )
    session.add(template_fitness)

    template_ecom = OrgTemplate(
        id=uuid4(),
        slug="ecommerce",
        name="E-Commerce",
        description="E-Commerce template",
        vertical="ecommerce",
        default_config_json={
            "sync_interval_minutes": 30,
            "alert_thresholds": {"roas_low": 1.5},
        },
        is_active=True,
        created_at=datetime.utcnow(),
    )
    session.add(template_ecom)

    session.commit()

    # Stash IDs on session for easy access in tests
    session._test_org_id = str(org_id)
    session._test_template_fitness_id = str(template_fitness.id)
    session._test_template_ecom_id = str(template_ecom.id)

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
    return {
        "user_id": str(uuid4()),
        "org_id": db_session._test_org_id,
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


class TestTemplates:

    def test_list_templates(self, client, db_session):
        """GET /api/templates/ returns seeded templates."""
        resp = client.get("/api/templates/")
        assert resp.status_code == 200

        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2

        slugs = {t["slug"] for t in data}
        assert "gym_fitness" in slugs
        assert "ecommerce" in slugs

        # Verify structure of one template
        for t in data:
            assert "id" in t
            assert "slug" in t
            assert "name" in t
            assert "description" in t
            assert "vertical" in t
            assert "default_config" in t

    def test_get_template_detail(self, client, db_session):
        """GET /api/templates/{id} returns correct template."""
        template_id = db_session._test_template_fitness_id
        resp = client.get(f"/api/templates/{template_id}")
        assert resp.status_code == 200

        data = resp.json()
        assert data["id"] == template_id
        assert data["slug"] == "gym_fitness"
        assert data["name"] == "Gym / Fitness"
        assert data["description"] == "Gym template"
        assert data["vertical"] == "fitness"
        assert data["default_config"]["sync_interval_minutes"] == 15
        assert data["default_config"]["alert_thresholds"]["ctr_low"] == 0.8

    def test_get_template_not_found(self, client, db_session):
        """GET /api/templates/{random_uuid} returns 404."""
        random_id = str(uuid4())
        resp = client.get(f"/api/templates/{random_id}")
        assert resp.status_code == 404

    def test_install_template(self, client, db_session):
        """POST /api/templates/{id}/install creates OrgConfig."""
        template_id = db_session._test_template_fitness_id
        resp = client.post(f"/api/templates/{template_id}/install")
        assert resp.status_code == 200

        data = resp.json()
        assert data["message"] == "Template installed"
        assert data["template_id"] == template_id
        assert data["config"]["sync_interval_minutes"] == 15
        assert data["config"]["alert_thresholds"]["ctr_low"] == 0.8

    def test_install_template_with_overrides(self, client, db_session):
        """POST install with overrides merges correctly."""
        template_id = db_session._test_template_fitness_id
        overrides = {
            "sync_interval_minutes": 60,
            "custom_field": "custom_value",
        }
        resp = client.post(
            f"/api/templates/{template_id}/install",
            json={"overrides": overrides},
        )
        assert resp.status_code == 200

        data = resp.json()
        config = data["config"]
        # Override should replace the default
        assert config["sync_interval_minutes"] == 60
        # New field should be present
        assert config["custom_field"] == "custom_value"
        # Original nested field from template defaults should be preserved
        assert config["alert_thresholds"]["ctr_low"] == 0.8

    def test_install_template_not_found(self, client, db_session):
        """POST /api/templates/{bad_id}/install returns 404."""
        bad_id = str(uuid4())
        resp = client.post(f"/api/templates/{bad_id}/install")
        assert resp.status_code == 404

    def test_get_org_config_after_install(self, client, db_session):
        """GET /api/org-config/ returns merged config after install."""
        # First install a template
        template_id = db_session._test_template_ecom_id
        install_resp = client.post(f"/api/templates/{template_id}/install")
        assert install_resp.status_code == 200

        # Now fetch org config
        resp = client.get("/api/org-config/")
        assert resp.status_code == 200

        data = resp.json()
        assert data["template_id"] == template_id
        assert data["config"]["sync_interval_minutes"] == 30
        assert data["config"]["alert_thresholds"]["roas_low"] == 1.5
        assert "feature_flags" in data

    def test_update_org_config(self, client, db_session):
        """PUT /api/org-config/ patches existing config."""
        # Install a template first to create an OrgConfig row
        template_id = db_session._test_template_fitness_id
        install_resp = client.post(f"/api/templates/{template_id}/install")
        assert install_resp.status_code == 200

        # Update with overrides via PUT
        update_resp = client.put(
            "/api/org-config/",
            json={"overrides": {"sync_interval_minutes": 120, "new_key": "new_value"}},
        )
        assert update_resp.status_code == 200

        data = update_resp.json()
        # The updated values should be present
        assert data["config"]["sync_interval_minutes"] == 120
        assert data["config"]["new_key"] == "new_value"
        # Template default that was not overridden should still be merged in
        assert data["config"]["alert_thresholds"]["ctr_low"] == 0.8
        assert data["template_id"] == template_id
