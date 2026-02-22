"""
Sprint 6 -- MetaJobScheduler unit tests.
Tests enqueue, idempotency, reschedule (success/failure/backoff/max_attempts),
plan-based intervals, and process_meta_jobs.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from uuid import uuid4

from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PG_UUID BEFORE any model imports so SQLite can handle UUID columns.
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

from backend.src.database.models import (
    Base,
    MetaAdAccount,
    MetaConnection,
    Organization,
    PlanEnum,
    ScheduledJob,
    Subscription,
    SubscriptionStatusEnum,
    SyncJobType,
)
from backend.src.services.meta_job_scheduler import (
    JOB_FREQUENCIES,
    MetaJobScheduler,
)


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


def _seed(db_session, plan: PlanEnum = PlanEnum.PRO):
    """Create Organization, MetaConnection, MetaAdAccount, and Subscription.

    Returns a dict with ``org_id`` and ``ad_account_id`` (both :class:`uuid.UUID`).
    """
    org_id = uuid4()
    org = Organization(
        id=org_id,
        name="Test Org",
        slug=f"test-org-{org_id.hex[:8]}",
        created_at=datetime.utcnow(),
    )
    db_session.add(org)

    conn_id = uuid4()
    conn = MetaConnection(
        id=conn_id,
        org_id=org_id,
        access_token_encrypted="enc_test_token",
        status="active",
        connected_at=datetime.utcnow(),
    )
    db_session.add(conn)

    ad_account_id = uuid4()
    ad_account = MetaAdAccount(
        id=ad_account_id,
        org_id=org_id,
        meta_account_id=f"act_{org_id.hex[:8]}",
        name="Test Ad Account",
        currency="USD",
        created_at=datetime.utcnow(),
    )
    db_session.add(ad_account)

    sub = Subscription(
        id=uuid4(),
        org_id=org_id,
        plan=plan,
        status=(
            SubscriptionStatusEnum.ACTIVE
            if plan != PlanEnum.TRIAL
            else SubscriptionStatusEnum.TRIALING
        ),
        created_at=datetime.utcnow(),
    )
    db_session.add(sub)

    db_session.commit()
    return {"org_id": org_id, "ad_account_id": ad_account_id}


# ---------------------------------------------------------------------------
# Test 1: enqueue_if_missing creates 4 jobs (one per SyncJobType)
# ---------------------------------------------------------------------------


class TestEnqueueIfMissingCreatesJobs:

    def test_creates_four_jobs(self, db_session):
        """enqueue_if_missing should create exactly one ScheduledJob per SyncJobType."""
        data = _seed(db_session)
        scheduler = MetaJobScheduler(db_session)

        created = scheduler.enqueue_if_missing(data["org_id"], data["ad_account_id"])
        db_session.commit()

        assert len(created) == 4

        created_types = sorted([j.job_type for j in created])
        expected_types = sorted([jt.value for jt in SyncJobType])
        assert created_types == expected_types

        # All jobs reference the same ad account
        for job in created:
            assert job.reference_id == data["ad_account_id"]
            assert job.org_id == data["org_id"]
            assert job.completed_at is None


# ---------------------------------------------------------------------------
# Test 2: enqueue_if_missing is idempotent (second call creates 0 new jobs)
# ---------------------------------------------------------------------------


class TestEnqueueIdempotent:

    def test_second_call_creates_zero_jobs(self, db_session):
        """Calling enqueue_if_missing twice for the same org/ad_account creates
        no additional jobs on the second invocation."""
        data = _seed(db_session)
        scheduler = MetaJobScheduler(db_session)

        first_batch = scheduler.enqueue_if_missing(data["org_id"], data["ad_account_id"])
        db_session.commit()
        assert len(first_batch) == 4

        second_batch = scheduler.enqueue_if_missing(data["org_id"], data["ad_account_id"])
        db_session.commit()
        assert len(second_batch) == 0

        total = (
            db_session.query(ScheduledJob)
            .filter(
                ScheduledJob.org_id == data["org_id"],
                ScheduledJob.reference_id == data["ad_account_id"],
            )
            .count()
        )
        assert total == 4


# ---------------------------------------------------------------------------
# Test 3: reschedule_job on success creates next job with correct interval
# ---------------------------------------------------------------------------


class TestRescheduleOnSuccess:

    def test_creates_next_job_with_correct_interval(self, db_session):
        """On success, reschedule_job marks the current job completed and creates a
        new ScheduledJob with scheduled_for = now + interval."""
        data = _seed(db_session, plan=PlanEnum.PRO)
        scheduler = MetaJobScheduler(db_session)

        job_type = SyncJobType.META_SYNC_ASSETS.value
        now = datetime.utcnow()

        job = ScheduledJob(
            id=uuid4(),
            org_id=data["org_id"],
            job_type=job_type,
            reference_id=data["ad_account_id"],
            scheduled_for=now - timedelta(minutes=1),
        )
        db_session.add(job)
        db_session.commit()

        scheduler.reschedule_job(job, success=True)
        db_session.commit()

        # Original job is completed
        assert job.completed_at is not None

        # A new job should have been created
        next_job = (
            db_session.query(ScheduledJob)
            .filter(
                ScheduledJob.org_id == data["org_id"],
                ScheduledJob.job_type == job_type,
                ScheduledJob.completed_at.is_(None),
            )
            .first()
        )
        assert next_job is not None
        assert next_job.id != job.id

        # Interval for PRO META_SYNC_ASSETS is 5 minutes
        pro_interval, _ = JOB_FREQUENCIES[job_type]
        expected_scheduled_for = job.completed_at + timedelta(minutes=pro_interval)
        diff = abs((next_job.scheduled_for - expected_scheduled_for).total_seconds())
        assert diff < 2  # within 2 seconds tolerance

        # Attempts reset to 0 on success
        assert next_job.attempts == 0


# ---------------------------------------------------------------------------
# Test 4: reschedule_job on failure increments attempts
# ---------------------------------------------------------------------------


class TestRescheduleOnFailureIncrementsAttempts:

    def test_failure_increments_attempts(self, db_session):
        """On failure, reschedule_job marks completed, increments attempts on the
        current job, and the new job carries the updated attempt count."""
        data = _seed(db_session)
        scheduler = MetaJobScheduler(db_session)

        job = ScheduledJob(
            id=uuid4(),
            org_id=data["org_id"],
            job_type=SyncJobType.META_SYNC_INSIGHTS.value,
            reference_id=data["ad_account_id"],
            scheduled_for=datetime.utcnow() - timedelta(minutes=1),
            attempts=0,
            max_attempts=5,
        )
        db_session.add(job)
        db_session.commit()

        scheduler.reschedule_job(job, success=False, error_msg="API timeout")
        db_session.commit()

        # Current job should have attempts=1 and error_message set
        assert job.attempts == 1
        assert job.error_message == "API timeout"
        assert job.completed_at is not None

        # New job carries the attempt count forward
        next_job = (
            db_session.query(ScheduledJob)
            .filter(
                ScheduledJob.org_id == data["org_id"],
                ScheduledJob.job_type == SyncJobType.META_SYNC_INSIGHTS.value,
                ScheduledJob.completed_at.is_(None),
            )
            .first()
        )
        assert next_job is not None
        assert next_job.attempts == 1


# ---------------------------------------------------------------------------
# Test 5: reschedule_job stops after max_attempts (no new job created)
# ---------------------------------------------------------------------------


class TestRescheduleStopsAtMaxAttempts:

    def test_no_new_job_after_max_attempts(self, db_session):
        """When attempts reach max_attempts, reschedule_job should not create a
        new ScheduledJob (requires manual intervention)."""
        data = _seed(db_session)
        scheduler = MetaJobScheduler(db_session)

        job = ScheduledJob(
            id=uuid4(),
            org_id=data["org_id"],
            job_type=SyncJobType.META_LIVE_MONITOR.value,
            reference_id=data["ad_account_id"],
            scheduled_for=datetime.utcnow() - timedelta(minutes=1),
            attempts=4,  # one below max
            max_attempts=5,
        )
        db_session.add(job)
        db_session.commit()

        scheduler.reschedule_job(job, success=False, error_msg="Persistent failure")
        db_session.commit()

        # Attempts should be bumped to 5 (== max_attempts)
        assert job.attempts == 5

        # No new incomplete job should exist
        pending = (
            db_session.query(ScheduledJob)
            .filter(
                ScheduledJob.org_id == data["org_id"],
                ScheduledJob.job_type == SyncJobType.META_LIVE_MONITOR.value,
                ScheduledJob.completed_at.is_(None),
            )
            .count()
        )
        assert pending == 0


# ---------------------------------------------------------------------------
# Test 6: reschedule_job uses exponential backoff on failure
# ---------------------------------------------------------------------------


class TestExponentialBackoff:

    def test_backoff_doubles_interval(self, db_session):
        """On failure, the next job's scheduled_for should incorporate exponential
        backoff: base_interval * 2^attempts, capped at 360 minutes."""
        data = _seed(db_session, plan=PlanEnum.PRO)
        scheduler = MetaJobScheduler(db_session)

        job_type = SyncJobType.META_SYNC_ASSETS.value
        pro_interval, _ = JOB_FREQUENCIES[job_type]  # 5 minutes

        # Simulate first failure (attempts will become 1)
        job = ScheduledJob(
            id=uuid4(),
            org_id=data["org_id"],
            job_type=job_type,
            reference_id=data["ad_account_id"],
            scheduled_for=datetime.utcnow() - timedelta(minutes=1),
            attempts=0,
            max_attempts=5,
        )
        db_session.add(job)
        db_session.commit()

        scheduler.reschedule_job(job, success=False, error_msg="transient error")
        db_session.commit()

        next_job = (
            db_session.query(ScheduledJob)
            .filter(
                ScheduledJob.org_id == data["org_id"],
                ScheduledJob.job_type == job_type,
                ScheduledJob.completed_at.is_(None),
            )
            .first()
        )
        assert next_job is not None

        # After first failure: attempts on new job == 1, backoff_factor = 2^1 = 2
        # Expected interval = min(5 * 2, 360) = 10 minutes
        expected_interval = min(pro_interval * (2 ** 1), 360)
        actual_delta = (next_job.scheduled_for - job.completed_at).total_seconds() / 60
        assert abs(actual_delta - expected_interval) < 0.1

        # --- Second failure ---
        job2 = next_job
        job2.scheduled_for = datetime.utcnow() - timedelta(minutes=1)
        db_session.commit()

        scheduler.reschedule_job(job2, success=False, error_msg="still failing")
        db_session.commit()

        next_job2 = (
            db_session.query(ScheduledJob)
            .filter(
                ScheduledJob.org_id == data["org_id"],
                ScheduledJob.job_type == job_type,
                ScheduledJob.completed_at.is_(None),
            )
            .first()
        )
        assert next_job2 is not None

        # After second failure: attempts on new job == 2, backoff_factor = 2^2 = 4
        # Expected interval = min(5 * 4, 360) = 20 minutes
        expected_interval_2 = min(pro_interval * (2 ** 2), 360)
        actual_delta_2 = (next_job2.scheduled_for - job2.completed_at).total_seconds() / 60
        assert abs(actual_delta_2 - expected_interval_2) < 0.1


# ---------------------------------------------------------------------------
# Test 7: TRIAL plan gets longer intervals than PRO
# ---------------------------------------------------------------------------


class TestTrialPlanLongerIntervals:

    def test_trial_intervals_exceed_pro(self, db_session):
        """For every SyncJobType, the TRIAL plan interval must be strictly
        greater than the PRO plan interval."""
        data_pro = _seed(db_session, plan=PlanEnum.PRO)
        data_trial = _seed(db_session, plan=PlanEnum.TRIAL)

        scheduler_pro = MetaJobScheduler(db_session)
        scheduler_trial = MetaJobScheduler(db_session)

        for jt in SyncJobType:
            pro_interval = scheduler_pro._get_interval_minutes(
                data_pro["org_id"], jt.value
            )
            trial_interval = scheduler_trial._get_interval_minutes(
                data_trial["org_id"], jt.value
            )
            assert trial_interval > pro_interval, (
                f"{jt.value}: TRIAL interval ({trial_interval}) should be "
                f"greater than PRO interval ({pro_interval})"
            )

    def test_enqueue_uses_plan_specific_next_run_at(self, db_session):
        """Jobs enqueued for a TRIAL org should have a longer next_run_at gap
        than jobs enqueued for a PRO org."""
        data_pro = _seed(db_session, plan=PlanEnum.PRO)
        data_trial = _seed(db_session, plan=PlanEnum.TRIAL)

        scheduler = MetaJobScheduler(db_session)

        pro_jobs = scheduler.enqueue_if_missing(
            data_pro["org_id"], data_pro["ad_account_id"]
        )
        trial_jobs = scheduler.enqueue_if_missing(
            data_trial["org_id"], data_trial["ad_account_id"]
        )
        db_session.commit()

        # Compare next_run_at gaps for the same job type
        pro_map = {j.job_type: j for j in pro_jobs}
        trial_map = {j.job_type: j for j in trial_jobs}

        for jt in SyncJobType:
            pro_gap = (
                pro_map[jt.value].next_run_at - pro_map[jt.value].scheduled_for
            ).total_seconds()
            trial_gap = (
                trial_map[jt.value].next_run_at - trial_map[jt.value].scheduled_for
            ).total_seconds()
            assert trial_gap > pro_gap, (
                f"{jt.value}: TRIAL next_run_at gap ({trial_gap}s) should exceed "
                f"PRO gap ({pro_gap}s)"
            )


# ---------------------------------------------------------------------------
# Test 8: process_meta_jobs picks up due jobs and executes them
# ---------------------------------------------------------------------------


class TestProcessMetaJobs:

    def test_picks_up_due_jobs_and_executes(self, db_session):
        """process_meta_jobs should find ScheduledJobs whose scheduled_for is
        in the past, call _execute_job for each, and return results."""
        data = _seed(db_session, plan=PlanEnum.PRO)
        scheduler = MetaJobScheduler(db_session)

        now = datetime.utcnow()

        # Create two due jobs and one future job
        due_job_1 = ScheduledJob(
            id=uuid4(),
            org_id=data["org_id"],
            job_type=SyncJobType.META_SYNC_ASSETS.value,
            reference_id=data["ad_account_id"],
            scheduled_for=now - timedelta(minutes=5),
        )
        due_job_2 = ScheduledJob(
            id=uuid4(),
            org_id=data["org_id"],
            job_type=SyncJobType.META_SYNC_INSIGHTS.value,
            reference_id=data["ad_account_id"],
            scheduled_for=now - timedelta(minutes=2),
        )
        future_job = ScheduledJob(
            id=uuid4(),
            org_id=data["org_id"],
            job_type=SyncJobType.META_LIVE_MONITOR.value,
            reference_id=data["ad_account_id"],
            scheduled_for=now + timedelta(hours=1),
        )
        db_session.add_all([due_job_1, due_job_2, future_job])
        db_session.commit()

        # Mock _execute_job so we do not hit real sync services
        mock_result = {
            "status": "ok",
            "synced": 10,
        }
        with patch.object(
            scheduler,
            "_execute_job",
            return_value={
                "job_id": "mocked",
                "job_type": "mocked",
                "status": "completed",
                "result": mock_result,
            },
        ) as mock_exec:
            results = scheduler.process_meta_jobs(limit=20)

        # Only the two due jobs should have been processed
        assert len(results) == 2
        assert mock_exec.call_count == 2

        # Verify call args contain only the due jobs (by id)
        called_job_ids = {call.args[0].id for call in mock_exec.call_args_list}
        assert called_job_ids == {due_job_1.id, due_job_2.id}

        # The future job must remain untouched
        db_session.expire_all()
        untouched = db_session.query(ScheduledJob).filter(
            ScheduledJob.id == future_job.id,
        ).first()
        assert untouched.completed_at is None

    def test_process_respects_limit(self, db_session):
        """process_meta_jobs should not process more jobs than the given limit."""
        data = _seed(db_session)
        scheduler = MetaJobScheduler(db_session)

        now = datetime.utcnow()
        for i in range(5):
            job = ScheduledJob(
                id=uuid4(),
                org_id=data["org_id"],
                job_type=SyncJobType.META_SYNC_ASSETS.value,
                reference_id=data["ad_account_id"],
                scheduled_for=now - timedelta(minutes=10 - i),
            )
            db_session.add(job)
        db_session.commit()

        with patch.object(
            scheduler,
            "_execute_job",
            return_value={
                "job_id": "mocked",
                "job_type": "mocked",
                "status": "completed",
                "result": {"status": "ok"},
            },
        ) as mock_exec:
            results = scheduler.process_meta_jobs(limit=3)

        assert len(results) == 3
        assert mock_exec.call_count == 3
