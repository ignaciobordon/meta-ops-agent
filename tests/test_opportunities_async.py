"""
Sprint 10 -- Async Opportunities Endpoint Tests.
Tests the POST /api/opportunities/analyze endpoint (202 async queue).
5 tests covering response shape, enqueue call, dispatch mapping, queue routing, backoff policy.
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

from fastapi.testclient import TestClient
from backend.main import app
from backend.src.database.models import Base
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user


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
    """TestClient with get_current_user overridden to return an admin user."""

    def fake_user():
        return {
            "id": "test-user-id",
            "email": "test@test.com",
            "role": "admin",
            "org_id": "00000000-0000-0000-0000-000000000001",
        }

    app.dependency_overrides[get_current_user] = fake_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# -- 1. test_analyze_returns_202 ----------------------------------------------


class TestAnalyzeReturns202:

    @patch("backend.src.jobs.queue.enqueue", return_value="fake-job-id")
    def test_analyze_returns_202(self, mock_enqueue, client):
        """POST /api/opportunities/analyze returns 202 with job_id and status='queued'."""
        resp = client.post("/api/opportunities/analyze")
        assert resp.status_code == 202

        data = resp.json()
        assert data["job_id"] == "fake-job-id"
        assert data["status"] == "queued"


# -- 2. test_analyze_creates_job_run ------------------------------------------


class TestAnalyzeCreatesJobRun:

    @patch("backend.src.jobs.queue.enqueue", return_value="fake-job-id")
    def test_analyze_creates_job_run(self, mock_enqueue, client):
        """enqueue is called with task_name='opportunities_analyze'."""
        client.post("/api/opportunities/analyze")

        mock_enqueue.assert_called_once()
        call_kwargs = mock_enqueue.call_args
        assert call_kwargs.kwargs.get("task_name") or call_kwargs[0][0] == "opportunities_analyze"
        # Verify task_name via keyword argument
        if call_kwargs.kwargs.get("task_name"):
            assert call_kwargs.kwargs["task_name"] == "opportunities_analyze"
        else:
            assert call_kwargs[0][0] == "opportunities_analyze"


# -- 3. test_analyze_dispatch_exists ------------------------------------------


class TestAnalyzeDispatchExists:

    def test_analyze_dispatch_exists(self):
        """'opportunities_analyze' is handled inside _dispatch in the task_runner module."""
        import inspect
        from backend.src.jobs import task_runner

        source = inspect.getsource(task_runner._dispatch)
        assert "opportunities_analyze" in source


# -- 4. test_queue_routing_includes_opportunities -----------------------------


class TestQueueRoutingIncludesOpportunities:

    def test_queue_routing_includes_opportunities(self):
        """QUEUE_ROUTING maps 'opportunities_analyze' to the 'llm' queue."""
        from backend.src.jobs.queue import QUEUE_ROUTING

        assert "opportunities_analyze" in QUEUE_ROUTING
        assert QUEUE_ROUTING["opportunities_analyze"] == "llm"


# -- 5. test_backoff_policy_exists --------------------------------------------


class TestBackoffPolicyExists:

    def test_backoff_policy_exists(self):
        """BACKOFF_POLICIES contains an entry for 'opportunities_analyze'."""
        from backend.src.retries.backoff import BACKOFF_POLICIES

        assert "opportunities_analyze" in BACKOFF_POLICIES
