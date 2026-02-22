"""
Sprint 7 -- BLOQUE 8: Ops Console API Tests.
Tests the admin-only endpoints for job monitoring, retry/cancel,
provider health, and queue statistics.
10 tests covering GET /api/ops/jobs, POST retry/cancel, GET queues.
"""
import os
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PG_UUID BEFORE any model imports so SQLite can handle UUID columns.
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.main import app
from backend.src.database.models import (
    Base,
    JobRun,
    JobRunStatus,
    Organization,
)
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
def org_id(db_session):
    """Create an Organization row and return its id."""
    _org_id = uuid4()
    org = Organization(
        id=_org_id,
        name="Ops Test Org",
        slug=f"ops-test-{_org_id.hex[:8]}",
        created_at=datetime.utcnow(),
    )
    db_session.add(org)
    db_session.commit()
    return _org_id


@pytest.fixture(scope="function")
def user_id():
    """Return a fake user id for the overridden auth dependency."""
    return uuid4()


@pytest.fixture(scope="function")
def client(override_db, db_session, org_id, user_id):
    """TestClient with get_current_user and require_admin overridden."""

    def fake_user():
        return {"user_id": str(user_id), "org_id": str(org_id), "role": "admin"}

    def fake_admin():
        return None

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[require_admin] = fake_admin
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Seed helpers ─────────────────────────────────────────────────────────────


def _make_job(org_id, **overrides):
    """Create a JobRun with sensible defaults; caller can override any field."""
    defaults = {
        "org_id": org_id,
        "job_type": "meta_sync_assets",
        "status": JobRunStatus.QUEUED,
        "payload_json": {"account_id": "act_123"},
    }
    defaults.update(overrides)
    return JobRun(**defaults)


@pytest.fixture(scope="function")
def seed_jobs(db_session, org_id):
    """Seed several JobRun rows with different statuses and types.
    Returns a dict mapping descriptive keys to job ids (as strings)."""
    now = datetime.utcnow()

    queued_job = _make_job(
        org_id,
        status=JobRunStatus.QUEUED,
        job_type="meta_sync_assets",
    )
    running_job = _make_job(
        org_id,
        status=JobRunStatus.RUNNING,
        job_type="meta_sync_insights",
        started_at=now - timedelta(minutes=5),
    )
    succeeded_job = _make_job(
        org_id,
        status=JobRunStatus.SUCCEEDED,
        job_type="meta_sync_assets",
        started_at=now - timedelta(minutes=10),
        finished_at=now - timedelta(minutes=8),
    )
    failed_job = _make_job(
        org_id,
        status=JobRunStatus.FAILED,
        job_type="meta_sync_insights",
        started_at=now - timedelta(minutes=15),
        finished_at=now - timedelta(minutes=14),
        last_error_code="API_ERROR",
        last_error_message="Meta API returned 500",
        attempts=2,
        max_attempts=5,
    )
    dead_job = _make_job(
        org_id,
        status=JobRunStatus.DEAD,
        job_type="meta_live_monitor",
        started_at=now - timedelta(minutes=30),
        finished_at=now - timedelta(minutes=29),
        last_error_code="MAX_RETRIES",
        last_error_message="Exhausted all 5 attempts",
        attempts=5,
        max_attempts=5,
    )

    db_session.add_all([queued_job, running_job, succeeded_job, failed_job, dead_job])
    db_session.commit()

    return {
        "queued": str(queued_job.id),
        "running": str(running_job.id),
        "succeeded": str(succeeded_job.id),
        "failed": str(failed_job.id),
        "dead": str(dead_job.id),
    }


# ── 1. test_list_jobs ────────────────────────────────────────────────────────


