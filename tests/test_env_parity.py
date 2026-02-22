"""
Env Parity Endpoint Tests.
Tests the GET /api/system/env/parity endpoint for environment diagnostics.
4 tests covering: 200 access, response shape, db_ok flag, missing_vars type.
"""
import os

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

import pytest
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

from fastapi.testclient import TestClient
from backend.main import app
from backend.src.database.models import Base
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user, require_admin


# ── Constants ────────────────────────────────────────────────────────────────

ORG_ID = "00000000-0000-0000-0000-000000000001"


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
    """TestClient with get_db, get_current_user, and require_admin overridden."""
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
            "org_id": ORG_ID,
        }

    def fake_admin():
        return None

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[require_admin] = fake_admin
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── 1. test_env_parity_returns_200 ────────────────────────────────────────────


class TestEnvParityReturns200:

    def test_env_parity_returns_200(self, client):
        """GET /api/system/env/parity returns 200 for an admin user."""
        resp = client.get("/api/system/env/parity")
        assert resp.status_code == 200


# ── 2. test_env_parity_response_shape ─────────────────────────────────────────


class TestEnvParityResponseShape:

    def test_env_parity_response_shape(self, client):
        """Response JSON contains all expected top-level fields."""
        resp = client.get("/api/system/env/parity")
        assert resp.status_code == 200

        data = resp.json()
        expected_fields = [
            "env_vars_ok",
            "redis_ok",
            "db_ok",
            "llm_keys_ok",
            "celery_ok",
            "missing_vars",
        ]
        for field in expected_fields:
            assert field in data, f"Missing field '{field}' in env/parity response"


# ── 3. test_env_parity_db_ok_true ─────────────────────────────────────────────


class TestEnvParityDbOkTrue:

    def test_env_parity_db_ok_true(self, client):
        """Since we use in-memory SQLite and SessionLocal works, db_ok should be True."""
        resp = client.get("/api/system/env/parity")
        assert resp.status_code == 200

        data = resp.json()
        assert data["db_ok"] is True


# ── 4. test_env_parity_missing_vars_list ──────────────────────────────────────


class TestEnvParityMissingVarsList:

    def test_env_parity_missing_vars_list(self, client):
        """missing_vars is always a list (possibly empty)."""
        resp = client.get("/api/system/env/parity")
        assert resp.status_code == 200

        data = resp.json()
        assert isinstance(data["missing_vars"], list)
