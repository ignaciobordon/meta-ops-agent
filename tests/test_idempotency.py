"""
Sprint 7 -- BLOQUE 3: Idempotency Guard Tests.
Tests get_or_create_job_run (DB-level dedup) and Redis-based execution locks.
"""
import os
import pytest
from uuid import uuid4
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PG_UUID BEFORE any model imports so SQLite can handle UUID columns.
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.src.database.models import Base, Organization, JobRun, JobRunStatus
from backend.src.jobs.idempotency import (
    get_or_create_job_run,
    acquire_execution_lock,
    release_execution_lock,
)
from backend.src.infra.fake_redis import FakeRedis


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


def _create_org(db_session) -> "uuid4":
    """Create a minimal Organization and return its id."""
    org_id = uuid4()
    org = Organization(
        id=org_id,
        name="Test Org",
        slug=f"test-org-{org_id.hex[:8]}",
        created_at=datetime.utcnow(),
    )
    db_session.add(org)
    db_session.commit()
    return org_id


# ---------------------------------------------------------------------------
# Test 1: get_or_create_job_run -- new key creates a new JobRun
# ---------------------------------------------------------------------------


class TestGetOrCreateNew:

    def test_get_or_create_new(self, db_session):
        """First call with a given idempotency key creates a new JobRun, is_new=True."""
        org_id = _create_org(db_session)
        key = f"idem-{uuid4().hex[:8]}"

        job_run, is_new = get_or_create_job_run(
            db=db_session,
            idempotency_key=key,
            org_id=org_id,
            job_type="sync_assets",
            payload={"account_id": "act_123"},
        )
        db_session.commit()

        assert is_new is True
        assert job_run is not None
        assert job_run.idempotency_key == key
        assert job_run.org_id == org_id
        assert job_run.job_type == "sync_assets"
        assert job_run.status == JobRunStatus.QUEUED
        assert job_run.payload_json == {"account_id": "act_123"}


# ---------------------------------------------------------------------------
# Test 2: get_or_create_job_run -- same key returns existing, is_new=False
# ---------------------------------------------------------------------------


class TestGetOrCreateExisting:

    def test_get_or_create_existing(self, db_session):
        """Second call with the same idempotency key returns the existing
        JobRun and is_new=False (no duplicate created)."""
        org_id = _create_org(db_session)
        key = f"idem-{uuid4().hex[:8]}"

        job_run_1, is_new_1 = get_or_create_job_run(
            db=db_session,
            idempotency_key=key,
            org_id=org_id,
            job_type="sync_assets",
            payload={"run": 1},
        )
        db_session.commit()

        job_run_2, is_new_2 = get_or_create_job_run(
            db=db_session,
            idempotency_key=key,
            org_id=org_id,
            job_type="sync_assets",
            payload={"run": 2},
        )

        assert is_new_1 is True
        assert is_new_2 is False
        assert job_run_2.id == job_run_1.id

        # Only one row in DB for this key
        count = (
            db_session.query(JobRun)
            .filter(
                JobRun.org_id == org_id,
                JobRun.job_type == "sync_assets",
                JobRun.idempotency_key == key,
            )
            .count()
        )
        assert count == 1


# ---------------------------------------------------------------------------
# Test 3: get_or_create_job_run -- terminal status allows new creation
# ---------------------------------------------------------------------------


class TestGetOrCreateTerminalAllowsNew:

    def test_get_or_create_terminal_allows_new(self, db_session):
        """If the existing JobRun has a terminal status (SUCCEEDED), a new
        call with the same key should create a new JobRun."""
        org_id = _create_org(db_session)
        key = f"idem-{uuid4().hex[:8]}"

        job_run_1, is_new_1 = get_or_create_job_run(
            db=db_session,
            idempotency_key=key,
            org_id=org_id,
            job_type="sync_insights",
            payload={},
        )
        db_session.commit()
        assert is_new_1 is True

        # Mark the existing run as SUCCEEDED (terminal)
        job_run_1.status = JobRunStatus.SUCCEEDED
        job_run_1.finished_at = datetime.utcnow()
        db_session.commit()

        job_run_2, is_new_2 = get_or_create_job_run(
            db=db_session,
            idempotency_key=key,
            org_id=org_id,
            job_type="sync_insights",
            payload={},
        )

        assert is_new_2 is True
        assert job_run_2.id != job_run_1.id


