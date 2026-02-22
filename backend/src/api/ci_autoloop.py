"""
CI AutoLoop API — status, manual triggers, run history.

Endpoints:
    GET  /status          — AutoLoop config + last run timestamps
    POST /run-now         — Trigger a tick immediately (admin-only)
    GET  /runs            — Paginated CI run history
    GET  /runs/{id}       — Single CI run detail
    POST /enabled         — Toggle autoloop on/off (admin-only)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.src.ci.models import CIRun, CIRunStatus, CIRunType
from backend.src.config import settings
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user, require_admin
from src.utils.logging_config import logger

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────


class AutoLoopStatusResponse(BaseModel):
    enabled: bool
    ingest_interval_trial: int
    ingest_interval_pro: int
    detect_interval_trial: int
    detect_interval_pro: int
    max_competitors_trial: int
    max_competitors_pro: int
    max_items_trial: int
    max_items_pro: int
    last_ingest_at: Optional[str] = None
    last_detect_at: Optional[str] = None
    total_runs: int = 0
    succeeded_runs: int = 0
    failed_runs: int = 0


class CIRunResponse(BaseModel):
    id: str
    org_id: str
    run_type: str
    source: Optional[str] = None
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    items_collected: int = 0
    opportunities_created: int = 0
    alerts_created: int = 0
    job_run_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    error_class: Optional[str] = None
    error_message: Optional[str] = None
    metadata_json: Optional[dict] = None
    created_at: Optional[str] = None


class RunNowResponse(BaseModel):
    status: str
    summary: dict


class EnabledRequest(BaseModel):
    enabled: bool


class EnabledResponse(BaseModel):
    enabled: bool
    message: str


# ── Helpers ──────────────────────────────────────────────────────────────────


def _ci_run_to_response(run: CIRun) -> CIRunResponse:
    return CIRunResponse(
        id=str(run.id),
        org_id=str(run.org_id),
        run_type=run.run_type.value if hasattr(run.run_type, "value") else str(run.run_type),
        source=run.source,
        status=run.status.value if hasattr(run.status, "value") else str(run.status),
        started_at=run.started_at.isoformat() if run.started_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        items_collected=run.items_collected or 0,
        opportunities_created=run.opportunities_created or 0,
        alerts_created=run.alerts_created or 0,
        job_run_id=str(run.job_run_id) if run.job_run_id else None,
        idempotency_key=run.idempotency_key,
        error_class=run.error_class,
        error_message=run.error_message,
        metadata_json=run.metadata_json,
        created_at=run.created_at.isoformat() if run.created_at else None,
    )


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/status", response_model=AutoLoopStatusResponse)
def get_autoloop_status(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return CI AutoLoop configuration and last run timestamps."""
    org_id = current_user.org_id

    # Last ingest
    last_ingest = (
        db.query(CIRun)
        .filter(
            CIRun.org_id == org_id,
            CIRun.run_type == CIRunType.INGEST,
            CIRun.status == CIRunStatus.SUCCEEDED,
        )
        .order_by(CIRun.finished_at.desc())
        .first()
    )

    # Last detect
    last_detect = (
        db.query(CIRun)
        .filter(
            CIRun.org_id == org_id,
            CIRun.run_type == CIRunType.DETECT,
            CIRun.status == CIRunStatus.SUCCEEDED,
        )
        .order_by(CIRun.finished_at.desc())
        .first()
    )

    # Counts
    total = db.query(CIRun).filter(CIRun.org_id == org_id).count()
    succeeded = (
        db.query(CIRun)
        .filter(CIRun.org_id == org_id, CIRun.status == CIRunStatus.SUCCEEDED)
        .count()
    )
    failed = (
        db.query(CIRun)
        .filter(CIRun.org_id == org_id, CIRun.status == CIRunStatus.FAILED)
        .count()
    )

    return AutoLoopStatusResponse(
        enabled=settings.CI_AUTOLOOP_ENABLED,
        ingest_interval_trial=settings.CI_INGEST_INTERVAL_MINUTES_TRIAL,
        ingest_interval_pro=settings.CI_INGEST_INTERVAL_MINUTES_PRO,
        detect_interval_trial=settings.CI_DETECT_INTERVAL_MINUTES_TRIAL,
        detect_interval_pro=settings.CI_DETECT_INTERVAL_MINUTES_PRO,
        max_competitors_trial=settings.CI_MAX_COMPETITORS_TRIAL,
        max_competitors_pro=settings.CI_MAX_COMPETITORS_PRO,
        max_items_trial=settings.CI_MAX_ITEMS_PER_RUN_TRIAL,
        max_items_pro=settings.CI_MAX_ITEMS_PER_RUN_PRO,
        last_ingest_at=(
            last_ingest.finished_at.isoformat() if last_ingest and last_ingest.finished_at else None
        ),
        last_detect_at=(
            last_detect.finished_at.isoformat() if last_detect and last_detect.finished_at else None
        ),
        total_runs=total,
        succeeded_runs=succeeded,
        failed_runs=failed,
    )