class TestListJobs:

    def test_list_jobs(self, client, seed_jobs):
        """GET /api/ops/jobs returns 200 with all seeded jobs."""
        resp = client.get("/api/ops/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 5


# ── 2. test_list_jobs_filter_status ───────────────────────────────────────────


class TestListJobsFilterStatus:

    def test_list_jobs_filter_status(self, client, seed_jobs):
        """GET /api/ops/jobs?status=queued returns only queued jobs."""
        resp = client.get("/api/ops/jobs?status=queued")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "queued"
        assert data[0]["id"] == seed_jobs["queued"]


# ── 3. test_list_jobs_filter_type ─────────────────────────────────────────────


class TestListJobsFilterType:

    def test_list_jobs_filter_type(self, client, seed_jobs):
        """GET /api/ops/jobs?job_type=meta_sync_assets returns only matching jobs."""
        resp = client.get("/api/ops/jobs?job_type=meta_sync_assets")
        assert resp.status_code == 200
        data = resp.json()
        # Seeded 2 meta_sync_assets jobs: queued + succeeded
        assert len(data) == 2
        for job in data:
            assert job["job_type"] == "meta_sync_assets"


# ── 4. test_get_job_detail ────────────────────────────────────────────────────


class TestGetJobDetail:

    def test_get_job_detail(self, client, seed_jobs):
        """GET /api/ops/jobs/{id} returns 200 with full job details."""
        job_id = seed_jobs["failed"]
        resp = client.get(f"/api/ops/jobs/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == job_id
        assert data["status"] == "failed"
        assert data["job_type"] == "meta_sync_insights"
        assert data["last_error_code"] == "API_ERROR"
        assert data["last_error_message"] == "Meta API returned 500"
        assert data["attempts"] == 2
        assert data["max_attempts"] == 5


# ── 5. test_get_job_not_found ─────────────────────────────────────────────────


class TestGetJobNotFound:

    def test_get_job_not_found(self, client, seed_jobs):
        """GET /api/ops/jobs/{fake_id} returns 404."""
        fake_id = str(uuid4())
        resp = client.get(f"/api/ops/jobs/{fake_id}")
        assert resp.status_code == 404


# ── 6. test_retry_failed_job ─────────────────────────────────────────────────


class TestRetryFailedJob:

    @patch("backend.src.jobs.queue.enqueue", return_value="new-run-id")
    def test_retry_failed_job(self, mock_enqueue, client, seed_jobs):
        """POST /api/ops/jobs/{failed_id}/retry returns 200 and re-enqueues."""
        job_id = seed_jobs["failed"]
        resp = client.post(f"/api/ops/jobs/{job_id}/retry")
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Job re-enqueued"
        assert data["new_job_run_id"] == "new-run-id"
        mock_enqueue.assert_called_once()


# ── 7. test_retry_succeeded_job_fails ─────────────────────────────────────────


class TestRetrySucceededJobFails:

    def test_retry_succeeded_job_fails(self, client, seed_jobs):
        """POST /api/ops/jobs/{succeeded_id}/retry returns 400 (not retryable)."""
        job_id = seed_jobs["succeeded"]
        resp = client.post(f"/api/ops/jobs/{job_id}/retry")
        assert resp.status_code == 400


# ── 8. test_cancel_queued_job ─────────────────────────────────────────────────


class TestCancelQueuedJob:

    def test_cancel_queued_job(self, client, seed_jobs):
        """POST /api/ops/jobs/{queued_id}/cancel returns 200 and changes status."""
        job_id = seed_jobs["queued"]
        resp = client.post(f"/api/ops/jobs/{job_id}/cancel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Job canceled"
        assert data["job_id"] == job_id

        # Verify the status was actually updated in the DB
        detail_resp = client.get(f"/api/ops/jobs/{job_id}")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["status"] == "canceled"


# ── 9. test_cancel_succeeded_job_fails ────────────────────────────────────────


class TestCancelSucceededJobFails:

    def test_cancel_succeeded_job_fails(self, client, seed_jobs):
        """POST /api/ops/jobs/{succeeded_id}/cancel returns 400 (terminal state)."""
        job_id = seed_jobs["succeeded"]
        resp = client.post(f"/api/ops/jobs/{job_id}/cancel")
        assert resp.status_code == 400


# ── 10. test_list_queues ──────────────────────────────────────────────────────


class TestListQueues:

    @patch(
        "backend.src.api.ops.QUEUE_ROUTING",
        {
            "meta_sync_assets": "io",
            "meta_sync_insights": "io",
            "meta_live_monitor": "io",
            "decision_execute": "default",
            "creatives_generate": "llm",
        },
        create=True,
    )
    def test_list_queues(self, client, seed_jobs):
        """GET /api/ops/queues returns 200 with per-queue stats."""
        resp = client.get("/api/ops/queues")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 3  # at least default, io, llm

        # Build a lookup by queue_name
        queues = {q["queue_name"]: q for q in data}

        # io queue: queued(1 meta_sync_assets) + running(1 meta_sync_insights) + failed(1 meta_sync_insights) + dead(1 meta_live_monitor)
        assert "io" in queues
        io_q = queues["io"]
        assert io_q["pending"] >= 1  # at least the queued meta_sync_assets
        assert io_q["running"] >= 1  # at least the running meta_sync_insights
        assert io_q["failed"] >= 1   # at least the failed meta_sync_insights + dead meta_live_monitor

        # All queues should have non-negative counts
        for q in data:
            assert q["pending"] >= 0
            assert q["running"] >= 0
            assert q["failed"] >= 0
