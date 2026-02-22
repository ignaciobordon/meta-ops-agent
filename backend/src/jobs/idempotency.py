"""
Sprint 7 -- BLOQUE 3: Idempotency Guard.
Prevents duplicate job execution using:
1. DB-level UNIQUE constraint on (org_id, job_type, idempotency_key)
2. Redis SETNX lock for concurrent execution prevention
"""
from typing import Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.src.database.models import JobRun, JobRunStatus
from src.utils.logging_config import logger

LOCK_TTL_SECONDS = 300  # 5 minutes


def get_or_create_job_run(
    db: Session,
    idempotency_key: str,
    org_id: UUID,
    job_type: str,
    payload: dict,
    max_attempts: int = 5,
    trace_id: Optional[str] = None,
) -> Tuple[JobRun, bool]:
    """
    Get existing JobRun by idempotency key, or create a new one.
    Returns (job_run, is_new).

    If the existing run has a terminal status (SUCCEEDED, FAILED, CANCELED, DEAD),
    its idempotency_key is cleared so a new run can be created with the same key.
    """
    TERMINAL_STATUSES = {
        JobRunStatus.SUCCEEDED,
        JobRunStatus.FAILED,
        JobRunStatus.CANCELED,
        JobRunStatus.DEAD,
    }

    # Check for existing
    existing = db.query(JobRun).filter(
        JobRun.org_id == org_id,
        JobRun.job_type == job_type,
        JobRun.idempotency_key == idempotency_key,
    ).first()

    if existing:
        if existing.status in TERMINAL_STATUSES:
            # Terminal run -- clear key so a new one can be created
            existing.idempotency_key = None
            db.flush()
        else:
            return existing, False

    # Create new
    job_run = JobRun(
        id=uuid4(),
        org_id=org_id,
        job_type=job_type,
        status=JobRunStatus.QUEUED,
        payload_json=payload,
        idempotency_key=idempotency_key,
        max_attempts=max_attempts,
        trace_id=trace_id,
    )

    try:
        db.add(job_run)
        db.flush()
        return job_run, True
    except IntegrityError:
        db.rollback()
        existing = db.query(JobRun).filter(
            JobRun.org_id == org_id,
            JobRun.job_type == job_type,
            JobRun.idempotency_key == idempotency_key,
        ).first()
        if existing:
            return existing, False
        raise


def acquire_execution_lock(job_run_id: str, ttl: int = LOCK_TTL_SECONDS) -> bool:
    """Acquire a Redis-based execution lock. Returns True if acquired."""
    try:
        from backend.src.infra.redis_client import get_redis
        redis = get_redis()
    except Exception:
        return True  # No Redis = allow (degraded mode)

    if redis is None:
        return True  # Degraded mode: allow execution

    lock_key = f"job_lock:{job_run_id}"
    return bool(redis.set(lock_key, "1", ex=ttl, nx=True))


def release_execution_lock(job_run_id: str):
    """Release the execution lock."""
    try:
        from backend.src.infra.redis_client import get_redis
        redis = get_redis()
    except Exception:
        return

    if redis is None:
        return

    lock_key = f"job_lock:{job_run_id}"
    redis.delete(lock_key)