# ---------------------------------------------------------------------------
# Test 4: get_or_create_job_run -- different key creates new
# ---------------------------------------------------------------------------


class TestGetOrCreateDifferentKeyCreatesNew:

    def test_get_or_create_different_key_creates_new(self, db_session):
        """Two calls with different idempotency keys both create new JobRuns."""
        org_id = _create_org(db_session)
        key_a = f"idem-a-{uuid4().hex[:8]}"
        key_b = f"idem-b-{uuid4().hex[:8]}"

        job_a, is_new_a = get_or_create_job_run(
            db=db_session,
            idempotency_key=key_a,
            org_id=org_id,
            job_type="sync_assets",
            payload={"key": "a"},
        )
        db_session.commit()

        job_b, is_new_b = get_or_create_job_run(
            db=db_session,
            idempotency_key=key_b,
            org_id=org_id,
            job_type="sync_assets",
            payload={"key": "b"},
        )
        db_session.commit()

        assert is_new_a is True
        assert is_new_b is True
        assert job_a.id != job_b.id
        assert job_a.idempotency_key == key_a
        assert job_b.idempotency_key == key_b


# ---------------------------------------------------------------------------
# Test 5: acquire_execution_lock -- success with FakeRedis
# ---------------------------------------------------------------------------


class TestAcquireLockSuccess:

    def test_acquire_lock_success(self):
        """With FakeRedis available, acquire_execution_lock returns True on
        first call for a given job_run_id."""
        fake_redis = FakeRedis()
        job_run_id = str(uuid4())

        with patch(
            "backend.src.infra.redis_client.get_redis",
            return_value=fake_redis,
        ):
            acquired = acquire_execution_lock(job_run_id, ttl=60)

        assert acquired is True
        assert fake_redis.exists(f"job_lock:{job_run_id}")


# ---------------------------------------------------------------------------
# Test 6: acquire_execution_lock -- already held returns False
# ---------------------------------------------------------------------------


class TestAcquireLockAlreadyHeld:

    def test_acquire_lock_already_held(self):
        """If the lock is already held, a second acquire_execution_lock returns
        False."""
        fake_redis = FakeRedis()
        job_run_id = str(uuid4())

        with patch(
            "backend.src.infra.redis_client.get_redis",
            return_value=fake_redis,
        ):
            first = acquire_execution_lock(job_run_id, ttl=60)
            second = acquire_execution_lock(job_run_id, ttl=60)

        assert first is True
        assert second is False


# ---------------------------------------------------------------------------
# Test 7: release_execution_lock -- release then re-acquire succeeds
# ---------------------------------------------------------------------------


class TestReleaseLock:

    def test_release_lock(self):
        """After releasing the lock, a subsequent acquire returns True."""
        fake_redis = FakeRedis()
        job_run_id = str(uuid4())

        with patch(
            "backend.src.infra.redis_client.get_redis",
            return_value=fake_redis,
        ):
            acquired_1 = acquire_execution_lock(job_run_id, ttl=60)
            assert acquired_1 is True

            release_execution_lock(job_run_id)
            assert not fake_redis.exists(f"job_lock:{job_run_id}")

            acquired_2 = acquire_execution_lock(job_run_id, ttl=60)
            assert acquired_2 is True


# ---------------------------------------------------------------------------
# Test 8: acquire_execution_lock -- no Redis returns True (degraded mode)
# ---------------------------------------------------------------------------


class TestAcquireLockNoRedis:

    def test_acquire_lock_no_redis(self):
        """When get_redis returns None, acquire_execution_lock returns True
        (degraded mode -- allow execution without lock)."""
        job_run_id = str(uuid4())

        with patch(
            "backend.src.infra.redis_client.get_redis",
            return_value=None,
        ):
            acquired = acquire_execution_lock(job_run_id, ttl=60)

        assert acquired is True
