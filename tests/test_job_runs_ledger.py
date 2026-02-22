"""
Job Runs Ledger Tests (BLOQUE 2, Sprint 7)
Tests the JobRun model, default values, status transitions,
idempotency constraints, JSON payload storage, and index queries.
15 tests covering the full JobRunStatus lifecycle.
"""
import os
import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine, String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PG_UUID BEFORE any model imports so SQLite can handle UUID columns.
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.src.database.models import (
    Base,
    JobRun,
    JobRunStatus,
    Organization,
)


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
def org_id(db_session):
    """Create an Organization row required for FK constraints and return its id."""
    _org_id = uuid4()
    org = Organization(
        id=_org_id,
        name="Test Org",
        slug=f"test-org-{_org_id.hex[:8]}",
        created_at=datetime.utcnow(),
    )
    db_session.add(org)
    db_session.commit()
    return _org_id


@pytest.fixture(scope="function")
def second_org_id(db_session):
    """Create a second Organization for multi-org tests."""
    _org_id = uuid4()
    org = Organization(
        id=_org_id,
        name="Second Org",
        slug=f"second-org-{_org_id.hex[:8]}",
        created_at=datetime.utcnow(),
    )
    db_session.add(org)
    db_session.commit()
    return _org_id


# ── Helper ───────────────────────────────────────────────────────────────────


def _make_job_run(org_id, **overrides):
    """Build a JobRun dict with sensible defaults; caller can override any field."""
    defaults = {
        "org_id": org_id,
        "job_type": "meta_sync_assets",
    }
    defaults.update(overrides)
    return JobRun(**defaults)


# ── 1. test_create_job_run_defaults ──────────────────────────────────────────


class TestCreateJobRunDefaults:

    def test_create_job_run_defaults(self, db_session, org_id):
        """Creating a JobRun with only required fields should populate
        status=QUEUED, attempts=0, max_attempts=5, and a generated id."""
        job = _make_job_run(org_id)
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        assert job.id is not None
        assert job.org_id == org_id
        assert job.job_type == "meta_sync_assets"
        assert job.status == JobRunStatus.QUEUED
        assert job.attempts == 0
        assert job.max_attempts == 5
        assert job.scheduled_job_id is None
        assert job.idempotency_key is None
        assert job.started_at is None
        assert job.finished_at is None
        assert job.last_error_code is None
        assert job.last_error_message is None
        assert job.created_at is not None


# ── 2. test_create_job_run_all_fields ────────────────────────────────────────


