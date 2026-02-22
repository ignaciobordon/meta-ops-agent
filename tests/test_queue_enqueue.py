"""
Sprint 7 -- BLOQUE 1: Queue & Task Runner Tests.
Tests for enqueue(), QUEUE_ROUTING, and run_job() lifecycle.
"""
import os
import sys
import pytest
from datetime import datetime, timedelta
from types import ModuleType
from unittest.mock import patch, MagicMock
from uuid import uuid4, UUID

from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PG_UUID BEFORE any model imports so SQLite can handle UUID columns.
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

# Stub the celery_app module before importing queue/task_runner, because
# kombu (a Celery dependency) is not installed in the test environment.
# The real module has a try/except that sets celery_app = None on ImportError,
# so we replicate that here.
_celery_stub = ModuleType("backend.src.infra.celery_app")
_celery_stub.celery_app = None
sys.modules.setdefault("backend.src.infra.celery_app", _celery_stub)

from backend.src.database.models import (
    Base,
    JobRun,
    JobRunStatus,
    Organization,
)
from backend.src.jobs.queue import enqueue, QUEUE_ROUTING

# Get a reference to the module as it exists in sys.modules for patching.
_celery_mod = sys.modules["backend.src.infra.celery_app"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(scope="function")
def org_id(db_session):
    """Create an Organization row and return its id."""
    oid = uuid4()
    org = Organization(
        id=oid,
        name="Test Org",
        slug=f"test-org-{oid.hex[:8]}",
        created_at=datetime.utcnow(),
    )
    db_session.add(org)
    db_session.commit()
    return oid


# ---------------------------------------------------------------------------
# Test 1: QUEUE_ROUTING -- meta_sync_assets routes to "io"
# ---------------------------------------------------------------------------


class TestQueueRoutingMetaSync:

    def test_meta_sync_assets_routes_to_io(self):
        """meta_sync_assets should route to the 'io' queue."""
        assert QUEUE_ROUTING["meta_sync_assets"] == "io"


# ---------------------------------------------------------------------------
# Test 2: QUEUE_ROUTING -- decision_execute routes to "default"
# ---------------------------------------------------------------------------


class TestQueueRoutingDecision:

    def test_decision_execute_routes_to_default(self):
        """decision_execute should route to the 'default' queue."""
        assert QUEUE_ROUTING["decision_execute"] == "default"


# ---------------------------------------------------------------------------
# Test 3: QUEUE_ROUTING -- creatives_generate routes to "llm"
# ---------------------------------------------------------------------------


class TestQueueRoutingLlm:

    def test_creatives_generate_routes_to_llm(self):
        """creatives_generate should route to the 'llm' queue."""
        assert QUEUE_ROUTING["creatives_generate"] == "llm"


# ---------------------------------------------------------------------------
# Test 4: enqueue creates a JobRun row with correct fields
# ---------------------------------------------------------------------------


class TestEnqueueCreatesJobRun:

    def test_creates_job_run_in_db(self, db_session, org_id):
        """enqueue() should create a JobRun row with status=QUEUED and correct
        job_type, org_id, and payload."""
        payload = {"ad_account_id": str(uuid4())}

        with patch.object(_celery_mod, "celery_app", None):
            job_run_id = enqueue(
                task_name="meta_sync_assets",
                payload=payload,
                org_id=org_id,
                db=db_session,
            )
        db_session.commit()

        job_run = db_session.query(JobRun).filter(
            JobRun.id == UUID(job_run_id)
        ).first()

        assert job_run is not None
        assert job_run.status == JobRunStatus.QUEUED
        assert job_run.job_type == "meta_sync_assets"
        assert job_run.org_id == org_id
        assert job_run.payload_json == payload
        assert job_run.max_attempts > 0


# ---------------------------------------------------------------------------
# Test 5: enqueue dispatches to Celery with correct args
# ---------------------------------------------------------------------------


class TestEnqueueDispatchesToCelery:

    def test_send_task_called_with_correct_args(self, db_session, org_id):
        """enqueue() should call celery_app.send_task with the correct task name,
        args, and queue."""
        mock_celery = MagicMock()

        with patch.object(_celery_mod, "celery_app", mock_celery):
            job_run_id = enqueue(
                task_name="meta_sync_assets",
                payload={"ad_account_id": str(uuid4())},
                org_id=org_id,
                db=db_session,
            )
            db_session.commit()

        mock_celery.send_task.assert_called_once()
        call_kwargs = mock_celery.send_task.call_args
        assert call_kwargs[0][0] == "backend.src.jobs.tasks.meta_sync_assets"
        assert call_kwargs[1]["args"] == [job_run_id]
        assert call_kwargs[1]["queue"] == "io"


# ---------------------------------------------------------------------------
# Test 6: enqueue with eta passes eta to send_task
# ---------------------------------------------------------------------------


class TestEnqueueWithEta:

    def test_eta_passed_to_celery(self, db_session, org_id):
        """When eta is provided, enqueue() should forward it to
        celery_app.send_task."""
        mock_celery = MagicMock()
        future_time = datetime.utcnow() + timedelta(minutes=30)

        with patch.object(_celery_mod, "celery_app", mock_celery):
            enqueue(
                task_name="decision_execute",
                payload={"decision_id": str(uuid4())},
                org_id=org_id,
                eta=future_time,
                db=db_session,
            )
            db_session.commit()

        call_kwargs = mock_celery.send_task.call_args
        assert call_kwargs[1]["eta"] == future_time
        assert call_kwargs[1]["queue"] == "default"


# ---------------------------------------------------------------------------
# Test 7: run_job success -- QUEUED -> RUNNING -> SUCCEEDED
# ---------------------------------------------------------------------------


class TestRunJobSuccess:

    def test_transitions_to_succeeded(self, db_session, org_id):
        """run_job should transition a QUEUED JobRun through RUNNING to
        SUCCEEDED when _dispatch completes without error."""
        job_run_id = uuid4()
        job_run = JobRun(
            id=job_run_id,
            org_id=org_id,
            job_type="meta_sync_assets",
            status=JobRunStatus.QUEUED,
            payload_json={"ad_account_id": str(uuid4())},
            max_attempts=5,
            scheduled_for=datetime.utcnow(),
            trace_id="test-trace-123",
            created_at=datetime.utcnow(),
        )
        db_session.add(job_run)
        db_session.commit()

        with patch("backend.src.database.session.SessionLocal", return_value=db_session), \
             patch("backend.src.jobs.task_runner._dispatch") as mock_dispatch, \
             patch("backend.src.jobs.idempotency.acquire_execution_lock", return_value=True), \
             patch("backend.src.jobs.idempotency.release_execution_lock"):

            from backend.src.jobs.task_runner import run_job
            run_job(str(job_run_id), "meta_sync_assets")

        db_session.expire_all()
        updated = db_session.query(JobRun).filter(JobRun.id == job_run_id).first()

        assert updated.status == JobRunStatus.SUCCEEDED
        assert updated.started_at is not None
        assert updated.finished_at is not None
        assert updated.attempts == 1
        mock_dispatch.assert_called_once()


# ---------------------------------------------------------------------------
# Test 8: run_job failure retryable -- dispatch raises, error classified as
#          retryable -> RETRY_SCHEDULED
# ---------------------------------------------------------------------------


class TestRunJobFailureRetryable:

    def test_transitions_to_retry_scheduled(self, db_session, org_id):
        """When _dispatch raises a transient error and attempts < max_attempts,
        the JobRun should transition to RETRY_SCHEDULED."""
        job_run_id = uuid4()
        job_run = JobRun(
            id=job_run_id,
            org_id=org_id,
            job_type="meta_sync_assets",
            status=JobRunStatus.QUEUED,
            payload_json={"ad_account_id": str(uuid4())},
            max_attempts=5,
            attempts=0,
            scheduled_for=datetime.utcnow(),
            trace_id="test-trace-retry",
            created_at=datetime.utcnow(),
        )
        db_session.add(job_run)
        db_session.commit()

        def _dispatch_raises(*args, **kwargs):
            raise ConnectionError("timeout connecting to Meta API")

        with patch("backend.src.database.session.SessionLocal", return_value=db_session), \
             patch("backend.src.jobs.task_runner._dispatch", side_effect=_dispatch_raises), \
             patch("backend.src.jobs.idempotency.acquire_execution_lock", return_value=True), \
             patch("backend.src.jobs.idempotency.release_execution_lock"), \
             patch("backend.src.jobs.queue.enqueue") as mock_re_enqueue, \
             patch.object(_celery_mod, "celery_app", None):

            from backend.src.jobs.task_runner import run_job
            run_job(str(job_run_id), "meta_sync_assets")

        db_session.expire_all()
        updated = db_session.query(JobRun).filter(JobRun.id == job_run_id).first()

        assert updated.status == JobRunStatus.RETRY_SCHEDULED
        assert updated.attempts == 1
        assert updated.last_error_code == "transient"
        assert "timeout" in updated.last_error_message.lower()
        # Verify re-enqueue was called for retry
        mock_re_enqueue.assert_called_once()


# ---------------------------------------------------------------------------
# Test 9: run_job failure dead -- attempts >= max_attempts -> DEAD
# ---------------------------------------------------------------------------


class TestRunJobFailureDead:

    def test_transitions_to_dead_at_max_attempts(self, db_session, org_id):
        """When _dispatch raises and attempts >= max_attempts, the JobRun
        should transition to DEAD (exhausted all retries)."""
        job_run_id = uuid4()
        job_run = JobRun(
            id=job_run_id,
            org_id=org_id,
            job_type="meta_sync_assets",
            status=JobRunStatus.QUEUED,
            payload_json={"ad_account_id": str(uuid4())},
            max_attempts=2,
            attempts=1,  # Will become 2 after run_job increments; 2 >= 2 -> DEAD
            scheduled_for=datetime.utcnow(),
            trace_id="test-trace-dead",
            created_at=datetime.utcnow(),
        )
        db_session.add(job_run)
        db_session.commit()

        def _dispatch_raises(*args, **kwargs):
            raise ConnectionError("timeout connecting to Meta API")

        with patch("backend.src.database.session.SessionLocal", return_value=db_session), \
             patch("backend.src.jobs.task_runner._dispatch", side_effect=_dispatch_raises), \
             patch("backend.src.jobs.idempotency.acquire_execution_lock", return_value=True), \
             patch("backend.src.jobs.idempotency.release_execution_lock"), \
             patch.object(_celery_mod, "celery_app", None):

            from backend.src.jobs.task_runner import run_job
            run_job(str(job_run_id), "meta_sync_assets")

        db_session.expire_all()
        updated = db_session.query(JobRun).filter(JobRun.id == job_run_id).first()

        assert updated.status == JobRunStatus.DEAD
        assert updated.attempts == 2
        assert updated.last_error_code is not None
        assert updated.finished_at is not None


# ---------------------------------------------------------------------------
# Test 10: run_job skips non-QUEUED jobs (e.g. SUCCEEDED)
# ---------------------------------------------------------------------------


class TestRunJobSkipNonQueued:

    def test_skips_when_status_is_succeeded(self, db_session, org_id):
        """run_job should skip execution when the JobRun status is already
        SUCCEEDED (not in QUEUED or RETRY_SCHEDULED)."""
        job_run_id = uuid4()
        job_run = JobRun(
            id=job_run_id,
            org_id=org_id,
            job_type="meta_sync_assets",
            status=JobRunStatus.SUCCEEDED,
            payload_json={"ad_account_id": str(uuid4())},
            max_attempts=5,
            attempts=1,
            scheduled_for=datetime.utcnow(),
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            trace_id="test-trace-skip",
            created_at=datetime.utcnow(),
        )
        db_session.add(job_run)
        db_session.commit()

        with patch("backend.src.database.session.SessionLocal", return_value=db_session), \
             patch("backend.src.jobs.task_runner._dispatch") as mock_dispatch, \
             patch("backend.src.jobs.idempotency.acquire_execution_lock", return_value=True), \
             patch("backend.src.jobs.idempotency.release_execution_lock"):

            from backend.src.jobs.task_runner import run_job
            run_job(str(job_run_id), "meta_sync_assets")

        # _dispatch should never be called when status is SUCCEEDED
        mock_dispatch.assert_not_called()

        # The JobRun should remain unchanged
        db_session.expire_all()
        updated = db_session.query(JobRun).filter(JobRun.id == job_run_id).first()
        assert updated.status == JobRunStatus.SUCCEEDED
        assert updated.attempts == 1