@router.post("/run-now", response_model=RunNowResponse)
def run_now(
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Manually trigger a CI AutoLoop tick (admin-only).

    Clears stale idempotency keys so the manual scan always runs.
    """
    from backend.src.ci.ci_autoloop import CIAutoLoop
    from backend.src.ci.models import CIRun, CIRunStatus
    from backend.src.database.models import JobRun

    now = datetime.utcnow()
    today_pattern = f"ci:%:{now.strftime('%Y-%m-%d')}:%"

    # Clear stale QUEUED/RUNNING ci_runs so manual scan bypasses idempotency
    stale = db.query(CIRun).filter(
        CIRun.status.in_([CIRunStatus.QUEUED, CIRunStatus.RUNNING]),
    ).all()
    for run in stale:
        run.status = CIRunStatus.FAILED
        run.error_message = "Cleared by manual run-now"
    if stale:
        db.flush()

    # Remove today's CIRun idempotency keys
    today_ci_runs = db.query(CIRun).filter(
        CIRun.idempotency_key.like(today_pattern),
    ).all()
    for run in today_ci_runs:
        run.idempotency_key = None
    if today_ci_runs:
        db.flush()

    # Also remove today's JobRun idempotency keys for CI tasks
    # (prevents UniqueConstraint violation on re-enqueue)
    today_jobs = db.query(JobRun).filter(
        JobRun.job_type.in_(["ci_ingest", "ci_detect"]),
        JobRun.idempotency_key.isnot(None),
        JobRun.idempotency_key.like(today_pattern),
    ).all()
    for job in today_jobs:
        job.idempotency_key = None
    if today_jobs:
        db.flush()

    loop = CIAutoLoop()

    try:
        summary = loop.tick(now, db, force=True)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("CI_RUN_NOW_FAILED | error={}", str(e)[:300])
        raise HTTPException(status_code=500, detail=f"CI tick failed: {str(e)[:200]}")

    logger.info(
        "CI_RUN_NOW | admin={} | summary={}",
        current_user.get("id", "?"), summary,
    )
    return RunNowResponse(status="ok", summary=summary)


@router.get("/runs", response_model=list[CIRunResponse])
def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    run_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List CI runs for the current org, newest first."""
    org_id = current_user.org_id

    q = db.query(CIRun).filter(CIRun.org_id == org_id)

    if run_type:
        q = q.filter(CIRun.run_type == run_type)
    if status:
        q = q.filter(CIRun.status == status)

    runs = q.order_by(CIRun.created_at.desc()).offset(offset).limit(limit).all()
    return [_ci_run_to_response(r) for r in runs]


@router.get("/runs/{run_id}", response_model=CIRunResponse)
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get a single CI run by ID."""
    org_id = current_user.org_id

    run = (
        db.query(CIRun)
        .filter(CIRun.id == UUID(run_id), CIRun.org_id == org_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="CI run not found")

    return _ci_run_to_response(run)


@router.post("/enabled", response_model=EnabledResponse)
def set_enabled(
    body: EnabledRequest,
    current_user=Depends(require_admin),
):
    """Toggle CI AutoLoop enabled/disabled (admin-only, runtime only)."""
    settings.CI_AUTOLOOP_ENABLED = body.enabled

    logger.info(
        "CI_AUTOLOOP_TOGGLED | admin={} | enabled={}",
        current_user.get("id", "?"), body.enabled,
    )
    return EnabledResponse(
        enabled=body.enabled,
        message=f"CI AutoLoop {'enabled' if body.enabled else 'disabled'}",
    )
