"""
Sprint 3 – BLOQUE 8: Health + Error Handling Tests
Tests for health endpoints and structured error responses.
"""
import os
import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.main import app
from backend.src.database.models import Base
from backend.src.database.session import get_db


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


class TestHealthAndErrors:

    def test_health_live_returns_200(self, client):
        """GET /api/health/live returns 200 with alive=true and uptime_seconds."""
        resp = client.get("/api/health/live")
        assert resp.status_code == 200
        data = resp.json()
        assert data["alive"] is True
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], (int, float))
        assert data["uptime_seconds"] >= 0

    def test_health_ready_returns_status(self, client):
        """GET /api/health/ready returns response with 'ready' key (True or False)."""
        resp = client.get("/api/health/ready")
        # Readiness probe returns 200 when ready, 503 when not
        assert resp.status_code in (200, 503)
        data = resp.json()
        assert "ready" in data
        assert isinstance(data["ready"], bool)

    def test_health_full_returns_dependencies(self, client):
        """GET /api/health returns response with dependency checks for
        database, chromadb, anthropic_api, meta_api, and disk_space."""
        resp = client.get("/api/health")
        # Full health check returns 200, 207, or 503 depending on dependency state
        assert resp.status_code in (200, 207, 503)
        data = resp.json()
        assert "dependencies" in data
        deps = data["dependencies"]
        for expected_dep in ("database", "chromadb", "anthropic_api", "meta_api", "disk_space"):
            assert expected_dep in deps, f"Missing dependency: {expected_dep}"
            assert "status" in deps[expected_dep]

    def test_404_returns_structured_error(self, client):
        """GET to a non-existent path returns 404 with structured error body
        containing code, message, and request_id."""
        resp = client.get("/api/nonexistent-path-xyz123")
        assert resp.status_code == 404
        data = resp.json()
        assert "error" in data
        error = data["error"]
        assert error["code"] == "HTTP_404"
        assert error["message"] == "Not Found"
        assert "request_id" in error

    def test_validation_error_returns_422(self, client):
        """POST /api/auth/login with empty body triggers a 422 validation error
        wrapped in the structured error format."""
        resp = client.post("/api/auth/login", json={})
        assert resp.status_code == 422
        data = resp.json()
        assert "error" in data
        error = data["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert error["message"] == "Request validation failed"
        assert "details" in error
        assert isinstance(error["details"], list)
        assert len(error["details"]) > 0
