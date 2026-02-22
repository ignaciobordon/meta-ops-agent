"""
Sprint 6 – BLOQUE E: Meta Job Scheduler
Reuses ScheduledJob (Sprint 5) for recurring meta sync jobs.
Manages enqueue, retry/backoff, next_run_at logic.
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from backend.src.database.models import (
    MetaAdAccount,
    MetaConnection,
    PlanEnum,
    ScheduledJob,
    Subscription,
    SyncJobType,
)
from src.utils.logging_config import logger


# Frequency map: job_type → (PRO interval minutes, TRIAL interval minutes)
JOB_FREQUENCIES = {
    SyncJobType.META_SYNC_ASSETS.value: (5, 15),
    SyncJobType.META_SYNC_INSIGHTS.value: (15, 60),
    SyncJobType.META_LIVE_MONITOR.value: (5, 30),
    SyncJobType.META_GENERATE_ALERTS.value: (30, 120),
}


class MetaJobScheduler:
    """Manages recurring meta sync jobs using ScheduledJob table."""

    def __init__(self, db: Session):
        self.db = db

    def _get_interval_minutes(self, org_id: UUID, job_type: str) -> int:
        """Get job interval based on subscription plan."""
        sub = self.db.query(Subscription).filter(Subscription.org_id == org_id).first()
        plan = sub.plan if sub else PlanEnum.TRIAL

        pro_interval, trial_interval = JOB_FREQUENCIES.get(
            job_type, (15, 60)
        )

        if plan in (PlanEnum.PRO, PlanEnum.ENTERPRISE, PlanEnum.WHITE_LABEL):
            return pro_interval
        return trial_interval

    def enqueue_if_missing(self, org_id: UUID, ad_account_id: UUID) -> List[ScheduledJob]:
        """Enqueue initial sync jobs for a newly connected ad account."""
        created = []
        now = datetime.utcnow()

        for job_type in [
            SyncJobType.META_SYNC_ASSETS.value,
            SyncJobType.META_SYNC_INSIGHTS.value,
            SyncJobType.META_LIVE_MONITOR.value,
            SyncJobType.META_GENERATE_ALERTS.value,
        ]:
            # Check if job already exists and is not completed
            existing = self.db.query(ScheduledJob).filter(
                ScheduledJob.org_id == org_id,
                ScheduledJob.job_type == job_type,
                ScheduledJob.reference_id == ad_account_id,
                ScheduledJob.completed_at.is_(None),
            ).first()

            if existing:
                continue

            interval = self._get_interval_minutes(org_id, job_type)
            job = ScheduledJob(
                org_id=org_id,
                job_type=job_type,
                reference_id=ad_account_id,
                scheduled_for=now,
                next_run_at=now + timedelta(minutes=interval),
            )
            self.db.add(job)
            created.append(job)

        if created:
            self.db.flush()
            logger.info(
                "META_JOBS_ENQUEUED | org={} | acc={} | count={}",
                org_id, ad_account_id, len(created),
            )

        return created

    def reschedule_job(self, job: ScheduledJob, success: bool, error_msg: Optional[str] = None):
        """After a job completes (or fails), mark done + create next run."""
        now = datetime.utcnow()
        job.completed_at = now

        if not success:
            job.attempts = (job.attempts or 0) + 1
            job.error_message = error_msg

            # Backoff: base interval * 2^attempts (max 360 min = 6 hours)
            max_attempts = job.max_attempts or 5
            if job.attempts >= max_attempts:
                logger.warning(
                    "META_JOB_MAX_RETRIES | job_id={} | type={} | attempts={}",
                    job.id, job.job_type, job.attempts,
                )
                return  # Don't reschedule; requires manual intervention

        # Schedule next run
        interval = self._get_interval_minutes(job.org_id, job.job_type)
        if not success:
            # Exponential backoff on failure
            backoff_factor = min(2 ** (job.attempts or 0), 64)
            interval = min(interval * backoff_factor, 360)

        next_job = ScheduledJob(
            org_id=job.org_id,
            job_type=job.job_type,
            reference_id=job.reference_id,
            scheduled_for=now + timedelta(minutes=interval),
            next_run_at=now + timedelta(minutes=interval * 2),
            attempts=0 if success else (job.attempts or 0),
            max_attempts=job.max_attempts or 5,
        )
        self.db.add(next_job)

    def process_meta_jobs(self, limit: int = 20) -> List[Dict]:
        """Process pending meta sync jobs that are due."""
        now = datetime.utcnow()

        meta_job_types = [jt.value for jt in SyncJobType]

        jobs = self.db.query(ScheduledJob).filter(
            ScheduledJob.job_type.in_(meta_job_types),
            ScheduledJob.scheduled_for <= now,
            ScheduledJob.completed_at.is_(None),
        ).order_by(ScheduledJob.scheduled_for).limit(limit).all()

        results = []
        for job in jobs:
            result = self._execute_job(job)
            results.append(result)

        self.db.commit()
        return results

    def _execute_job(self, job: ScheduledJob) -> Dict:
        """Enqueue a scheduled job to the worker queue (Sprint 7).
        ScheduledJob remains the scheduler source of truth.
        Actual execution happens via Celery workers.
        """
        ad_account_id = job.reference_id
        org_id = job.org_id

        logger.info(
            "META_JOB_ENQUEUE | job_id={} | type={} | org={} | acc={}",
            job.id, job.job_type, org_id, ad_account_id,
        )

        try:
            from backend.src.jobs.queue import enqueue

            payload = {
                "ad_account_id": str(ad_account_id),
                "org_id": str(org_id),
            }
            idempotency_key = f"{job.job_type}:{org_id}:{ad_account_id}"

            job_run_id = enqueue(
                task_name=job.job_type,
                payload=payload,
                org_id=org_id,
                idempotency_key=idempotency_key,
                scheduled_job_id=job.id,
                db=self.db,
            )

            # Reschedule for next run
            self.reschedule_job(job, success=True)

            return {
                "job_id": str(job.id),
                "job_run_id": job_run_id,
                "job_type": job.job_type,
                "status": "enqueued",
            }

        except Exception as e:
            logger.error("META_JOB_ENQUEUE_FAILED | job_id={} | error={}", job.id, str(e))
            self.reschedule_job(job, success=False, error_msg=str(e))
            return {
                "job_id": str(job.id),
                "job_type": job.job_type,
                "status": "failed",
                "error": str(e),
            }
