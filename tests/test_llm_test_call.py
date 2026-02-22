"""
Sprint 11 -- LLM Test Call Endpoint Tests.
Tests the admin-only POST /api/system/llm/test-call endpoint.
4 tests covering success, 502 on failure, task_type passthrough, and admin auth.
"""
import os
import pytest
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PG_UUID BEFORE any model imports so SQLite can handle UUID columns.
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.main import app
from backend.src.database.models import Base
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user, require_admin


# -- Fixtures -----------------------------------------------------------------


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
    """Override get_db to use the in-memory SQLite engine."""
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
    """TestClient with get_current_user and require_admin overridden."""

    def fake_user():
        return {"user_id": "test-user-id", "org_id": "test-org-id", "role": "admin"}

    def fake_admin():
        return None

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[require_admin] = fake_admin
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# -- 1. test_llm_test_call_success --------------------------------------------


class TestLLMTestCallSuccess:

    @patch("backend.src.llm.router.get_llm_router")
    def test_llm_test_call_success(self, mock_get_router, client):
        """POST /api/system/llm/test-call returns 200 with expected fields
        when the LLM router generates a response successfully."""
        mock_response = MagicMock()
        mock_response.provider = "anthropic"
        mock_response.model = "test-model"
        mock_response.content = {"answer": "hi"}
        mock_response.raw_text = "hi"
        mock_response.latency_ms = 100.0
        mock_response.tokens_used = 10
        mock_response.was_fallback = False

        mock_router = MagicMock()
        mock_router.generate.return_value = mock_response
        mock_get_router.return_value = mock_router

        resp = client.post(
            "/api/system/llm/test-call",
            json={"task_type": "test", "prompt": "hello"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "anthropic"
        assert data["model"] == "test-model"
        assert data["content"] == {"answer": "hi"}
        assert data["raw_text"] == "hi"
        assert data["latency_ms"] == 100.0
        assert data["tokens_used"] == 10
        assert data["was_fallback"] is False


# -- 2. test_llm_test_call_502_on_failure -------------------------------------


class TestLLMTestCall502OnFailure:

    @patch("backend.src.llm.router.get_llm_router")
    def test_llm_test_call_502_on_failure(self, mock_get_router, client):
        """POST /api/system/llm/test-call returns 502 when generate() raises."""
        mock_router = MagicMock()
        mock_router.generate.side_effect = Exception("LLM provider down")
        mock_get_router.return_value = mock_router

        resp = client.post(
            "/api/system/llm/test-call",
            json={"task_type": "test", "prompt": "hello"},
        )

        assert resp.status_code == 502


# -- 3. test_llm_test_call_task_type_passthrough ------------------------------


class TestLLMTestCallTaskTypePassthrough:

    @patch("backend.src.llm.router.get_llm_router")
    def test_llm_test_call_task_type_passthrough(self, mock_get_router, client):
        """The task_type from the request body is passed through to LLMRequest."""
        mock_response = MagicMock()
        mock_response.provider = "anthropic"
        mock_response.model = "test-model"
        mock_response.content = {"answer": "hi"}
        mock_response.raw_text = "hi"
        mock_response.latency_ms = 50.0
        mock_response.tokens_used = 5
        mock_response.was_fallback = False

        mock_router = MagicMock()
        mock_router.generate.return_value = mock_response
        mock_get_router.return_value = mock_router

        resp = client.post(
            "/api/system/llm/test-call",
            json={"task_type": "custom_type", "prompt": "hello"},
        )

        assert resp.status_code == 200

        # Verify generate() was called once and inspect the LLMRequest argument
        mock_router.generate.assert_called_once()
        llm_request = mock_router.generate.call_args[0][0]
        assert llm_request.task_type == "custom_type"


# -- 4. test_llm_test_call_requires_admin -------------------------------------


class TestLLMTestCallRequiresAdmin:

    def test_llm_test_call_requires_admin(self, override_db):
        """Without the admin override the endpoint returns 403."""

        def fake_user():
            return {"user_id": "test-user-id", "org_id": "test-org-id", "role": "viewer"}

        def fake_admin_denied():
            raise HTTPException(status_code=403, detail="Admin access required")

        app.dependency_overrides[get_current_user] = fake_user
        app.dependency_overrides[require_admin] = fake_admin_denied

        with TestClient(app) as c:
            resp = c.post(
                "/api/system/llm/test-call",
                json={"task_type": "test", "prompt": "hello"},
            )

        app.dependency_overrides.clear()

        assert resp.status_code == 403
