"""
Test Opportunities Runtime Path — endpoint → enqueue → handler → correct method calls.
Verifies the full chain uses canonical interfaces.
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
from backend.src.middleware.auth import get_current_user


ORG_ID = "00000000-0000-0000-0000-000000000001"


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
def client(db_engine):
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

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = fake_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestOpportunitiesEndpointEnqueuesCorrectJob:

    @patch("backend.src.jobs.queue.enqueue", return_value="fake-job-id")
    def test_endpoint_enqueues_opportunities_analyze(self, mock_enqueue, client):
        """POST /api/opportunities/analyze enqueues 'opportunities_analyze' task."""
        resp = client.post("/api/opportunities/analyze")
        assert resp.status_code == 202

        mock_enqueue.assert_called_once()
        call_kwargs = mock_enqueue.call_args
        assert call_kwargs.kwargs.get("task_name") == "opportunities_analyze" or \
               call_kwargs[0][0] == "opportunities_analyze"


class TestOpportunitiesHandlerUsesBrandMapBuilder:

    def test_task_runner_source_uses_builder_build(self):
        """Verify task_runner.py calls builder.build() for opportunities_analyze."""
        from pathlib import Path
        task_runner_path = Path(__file__).parent.parent / "backend" / "src" / "jobs" / "task_runner.py"
        source = task_runner_path.read_text(encoding="utf-8")

        assert "builder.build(" in source, (
            "task_runner.py should call builder.build() for BrandMap construction"
        )

    def test_task_runner_source_accesses_opportunity_map(self):
        """Verify task_runner.py accesses brand_map.opportunity_map."""
        from pathlib import Path
        task_runner_path = Path(__file__).parent.parent / "backend" / "src" / "jobs" / "task_runner.py"
        source = task_runner_path.read_text(encoding="utf-8")

        assert "brand_map.opportunity_map" in source, (
            "task_runner.py should access brand_map.opportunity_map"
        )


class TestOpportunitiesResponseShape:

    @patch("backend.src.jobs.queue.enqueue", return_value="fake-job-id")
    def test_analyze_returns_job_id_and_status(self, mock_enqueue, client):
        """POST /api/opportunities/analyze returns {job_id, status: 'queued'}."""
        resp = client.post("/api/opportunities/analyze")
        assert resp.status_code == 202

        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "queued"
