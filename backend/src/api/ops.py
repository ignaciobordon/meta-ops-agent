"""
Sprint 7 -- BLOQUE 8: Ops Console API.
Admin-only endpoints for job monitoring and provider health.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.src.database.models import JobRun, JobRunStatus
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user, require_admin
from backend.src.providers.circuit_breaker import PersistentCircuitBreaker
from backend.src.providers.rate_limiter import ProviderRateLimiter, PROVIDER_LIMITS

router = APIRouter()


# ── Response Models ──────────────────────────────────────────────────────


class JobRunResponse(BaseModel):
    id: str
    org_id: str
    job_type: str
    status: str
    queue: Optional[str] = None
    attempts: int
    max_attempts: int
    payload: Optional[dict] = None
    scheduled_for: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None
    trace_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class ProviderStatusResponse(BaseModel):
    provider: str
    circuit_state: str
    failure_count: int
    rate_limit_remaining: int
    rate_limit_total: int


class QueueStatsResponse(BaseModel):
    queue_name: str
    pending: int
    running: int
    failed: int


# ── Helper ───────────────────────────────────────────────────────────────


def _to_response(job: JobRun) -> JobRunResponse:
    from backend.src.jobs.queue import QUEUE_ROUTING
    return JobRunResponse(
        id=str(job.id),
        org_id=str(job.org_id),
        job_type=job.job_type,
        status=job.status.value if hasattr(job.status, "value") else str(job.status),
        queue=QUEUE_ROUTING.get(job.job_type, "default"),
        attempts=job.attempts or 0,
        max_attempts=job.max_attempts or 5,
        payload=job.payload_json,
        scheduled_for=job.scheduled_for.isoformat() if job.scheduled_for else None,
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
        last_error_code=job.last_error_code,
        last_error_message=job.last_error_message,
        trace_id=job.trace_id,
        idempotency_key=job.idempotency_key,
        created_at=job.created_at.isoformat() if job.created_at else None,
    )


# ── Job Endpoints ────────────────────────────────────────────────────────


@router.get("/jobs", response_model=List[JobRunResponse])
def list_job_runs(
    status: Optional[str] = Query(None, description="Filter by status"),
    job_type: Optional[str] = Query(None, description="Filter by job type"),
    limit: int = Query(50, le=200),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List job runs for the current org."""
    org_id = user.get("org_id", "")
    query = db.query(JobRun).filter(JobRun.org_id == UUID(org_id))

    if status:
        query = query.filter(JobRun.status == status)
    if job_type:
        query = query.filter(JobRun.job_type == job_type)

    jobs = query.order_by(JobRun.created_at.desc()).limit(limit).all()
    return [_to_response(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobRunResponse)
def get_job_run(
    job_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get details of a specific job run."""
    org_id = user.get("org_id", "")
    job = db.query(JobRun).filter(
        JobRun.id == UUID(job_id),
        JobRun.org_id == UUID(org_id),
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job run not found")
    return _to_response(job)


@router.post("/jobs/{job_id}/retry")
def retry_job(
    job_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Re-enqueue a failed or dead job."""
    org_id = user.get("org_id", "")
    job = db.query(JobRun).filter(
        JobRun.id == UUID(job_id),
        JobRun.org_id == UUID(org_id),
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job run not found")
    if job.status not in (JobRunStatus.FAILED, JobRunStatus.DEAD):
        raise HTTPException(status_code=400, detail="Can only retry failed or dead jobs")

    from backend.src.jobs.queue import enqueue
    new_id = enqueue(
        task_name=job.job_type,
        payload=job.payload_json or {},
        org_id=job.org_id,
        scheduled_job_id=job.scheduled_job_id,
        trace_id=job.trace_id,
        max_attempts=job.max_attempts,
        db=db,
    )
    db.commit()
    return {"message": "Job re-enqueued", "new_job_run_id": new_id}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Cancel a queued or running job."""
    org_id = user.get("org_id", "")
    job = db.query(JobRun).filter(
        JobRun.id == UUID(job_id),
        JobRun.org_id == UUID(org_id),
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job run not found")
    if job.status in (JobRunStatus.SUCCEEDED, JobRunStatus.DEAD):
        raise HTTPException(status_code=400, detail="Cannot cancel a terminal job")

    job.status = JobRunStatus.CANCELED
    job.finished_at = datetime.utcnow()
    db.commit()
    return {"message": "Job canceled", "job_id": job_id}


# ── Provider Endpoints ───────────────────────────────────────────────────


@router.get("/providers", response_model=List[ProviderStatusResponse])
def list_providers(user: dict = Depends(get_current_user)):
    """Get circuit breaker and rate limit status for all providers."""
    org_id = UUID(user.get("org_id", ""))
    results = []
    for provider_name, limits in PROVIDER_LIMITS.items():
        cb = PersistentCircuitBreaker(provider_name, org_id)
        rl = ProviderRateLimiter(provider_name, org_id)
        results.append(ProviderStatusResponse(
            provider=provider_name,
            circuit_state=cb.state,
            failure_count=cb._load_state().get("failure_count", 0),
            rate_limit_remaining=rl.tokens_remaining(),
            rate_limit_total=limits["rate"],
        ))
    return results


# ── Queue Stats ──────────────────────────────────────────────────────────


@router.get("/queues", response_model=List[QueueStatsResponse])
def list_queue_stats(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get queue statistics (pending/running/failed counts per queue)."""
    org_id = UUID(user.get("org_id", ""))

    from backend.src.jobs.queue import QUEUE_ROUTING
    # Invert routing: queue_name -> [job_types]
    queue_types = {"default": [], "io": [], "llm": []}
    for jtype, qname in QUEUE_ROUTING.items():
        queue_types.setdefault(qname, []).append(jtype)

    results = []
    for q_name, types in queue_types.items():
        if not types:
            types = ["__none__"]

        pending = db.query(JobRun).filter(
            JobRun.org_id == org_id,
            JobRun.job_type.in_(types),
            JobRun.status.in_([JobRunStatus.QUEUED, JobRunStatus.RETRY_SCHEDULED]),
        ).count()
        running = db.query(JobRun).filter(
            JobRun.org_id == org_id,
            JobRun.job_type.in_(types),
            JobRun.status == JobRunStatus.RUNNING,
        ).count()
        failed = db.query(JobRun).filter(
            JobRun.org_id == org_id,
            JobRun.job_type.in_(types),
            JobRun.status.in_([JobRunStatus.FAILED, JobRunStatus.DEAD]),
        ).count()
        results.append(QueueStatsResponse(
            queue_name=q_name, pending=pending, running=running, failed=failed,
        ))

    return results
