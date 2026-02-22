"""
CI AutoLoop Orchestrator — autonomous competitive intelligence pipeline.

Pipeline: scheduler → collectors → normalizer → persistence → detectors → opportunities → alerts

Tick-based: CIAutoLoop.tick(now) enumerates orgs, decides what to run,
enqueues idempotent Celery tasks.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from backend.src.ci.models import CIRun, CIRunStatus, CIRunType
from backend.src.config import settings
from backend.src.database.models import Organization, Subscription, PlanEnum, SubscriptionStatusEnum
from backend.src.observability.metrics import track_ci_tick_orgs
from src.utils.logging_config import logger


# ── Helpers ─────────────────────────────────────────────────────────────────

def _get_enabled_sources() -> list[str]:
    """Return only sources enabled by feature flags."""
    sources = []
    if settings.CI_SOURCE_WEB_ENABLED:
        sources.append("web")
    if settings.CI_SOURCE_META_ADS_ENABLED:
        sources.append("meta_ads")
    if settings.CI_SOURCE_GOOGLE_ADS_ENABLED:
        sources.append("google_ads")
    if settings.CI_SOURCE_TIKTOK_ENABLED:
        sources.append("tiktok")
    # Instagram + social_scraping NOT included — behind Nivel C flag
    return sources


def _get_plan(db: Session, org_id: UUID) -> str:
    """Resolve the current plan for an org. Defaults to 'trial'."""
    sub = db.query(Subscription).filter(Subscription.org_id == org_id).first()
    if not sub:
        return "trial"
    return sub.plan.value if hasattr(sub.plan, "value") else str(sub.plan)


def _get_sub_status(db: Session, org_id: UUID) -> str:
    """Resolve the subscription status. Defaults to 'trialing'."""
    sub = db.query(Subscription).filter(Subscription.org_id == org_id).first()
    if not sub:
        return "trialing"
    return sub.status.value if hasattr(sub.status, "value") else str(sub.status)


def _ingest_interval(plan: str) -> int:
    """Return ingest interval in minutes for the plan."""
    if plan in ("pro", "enterprise", "white_label"):
        return settings.CI_INGEST_INTERVAL_MINUTES_PRO
    return settings.CI_INGEST_INTERVAL_MINUTES_TRIAL


def _detect_interval(plan: str) -> int:
    """Return detect interval in minutes for the plan."""
    if plan in ("pro", "enterprise", "white_label"):
        return settings.CI_DETECT_INTERVAL_MINUTES_PRO
    return settings.CI_DETECT_INTERVAL_MINUTES_TRIAL


def _max_competitors(plan: str) -> int:
    if plan in ("pro", "enterprise", "white_label"):
        return settings.CI_MAX_COMPETITORS_PRO
    return settings.CI_MAX_COMPETITORS_TRIAL


def _max_items(plan: str) -> int:
    if plan in ("pro", "enterprise", "white_label"):
        return settings.CI_MAX_ITEMS_PER_RUN_PRO
    return settings.CI_MAX_ITEMS_PER_RUN_TRIAL


def make_idempotency_key(
    run_type: str,
    org_id: UUID | str,
    source: str | None,
    now: datetime,
    interval_minutes: int,
) -> str:
    """
    Build a unique, deterministic idempotency key per run window.

    Format:
        ci:{run_type}:{org_id}:{source}:{yyyy-mm-dd}:{bucket}
    Bucket = floor(minutes_since_midnight / interval).
    """
    day = now.strftime("%Y-%m-%d")
    minutes_since_midnight = now.hour * 60 + now.minute
    bucket = math.floor(minutes_since_midnight / max(interval_minutes, 1))
    source_part = source or "all"
    return f"ci:{run_type}:{org_id}:{source_part}:{day}:{bucket}"


# ── Orchestrator ────────────────────────────────────────────────────────────


class CIAutoLoop:
    """
    Scheduler-driven orchestrator.

    Call tick(now) periodically (e.g., every minute via Celery beat / cron).
    It will enumerate eligible orgs and enqueue ingest/detect tasks
    as needed, respecting plan gates and idempotency.
    """

    def tick(self, now: datetime, db: Session, force: bool = False) -> dict:
        """
        Main entry point. Returns a summary dict.

        When force=True (manual run-now), bypass should_run scheduling
        guards so scans always execute regardless of elapsed time or
        idempotency windows.
        """
        if not settings.CI_AUTOLOOP_ENABLED:
            return {"status": "disabled"}

        orgs = db.query(Organization).all()
        summary = {
            "orgs_checked": 0,
            "ingest_enqueued": 0,
            "detect_enqueued": 0,
            "skipped": 0,
        }

        for org in orgs:
            summary["orgs_checked"] += 1
            org_id = org.id
            plan = _get_plan(db, org_id)
            sub_status = _get_sub_status(db, org_id)

            # Past-due/canceled: skip external fetch entirely (unless forced)
            if not force and sub_status in ("past_due", "canceled"):
                # Allow detect only (no external fetch) — or skip completely
                if self.should_run_detect(org_id, plan, now, db):
                    self.enqueue_detect(org_id, db, now, plan)
                    summary["detect_enqueued"] += 1
                else:
                    summary["skipped"] += 1
                continue

            # Ingest per enabled source (feature-flag gated)
            for source in _get_enabled_sources():
                if force or self.should_run_ingest(org_id, plan, now, db, source):
                    self.enqueue_ingest(org_id, source, db, now, plan, force=force)
                    summary["ingest_enqueued"] += 1

            # Detect
            if force or self.should_run_detect(org_id, plan, now, db):
                self.enqueue_detect(org_id, db, now, plan, force=force)
                summary["detect_enqueued"] += 1

        track_ci_tick_orgs(summary["orgs_checked"])

        logger.info(
            "CI_AUTOLOOP_TICK | orgs={} | ingest={} | detect={} | skipped={}",
            summary["orgs_checked"],
            summary["ingest_enqueued"],
            summary["detect_enqueued"],
            summary["skipped"],
        )
        return summary

    # ── Decision Logic ──────────────────────────────────────────────────

    def should_run_ingest(
        self,
        org_id: UUID,
        plan: str,
        now: datetime,
        db: Session,
        source: str = "web",
    ) -> bool:
        interval = _ingest_interval(plan)
        idem_key = make_idempotency_key("ingest", org_id, source, now, interval)

        # Check if already exists in ci_runs (any non-terminal status or succeeded this window)
        existing = db.query(CIRun).filter(
            CIRun.idempotency_key == idem_key,
        ).first()
        if existing:
            return False

        # Check last successful ingest for this source
        last = (
            db.query(CIRun)
            .filter(
                CIRun.org_id == org_id,
                CIRun.run_type == CIRunType.INGEST,
                CIRun.source == source,
                CIRun.status == CIRunStatus.SUCCEEDED,
            )
            .order_by(CIRun.finished_at.desc())
            .first()
        )

        if last and last.finished_at:
            elapsed = (now - last.finished_at).total_seconds() / 60
            if elapsed < interval:
                return False

        return True

    def should_run_detect(
        self,
        org_id: UUID,
        plan: str,
        now: datetime,
        db: Session,
    ) -> bool:
        interval = _detect_interval(plan)
        idem_key = make_idempotency_key("detect", org_id, None, now, interval)

        existing = db.query(CIRun).filter(
            CIRun.idempotency_key == idem_key,
        ).first()
        if existing:
            return False

        last = (
            db.query(CIRun)
            .filter(
                CIRun.org_id == org_id,
                CIRun.run_type == CIRunType.DETECT,
                CIRun.status == CIRunStatus.SUCCEEDED,
            )
            .order_by(CIRun.finished_at.desc())
            .first()
        )

        if last and last.finished_at:
            elapsed = (now - last.finished_at).total_seconds() / 60
            if elapsed < interval:
                return False

        return True

    # ── Enqueue ─────────────────────────────────────────────────────────

    def enqueue_ingest(
        self,
        org_id: UUID,
        source: str,
        db: Session,
        now: datetime,
        plan: str,
        force: bool = False,
    ) -> Optional[str]:
        interval = _ingest_interval(plan)
        idem_key = make_idempotency_key("ingest", org_id, source, now, interval)

        # When force=True (manual run-now), scan ALL competitors, not plan limit
        max_comp = 200 if force else _max_competitors(plan)
        max_it = 1000 if force else _max_items(plan)

        from backend.src.jobs.queue import enqueue
        job_run_id = enqueue(
            task_name="ci_ingest",
            payload={
                "source": source,
                "max_competitors": max_comp,
                "max_items": max_it,
            },
            org_id=org_id,
            idempotency_key=idem_key,
            queue="ci_io",
            db=db,
        )

        # Create ci_run row
        from uuid import UUID as _UUID
        ci_run = CIRun(
            org_id=org_id,
            run_type=CIRunType.INGEST,
            source=source,
            status=CIRunStatus.QUEUED,
            job_run_id=_UUID(job_run_id) if job_run_id else None,
            idempotency_key=idem_key,
        )
        db.add(ci_run)
        db.flush()

        logger.info(
            "CI_INGEST_ENQUEUED | org={} | source={} | key={} | job_run_id={}",
            org_id, source, idem_key, job_run_id,
        )
        return job_run_id

    def enqueue_detect(
        self,
        org_id: UUID,
        db: Session,
        now: datetime,
        plan: str,
        force: bool = False,
    ) -> Optional[str]:
        interval = _detect_interval(plan)
        idem_key = make_idempotency_key("detect", org_id, None, now, interval)

        max_comp = 200 if force else _max_competitors(plan)
        max_it = 1000 if force else _max_items(plan)

        from backend.src.jobs.queue import enqueue
        job_run_id = enqueue(
            task_name="ci_detect",
            payload={
                "max_competitors": max_comp,
                "max_items": max_it,
            },
            org_id=org_id,
            idempotency_key=idem_key,
            queue="ci_cpu",
            db=db,
        )

        ci_run = CIRun(
            org_id=org_id,
            run_type=CIRunType.DETECT,
            source=None,
            status=CIRunStatus.QUEUED,
            job_run_id=UUID(job_run_id) if job_run_id else None,
            idempotency_key=idem_key,
        )
        db.add(ci_run)
        db.flush()

        logger.info(
            "CI_DETECT_ENQUEUED | org={} | key={} | job_run_id={}",
            org_id, idem_key, job_run_id,
        )
        return job_run_id
