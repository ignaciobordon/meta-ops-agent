"""
Sprint 7 -- BLOQUE 1: Queue abstraction.
enqueue() creates a JobRun row, then sends to Celery.
Falls back to synchronous execution if Celery is unavailable.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from backend.src.database.models import JobRun, JobRunStatus
from backend.src.retries.backoff import get_max_attempts
from src.utils.logging_config import logger, get_trace_id

# Map job_type -> Celery queue name
QUEUE_ROUTING = {
    "meta_sync_assets": "io",
    "meta_sync_insights": "io",
    "meta_live_monitor": "io",
    "meta_generate_alerts": "io",
    "outcome_capture": "io",
    "decision_execute": "default",
    "creatives_generate": "llm",
    "opportunities_analyze": "llm",
    "content_studio_generate": "llm",
    "ci_ingest": "ci_io",
    "ci_detect": "ci_cpu",
    "unified_intelligence_analyze": "llm",
    "flywheel_run": "default",
    "data_room_export": "io",
}


def enqueue(
    task_name: str,
    payload: dict,
    org_id,
    idempotency_key: Optional[str] = None,
    queue: Optional[str] = None,
    eta: Optional[datetime] = None,
    scheduled_job_id=None,
    trace_id: Optional[str] = None,
    max_attempts: Optional[int] = None,
    db=None,
) -> str:
    """
    Create a JobRun row and dispatch to Celery.
    Returns the job_run_id as string.

    If db is provided, uses that session. Otherwise creates a new one.
    """
    job_run_id = uuid4()
    resolved_queue = queue or QUEUE_ROUTING.get(task_name, "default")
    resolved_trace = trace_id or get_trace_id()
    resolved_max = max_attempts or get_max_attempts(task_name)

    # Ensure org_id is UUID
    if isinstance(org_id, str):
        org_id = UUID(org_id)
    if scheduled_job_id and isinstance(scheduled_job_id, str):
        scheduled_job_id = UUID(scheduled_job_id)

    job_run = JobRun(
        id=job_run_id,
        org_id=org_id,
        scheduled_job_id=scheduled_job_id,
        job_type=task_name,
        status=JobRunStatus.QUEUED,
        payload_json=payload,
        idempotency_key=idempotency_key,
        max_attempts=resolved_max,
        scheduled_for=eta or datetime.utcnow(),
        trace_id=resolved_trace,
    )

    if db:
        db.add(job_run)
        db.flush()
    else:
        from backend.src.database.session import SessionLocal
        session = SessionLocal()
        try:
            session.add(job_run)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # Dispatch to Celery or fall back to sync execution
    dispatched_to_celery = False
    try:
        from backend.src.infra.celery_app import celery_app
        if celery_app is not None:
            celery_app.send_task(
                f"backend.src.jobs.tasks.{task_name}",
                args=[str(job_run_id)],
                queue=resolved_queue,
                eta=eta,
            )
            dispatched_to_celery = True
    except Exception as e:
        logger.warning(
            "CELERY_DISPATCH_FAILED | job_run_id={} | task={} | error={} | falling_back_to_sync",
            job_run_id, task_name, str(e),
        )

    if not dispatched_to_celery:
        import threading
        logger.info(
            "SYNC_FALLBACK | job_run_id={} | task={} | Celery unavailable, running in-process",
            job_run_id, task_name,
        )
        # If using caller's db session, the JobRun was only flushed (not committed).
        # The background thread opens a NEW session and won't see uncommitted rows.
        # Commit now so the thread can find the JobRun.
        if db:
            try:
                db.commit()
            except Exception:
                db.rollback()
                raise
        thread = threading.Thread(
            target=_run_sync_fallback,
            args=(str(job_run_id), task_name),
            daemon=True,
        )
        thread.start()

    logger.info(
        "JOB_ENQUEUED | job_run_id={} | task={} | queue={} | org={} | celery={}",
        job_run_id, task_name, resolved_queue, org_id, dispatched_to_celery,
    )
    return str(job_run_id)


def _run_sync_fallback(job_run_id: str, task_name: str):
    """Execute job synchronously in a background thread (no Celery)."""
    try:
        from backend.src.jobs.task_runner import run_job
        run_job(job_run_id, task_name)
    except Exception as e:
        logger.error(
            "SYNC_FALLBACK_FAILED | job_run_id={} | task={} | error={}",
            job_run_id, task_name, str(e)[:200],
        )
