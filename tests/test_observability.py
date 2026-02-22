"""
Observability Tests — X-Request-ID Middleware
Verifies that every response carries an X-Request-ID header:
generated automatically when absent, echoed back when provided.
"""
import os
import re
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

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class TestRequestContext:

    def test_request_id_header_returned(self, client):
        """Every response must include a non-empty X-Request-ID header."""
        resp = client.get("/api/health/live")
        assert "x-request-id" in resp.headers
        assert isinstance(resp.headers["x-request-id"], str)
        assert len(resp.headers["x-request-id"]) > 0

    def test_request_id_propagated(self, client):
        """When the caller sends X-Request-ID, the same value is echoed back."""
        resp = client.get(
            "/api/health/live",
            headers={"X-Request-ID": "custom-trace-123"},
        )
        assert resp.headers["x-request-id"] == "custom-trace-123"

    def test_request_id_generated_if_missing(self, client):
        """When no X-Request-ID is sent, the middleware generates a valid UUID."""
        resp = client.get("/api/health/live")
        request_id = resp.headers.get("x-request-id", "")
        assert len(request_id) == 36
        assert UUID_RE.match(request_id), (
            f"Expected a UUID-shaped value, got: {request_id!r}"
        )
