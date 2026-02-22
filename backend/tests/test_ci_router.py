"""
Tests for CI module — Router (registered in main.py at /api/ci).

These tests verify:
1. Router IS registered in the main app
2. Router endpoints work when mounted directly
"""
import pytest
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.src.ci.router import router as ci_router


class TestCIRouterRegistered:
    """Verify the CI router is registered in main.py."""

    def test_router_in_main_app(self):
        """CI router must be registered in main.py at /api/ci."""
        from backend.main import app

        ci_paths = []
        for route in app.routes:
            path = getattr(route, "path", "")
            if "/ci/" in path:
                ci_paths.append(path)
        assert len(ci_paths) > 0, "CI router not found in main app routes"

    def test_ci_endpoints_require_auth(self):
        """CI endpoints should require authentication (401/403)."""
        from backend.main import app

        client = TestClient(app)
        resp = client.get("/api/ci/competitors")
        assert resp.status_code in (401, 403), (
            f"Expected 401/403, got {resp.status_code}. Auth may not be enforced."
        )


class TestCIRouterMounted:
    """Test CI router when mounted on a test app."""

    @pytest.fixture
    def app(self):
        """Create a minimal test app with CI router mounted."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from backend.src.database.models import Base, Organization
        import backend.src.ci.models  # noqa: F401 — ensure CI tables are registered

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)

        # Create org
        session = Session()
        org_id = uuid4()
        org = Organization(id=org_id, name="Test", slug="test")
        session.add(org)
        session.commit()
        session.close()

        test_app = FastAPI()

        # Override dependencies
        def get_test_db():
            db = Session()
            try:
                yield db
            finally:
                db.close()

        def get_test_user():
            return {"user_id": str(uuid4()), "org_id": str(org_id), "role": "admin"}

        from backend.src.database.session import get_db
        from backend.src.middleware.auth import get_current_user

        test_app.include_router(ci_router, prefix="/api/ci")
        test_app.dependency_overrides[get_db] = get_test_db
        test_app.dependency_overrides[get_current_user] = get_test_user

        return test_app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_create_competitor(self, client):
        resp = client.post("/api/ci/competitors", json={
            "name": "Rival Corp",
            "website_url": "https://rival.com",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Rival Corp"
        assert data["status"] == "active"

    def test_list_competitors_empty(self, client):
        resp = client.get("/api/ci/competitors")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_competitors_with_data(self, client):
        client.post("/api/ci/competitors", json={"name": "A"})
        client.post("/api/ci/competitors", json={"name": "B"})
        resp = client.get("/api/ci/competitors")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_competitor(self, client):
        create_resp = client.post("/api/ci/competitors", json={"name": "Find Me"})
        comp_id = create_resp.json()["id"]
        resp = client.get(f"/api/ci/competitors/{comp_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Find Me"

    def test_get_competitor_not_found(self, client):
        resp = client.get(f"/api/ci/competitors/{uuid4()}")
        assert resp.status_code == 404

    def test_update_competitor(self, client):
        create_resp = client.post("/api/ci/competitors", json={"name": "Old"})
        comp_id = create_resp.json()["id"]
        resp = client.patch(f"/api/ci/competitors/{comp_id}", json={"name": "New"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "New"

    def test_delete_competitor(self, client):
        create_resp = client.post("/api/ci/competitors", json={"name": "Bye"})
        comp_id = create_resp.json()["id"]
        resp = client.delete(f"/api/ci/competitors/{comp_id}")
        assert resp.status_code == 204

    def test_create_source(self, client):
        resp = client.post("/api/ci/sources", json={
            "name": "Meta Ads",
            "source_type": "meta_ad_library",
        })
        assert resp.status_code == 201
        assert resp.json()["source_type"] == "meta_ad_library"

    def test_list_sources(self, client):
        client.post("/api/ci/sources", json={"name": "S1", "source_type": "manual"})
        resp = client.get("/api/ci/sources")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