class TestCreateJobRunAllFields:

    def test_create_job_run_all_fields(self, db_session, org_id):
        """Creating a JobRun with every field populated should persist all values."""
        now = datetime.utcnow()
        job_id = uuid4()
        job = JobRun(
            id=job_id,
            org_id=org_id,
            scheduled_job_id=None,
            job_type="meta_sync_insights",
            status=JobRunStatus.RUNNING,
            payload_json={"account_id": "act_123", "date_range": "last_7d"},
            idempotency_key="sync-insights-2026-02-17",
            attempts=1,
            max_attempts=3,
            scheduled_for=now + timedelta(minutes=10),
            started_at=now,
            finished_at=None,
            last_error_code="TIMEOUT",
            last_error_message="Request timed out after 30s",
            trace_id="trace-abc-123",
            request_id="req-xyz-789",
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        assert str(job.id) == str(job_id)
        assert job.job_type == "meta_sync_insights"
        assert job.status == JobRunStatus.RUNNING
        assert job.payload_json["account_id"] == "act_123"
        assert job.idempotency_key == "sync-insights-2026-02-17"
        assert job.attempts == 1
        assert job.max_attempts == 3
        assert job.scheduled_for is not None
        assert job.started_at == now
        assert job.finished_at is None
        assert job.last_error_code == "TIMEOUT"
        assert job.last_error_message == "Request timed out after 30s"
        assert job.trace_id == "trace-abc-123"
        assert job.request_id == "req-xyz-789"


# ── 3. test_status_queued_to_running ─────────────────────────────────────────


class TestStatusQueuedToRunning:

    def test_status_queued_to_running(self, db_session, org_id):
        """A job transitions from QUEUED to RUNNING when it starts execution."""
        job = _make_job_run(org_id)
        db_session.add(job)
        db_session.commit()

        assert job.status == JobRunStatus.QUEUED

        job.status = JobRunStatus.RUNNING
        job.started_at = datetime.utcnow()
        job.attempts += 1
        db_session.commit()
        db_session.refresh(job)

        assert job.status == JobRunStatus.RUNNING
        assert job.started_at is not None
        assert job.attempts == 1


# ── 4. test_status_running_to_succeeded ──────────────────────────────────────


class TestStatusRunningToSucceeded:

    def test_status_running_to_succeeded(self, db_session, org_id):
        """A job transitions from RUNNING to SUCCEEDED on successful completion."""
        job = _make_job_run(org_id, status=JobRunStatus.RUNNING, attempts=1)
        job.started_at = datetime.utcnow()
        db_session.add(job)
        db_session.commit()

        job.status = JobRunStatus.SUCCEEDED
        job.finished_at = datetime.utcnow()
        db_session.commit()
        db_session.refresh(job)

        assert job.status == JobRunStatus.SUCCEEDED
        assert job.finished_at is not None
        assert job.finished_at >= job.started_at


# ── 5. test_status_running_to_failed ─────────────────────────────────────────


class TestStatusRunningToFailed:

    def test_status_running_to_failed(self, db_session, org_id):
        """A job transitions from RUNNING to FAILED when an error occurs."""
        job = _make_job_run(org_id, status=JobRunStatus.RUNNING, attempts=1)
        job.started_at = datetime.utcnow()
        db_session.add(job)
        db_session.commit()

        job.status = JobRunStatus.FAILED
        job.finished_at = datetime.utcnow()
        job.last_error_code = "API_ERROR"
        job.last_error_message = "Meta API returned 500"
        db_session.commit()
        db_session.refresh(job)

        assert job.status == JobRunStatus.FAILED
        assert job.last_error_code == "API_ERROR"
        assert job.last_error_message == "Meta API returned 500"
        assert job.finished_at is not None


# ── 6. test_status_failed_to_retry_scheduled ─────────────────────────────────


class TestStatusFailedToRetryScheduled:

    def test_status_failed_to_retry_scheduled(self, db_session, org_id):
        """A FAILED job transitions to RETRY_SCHEDULED when a retry is enqueued."""
        job = _make_job_run(
            org_id,
            status=JobRunStatus.FAILED,
            attempts=1,
            max_attempts=5,
        )
        job.started_at = datetime.utcnow() - timedelta(seconds=30)
        job.finished_at = datetime.utcnow()
        job.last_error_code = "TIMEOUT"
        job.last_error_message = "Request timed out"
        db_session.add(job)
        db_session.commit()

        job.status = JobRunStatus.RETRY_SCHEDULED
        job.scheduled_for = datetime.utcnow() + timedelta(minutes=5)
        db_session.commit()
        db_session.refresh(job)

        assert job.status == JobRunStatus.RETRY_SCHEDULED
        assert job.scheduled_for is not None
        assert job.attempts < job.max_attempts


# ── 7. test_status_retry_scheduled_to_running ────────────────────────────────


class TestStatusRetryScheduledToRunning:

    def test_status_retry_scheduled_to_running(self, db_session, org_id):
        """A RETRY_SCHEDULED job transitions back to RUNNING on the next attempt."""
        job = _make_job_run(
            org_id,
            status=JobRunStatus.RETRY_SCHEDULED,
            attempts=2,
            max_attempts=5,
        )
        job.scheduled_for = datetime.utcnow() - timedelta(minutes=1)
        db_session.add(job)
        db_session.commit()

        job.status = JobRunStatus.RUNNING
        job.started_at = datetime.utcnow()
        job.attempts += 1
        db_session.commit()
        db_session.refresh(job)

        assert job.status == JobRunStatus.RUNNING
        assert job.attempts == 3
        assert job.started_at is not None


# ── 8. test_status_running_to_dead ───────────────────────────────────────────


class TestStatusRunningToDead:

    def test_status_running_to_dead(self, db_session, org_id):
        """A RUNNING job transitions to DEAD when max attempts are exhausted."""
        job = _make_job_run(
            org_id,
            status=JobRunStatus.RUNNING,
            attempts=5,
            max_attempts=5,
        )
        job.started_at = datetime.utcnow()
        db_session.add(job)
        db_session.commit()

        job.status = JobRunStatus.DEAD
        job.finished_at = datetime.utcnow()
        job.last_error_code = "MAX_RETRIES"
        job.last_error_message = "Exhausted all 5 attempts"
        db_session.commit()
        db_session.refresh(job)

        assert job.status == JobRunStatus.DEAD
        assert job.attempts == job.max_attempts
        assert job.last_error_code == "MAX_RETRIES"
        assert job.finished_at is not None


# ── 9. test_status_queued_to_canceled ────────────────────────────────────────


class TestStatusQueuedToCanceled:

    def test_status_queued_to_canceled(self, db_session, org_id):
        """A QUEUED job can be canceled before it starts running."""
        job = _make_job_run(org_id)
        db_session.add(job)
        db_session.commit()

        assert job.status == JobRunStatus.QUEUED

        job.status = JobRunStatus.CANCELED
        job.finished_at = datetime.utcnow()
        db_session.commit()
        db_session.refresh(job)

        assert job.status == JobRunStatus.CANCELED
        assert job.finished_at is not None
        assert job.started_at is None  # never started


# ── 10. test_idempotency_key_unique_constraint ───────────────────────────────


class TestIdempotencyKeyUniqueConstraint:

    def test_idempotency_key_unique_constraint(self, db_session, org_id):
        """Inserting two JobRuns with the same (org_id, job_type, idempotency_key)
        raises IntegrityError."""
        job1 = _make_job_run(
            org_id,
            job_type="meta_sync_assets",
            idempotency_key="dedup-key-001",
        )
        db_session.add(job1)
        db_session.commit()

        job2 = _make_job_run(
            org_id,
            job_type="meta_sync_assets",
            idempotency_key="dedup-key-001",
        )
        db_session.add(job2)

        with pytest.raises(IntegrityError):
            db_session.commit()

        db_session.rollback()


# ── 11. test_idempotency_key_different_org_ok ────────────────────────────────


class TestIdempotencyKeyDifferentOrgOk:

    def test_idempotency_key_different_org_ok(self, db_session, org_id, second_org_id):
        """The same (job_type, idempotency_key) in different orgs does NOT
        violate the unique constraint."""
        job1 = _make_job_run(
            org_id,
            job_type="meta_sync_assets",
            idempotency_key="shared-key-001",
        )
        job2 = _make_job_run(
            second_org_id,
            job_type="meta_sync_assets",
            idempotency_key="shared-key-001",
        )
        db_session.add_all([job1, job2])
        db_session.commit()

        assert job1.id != job2.id
        assert str(job1.org_id) != str(job2.org_id)
        assert job1.idempotency_key == job2.idempotency_key


# ── 12. test_idempotency_key_null_allows_duplicates ──────────────────────────


class TestIdempotencyKeyNullAllowsDuplicates:

    def test_idempotency_key_null_allows_duplicates(self, db_session, org_id):
        """Multiple JobRuns with NULL idempotency_key for the same org+type
        should NOT trigger the unique constraint (NULLs are distinct in SQL)."""
        jobs = []
        for _ in range(3):
            job = _make_job_run(
                org_id,
                job_type="meta_sync_assets",
                idempotency_key=None,
            )
            jobs.append(job)

        db_session.add_all(jobs)
        db_session.commit()

        count = (
            db_session.query(JobRun)
            .filter(
                JobRun.org_id == org_id,
                JobRun.job_type == "meta_sync_assets",
                JobRun.idempotency_key.is_(None),
            )
            .count()
        )
        assert count == 3


# ── 13. test_payload_json_storage ────────────────────────────────────────────


class TestPayloadJsonStorage:

    def test_payload_json_storage(self, db_session, org_id):
        """JSON payloads are stored and retrieved faithfully, preserving
        nested structures, arrays, and data types."""
        payload = {
            "account_id": "act_12345",
            "date_range": "last_30d",
            "metrics": ["spend", "impressions", "ctr"],
            "filters": {
                "campaign_status": "ACTIVE",
                "min_spend": 10.5,
            },
            "force_refresh": True,
            "tags": None,
        }

        job = _make_job_run(org_id, payload_json=payload)
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        retrieved = job.payload_json
        assert retrieved["account_id"] == "act_12345"
        assert retrieved["date_range"] == "last_30d"
        assert retrieved["metrics"] == ["spend", "impressions", "ctr"]
        assert retrieved["filters"]["campaign_status"] == "ACTIVE"
        assert retrieved["filters"]["min_spend"] == 10.5
        assert retrieved["force_refresh"] is True
        assert retrieved["tags"] is None


# ── 14. test_attempts_increment ──────────────────────────────────────────────


class TestAttemptsIncrement:

    def test_attempts_increment(self, db_session, org_id):
        """Incrementing attempts through multiple retry cycles correctly
        tracks the count and respects max_attempts."""
        job = _make_job_run(org_id, max_attempts=3)
        db_session.add(job)
        db_session.commit()

        assert job.attempts == 0

        # Simulate three retry cycles
        for expected_attempt in range(1, 4):
            job.attempts += 1
            db_session.commit()
            db_session.refresh(job)
            assert job.attempts == expected_attempt

        # After 3 increments, attempts equals max_attempts
        assert job.attempts == job.max_attempts

        # One more increment goes beyond max (the app logic would prevent this,
        # but the DB model itself does not enforce an upper bound)
        job.attempts += 1
        db_session.commit()
        db_session.refresh(job)
        assert job.attempts == 4
        assert job.attempts > job.max_attempts


# ── 15. test_query_by_status_index ───────────────────────────────────────────


class TestQueryByStatusIndex:

    def test_query_by_status_index(self, db_session, org_id, second_org_id):
        """Querying JobRuns by (org_id, status) returns the correct subset,
        exercising the ix_job_run_org_status index."""
        # Create jobs across two orgs with various statuses
        statuses_org1 = [
            JobRunStatus.QUEUED,
            JobRunStatus.QUEUED,
            JobRunStatus.RUNNING,
            JobRunStatus.SUCCEEDED,
            JobRunStatus.FAILED,
        ]
        statuses_org2 = [
            JobRunStatus.QUEUED,
            JobRunStatus.DEAD,
        ]

        for status in statuses_org1:
            job = _make_job_run(org_id, status=status)
            db_session.add(job)

        for status in statuses_org2:
            job = _make_job_run(second_org_id, status=status)
            db_session.add(job)

        db_session.commit()

        # Query QUEUED jobs for org1 only
        queued_org1 = (
            db_session.query(JobRun)
            .filter(
                JobRun.org_id == org_id,
                JobRun.status == JobRunStatus.QUEUED,
            )
            .all()
        )
        assert len(queued_org1) == 2

        # Query RUNNING jobs for org1
        running_org1 = (
            db_session.query(JobRun)
            .filter(
                JobRun.org_id == org_id,
                JobRun.status == JobRunStatus.RUNNING,
            )
            .all()
        )
        assert len(running_org1) == 1

        # Query QUEUED jobs for org2
        queued_org2 = (
            db_session.query(JobRun)
            .filter(
                JobRun.org_id == second_org_id,
                JobRun.status == JobRunStatus.QUEUED,
            )
            .all()
        )
        assert len(queued_org2) == 1

        # Query DEAD jobs for org2
        dead_org2 = (
            db_session.query(JobRun)
            .filter(
                JobRun.org_id == second_org_id,
                JobRun.status == JobRunStatus.DEAD,
            )
            .all()
        )
        assert len(dead_org2) == 1

        # Cross-org isolation: org1 should have zero DEAD jobs
        dead_org1 = (
            db_session.query(JobRun)
            .filter(
                JobRun.org_id == org_id,
                JobRun.status == JobRunStatus.DEAD,
            )
            .all()
        )
        assert len(dead_org1) == 0

        # Total jobs across both orgs
        total = db_session.query(JobRun).count()
        assert total == 7
