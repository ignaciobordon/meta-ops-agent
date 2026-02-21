"""Flywheel Service — Orchestrates the 8-step flywheel cycle.

Each run creates a FlywheelRun with 8 FlywheelStep rows.
Steps are executed sequentially; if a step fails the run stops.
"""
import time
from datetime import datetime
from typing import List, Optional, Dict, Any
from uuid import uuid4, UUID

from sqlalchemy.orm import Session

from backend.src.database.models import (
    FlywheelRun,
    FlywheelStep,
    JobRun,
    JobRunStatus,
    MetaAdAccount,
    MetaConnection,
    EntityMemory,
    FeatureMemory,
    MetaInsightsDaily,
    InsightLevel,
    Creative,
    ContentPack,
)
from backend.src.jobs.queue import enqueue
from src.utils.logging_config import logger

# Ordered list of the 8 flywheel steps
FLYWHEEL_STEPS = [
    "meta_sync",
    "brain_analysis",
    "saturation_check",
    "unified_intelligence",
    "opportunities",
    "creatives",
    "content_studio",
    "export",
]

# Steps that enqueue background jobs (all others are read-only checks)
_JOB_STEPS = {"meta_sync", "unified_intelligence", "creatives", "content_studio"}

# Maximum seconds to wait for a single job to complete
_POLL_TIMEOUT = 360
_POLL_INTERVAL = 2


class FlywheelService:
    """Orchestrate the 8-step flywheel cycle for an organization."""

    def __init__(self, db: Session, org_id):
        self.db = db
        self.org_id = UUID(str(org_id)) if not isinstance(org_id, UUID) else org_id

    # ── Public API ────────────────────────────────────────────────────────────

    def create_run(self, config: Optional[Dict[str, Any]] = None) -> FlywheelRun:
        """Create a FlywheelRun with 8 FlywheelStep rows."""
        config = config or {}

        ad_account_id = None
        if config.get("ad_account_id"):
            ad_account_id = UUID(config["ad_account_id"])

        run = FlywheelRun(
            id=uuid4(),
            org_id=self.org_id,
            ad_account_id=ad_account_id,
            status="queued",
            trigger=config.get("trigger", "manual"),
            config_json=config,
            outputs_json={},
        )
        self.db.add(run)
        self.db.flush()

        for order, step_name in enumerate(FLYWHEEL_STEPS, start=1):
            step = FlywheelStep(
                id=uuid4(),
                flywheel_run_id=run.id,
                step_name=step_name,
                step_order=order,
                status="pending",
                artifacts_json={},
            )
            self.db.add(step)

        self.db.flush()
        logger.info(
            "FLYWHEEL_RUN_CREATED | run_id={} | org={} | steps={}",
            run.id, self.org_id, len(FLYWHEEL_STEPS),
        )
        return run

    def execute_run(self, run_id: UUID):
        """Execute all steps of a flywheel run sequentially."""
        run = self.db.query(FlywheelRun).filter(FlywheelRun.id == run_id).first()
        if not run:
            raise ValueError(f"FlywheelRun {run_id} not found")

        run.status = "running"
        run.started_at = datetime.utcnow()
        self.db.commit()

        logger.info("FLYWHEEL_RUN_START | run_id={} | org={}", run_id, self.org_id)

        steps = (
            self.db.query(FlywheelStep)
            .filter(FlywheelStep.flywheel_run_id == run_id)
            .order_by(FlywheelStep.step_order)
            .all()
        )

        for step in steps:
            try:
                self._execute_step(run, step)
            except Exception as exc:
                step.status = "failed"
                step.finished_at = datetime.utcnow()
                step.error_message = str(exc)[:2000]
                run.status = "failed"
                run.finished_at = datetime.utcnow()
                run.error_message = f"Step '{step.step_name}' failed: {str(exc)[:500]}"
                self.db.commit()
                logger.error(
                    "FLYWHEEL_STEP_FAILED | run={} | step={} | error={}",
                    run_id, step.step_name, str(exc)[:200],
                )
                return

        # All steps succeeded
        run.status = "succeeded"
        run.finished_at = datetime.utcnow()
        self.db.commit()
        logger.info("FLYWHEEL_RUN_SUCCEEDED | run_id={} | org={}", run_id, self.org_id)

    def get_run_with_steps(self, run_id: UUID) -> Optional[Dict[str, Any]]:
        """Return run + steps with job status info."""
        run = (
            self.db.query(FlywheelRun)
            .filter(FlywheelRun.id == run_id, FlywheelRun.org_id == self.org_id)
            .first()
        )
        if not run:
            return None

        steps = (
            self.db.query(FlywheelStep)
            .filter(FlywheelStep.flywheel_run_id == run_id)
            .order_by(FlywheelStep.step_order)
            .all()
        )

        steps_data = []
        for s in steps:
            step_dict = {
                "id": str(s.id),
                "step_name": s.step_name,
                "step_order": s.step_order,
                "status": s.status,
                "job_run_id": str(s.job_run_id) if s.job_run_id else None,
                "artifacts_json": s.artifacts_json or {},
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "finished_at": s.finished_at.isoformat() if s.finished_at else None,
                "error_message": s.error_message,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            # Enrich with job status if applicable
            if s.job_run_id:
                job = self.db.query(JobRun).filter(JobRun.id == s.job_run_id).first()
                if job:
                    step_dict["job_status"] = job.status.value if job.status else None
                    step_dict["job_error"] = job.last_error_message
            steps_data.append(step_dict)

        return {
            "id": str(run.id),
            "org_id": str(run.org_id),
            "ad_account_id": str(run.ad_account_id) if run.ad_account_id else None,
            "status": run.status,
            "trigger": run.trigger,
            "config_json": run.config_json or {},
            "outputs_json": run.outputs_json or {},
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "error_message": run.error_message,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "steps": steps_data,
        }

    def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent flywheel runs for the org."""
        runs = (
            self.db.query(FlywheelRun)
            .filter(FlywheelRun.org_id == self.org_id)
            .order_by(FlywheelRun.created_at.desc())
            .limit(limit)
            .all()
        )
        result = []
        for r in runs:
            step_count = (
                self.db.query(FlywheelStep)
                .filter(FlywheelStep.flywheel_run_id == r.id)
                .count()
            )
            succeeded_count = (
                self.db.query(FlywheelStep)
                .filter(
                    FlywheelStep.flywheel_run_id == r.id,
                    FlywheelStep.status == "succeeded",
                )
                .count()
            )
            result.append({
                "id": str(r.id),
                "status": r.status,
                "trigger": r.trigger,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "error_message": r.error_message,
                "steps_total": step_count,
                "steps_succeeded": succeeded_count,
            })
        return result

    def cancel_run(self, run_id: UUID) -> Dict[str, Any]:
        """Cancel a running flywheel run and all its pending/running steps and jobs."""
        run = (
            self.db.query(FlywheelRun)
            .filter(FlywheelRun.id == run_id, FlywheelRun.org_id == self.org_id)
            .first()
        )
        if not run:
            raise ValueError(f"FlywheelRun {run_id} not found")
        if run.status in ("succeeded", "failed", "canceled"):
            raise ValueError(f"Run is already {run.status}")

        # Cancel all pending/running steps
        steps = (
            self.db.query(FlywheelStep)
            .filter(FlywheelStep.flywheel_run_id == run_id)
            .all()
        )
        canceled_jobs = 0
        for step in steps:
            if step.status in ("pending", "running"):
                step.status = "canceled"
                step.finished_at = datetime.utcnow()
            # Cancel any associated running/queued jobs
            if step.job_run_id:
                job = self.db.query(JobRun).filter(JobRun.id == step.job_run_id).first()
                if job and job.status in (JobRunStatus.QUEUED, JobRunStatus.RUNNING, JobRunStatus.RETRY_SCHEDULED):
                    job.status = JobRunStatus.CANCELED
                    job.finished_at = datetime.utcnow()
                    canceled_jobs += 1

        run.status = "canceled"
        run.finished_at = datetime.utcnow()
        run.error_message = "Canceled by user"
        self.db.commit()

        logger.info(
            "FLYWHEEL_RUN_CANCELED | run={} | org={} | canceled_jobs={}",
            run_id, self.org_id, canceled_jobs,
        )
        return {"run_id": str(run_id), "status": "canceled", "canceled_jobs": canceled_jobs}

    def retry_step(self, run_id: UUID, step_id: UUID) -> Dict[str, Any]:
        """Retry a single failed step."""
        run = (
            self.db.query(FlywheelRun)
            .filter(FlywheelRun.id == run_id, FlywheelRun.org_id == self.org_id)
            .first()
        )
        if not run:
            raise ValueError(f"FlywheelRun {run_id} not found")

        step = (
            self.db.query(FlywheelStep)
            .filter(FlywheelStep.id == step_id, FlywheelStep.flywheel_run_id == run_id)
            .first()
        )
        if not step:
            raise ValueError(f"FlywheelStep {step_id} not found")
        if step.status not in ("failed", "skipped"):
            raise ValueError(f"Step status is '{step.status}', only failed/skipped steps can be retried")

        # Reset step
        step.status = "pending"
        step.error_message = None
        step.started_at = None
        step.finished_at = None
        step.job_run_id = None
        step.artifacts_json = {}

        # Reset run status if it was failed
        if run.status == "failed":
            run.status = "running"
            run.error_message = None
            run.finished_at = None

        self.db.commit()

        # Execute the single step
        try:
            self._execute_step(run, step)
        except Exception as exc:
            step.status = "failed"
            step.finished_at = datetime.utcnow()
            step.error_message = str(exc)[:2000]
            self.db.commit()
            raise

        # Check if all steps are now succeeded
        all_steps = (
            self.db.query(FlywheelStep)
            .filter(FlywheelStep.flywheel_run_id == run_id)
            .all()
        )
        all_succeeded = all(s.status == "succeeded" for s in all_steps)
        if all_succeeded:
            run.status = "succeeded"
            run.finished_at = datetime.utcnow()
        self.db.commit()

        return {"step_id": str(step.id), "status": step.status}

    # ── Private step execution ────────────────────────────────────────────────

    def _execute_step(self, run: FlywheelRun, step: FlywheelStep):
        """Execute a single flywheel step."""
        step.status = "running"
        step.started_at = datetime.utcnow()
        self.db.commit()

        handler = getattr(self, f"_step_{step.step_name}", None)
        if not handler:
            raise ValueError(f"Unknown step: {step.step_name}")

        handler(run, step)

        if step.status == "running":
            step.status = "succeeded"
        step.finished_at = datetime.utcnow()
        self.db.commit()

        logger.info(
            "FLYWHEEL_STEP_DONE | run={} | step={} | status={}",
            run.id, step.step_name, step.status,
        )

    # ── Step 1: meta_sync ────────────────────────────────────────────────────

    def _step_meta_sync(self, run: FlywheelRun, step: FlywheelStep):
        """Enqueue meta_sync_assets + meta_sync_insights jobs."""
        # Find connected ad account
        ad_account = None
        if run.ad_account_id:
            ad_account = (
                self.db.query(MetaAdAccount)
                .filter(MetaAdAccount.id == run.ad_account_id, MetaAdAccount.org_id == self.org_id)
                .first()
            )
        else:
            ad_account = (
                self.db.query(MetaAdAccount)
                .filter(MetaAdAccount.org_id == self.org_id)
                .first()
            )

        if not ad_account:
            step.status = "skipped"
            step.artifacts_json = {"reason": "No ad account connected"}
            logger.info("FLYWHEEL_META_SYNC_SKIP | run={} | no ad account", run.id)
            return

        # Enqueue assets sync
        assets_job_id = enqueue(
            task_name="meta_sync_assets",
            payload={"ad_account_id": str(ad_account.id)},
            org_id=self.org_id,
            db=self.db,
        )

        # Enqueue insights sync
        insights_job_id = enqueue(
            task_name="meta_sync_insights",
            payload={"ad_account_id": str(ad_account.id)},
            org_id=self.org_id,
            db=self.db,
        )

        step.job_run_id = UUID(assets_job_id)
        step.artifacts_json = {
            "assets_job_id": assets_job_id,
            "insights_job_id": insights_job_id,
            "ad_account_id": str(ad_account.id),
        }
        self.db.commit()

        # Wait for both jobs to complete
        self._wait_for_job(assets_job_id)
        self._wait_for_job(insights_job_id)

    # ── Step 2: brain_analysis ───────────────────────────────────────────────

    def _step_brain_analysis(self, run: FlywheelRun, step: FlywheelStep):
        """Analyze Brain data: top entities, winning features, trust distribution."""
        entity_count = (
            self.db.query(EntityMemory)
            .filter(EntityMemory.org_id == self.org_id)
            .count()
        )
        feature_count = (
            self.db.query(FeatureMemory)
            .filter(FeatureMemory.org_id == self.org_id)
            .count()
        )

        # Top 5 trusted entities
        top_entities = (
            self.db.query(EntityMemory)
            .filter(EntityMemory.org_id == self.org_id)
            .order_by(EntityMemory.trust_score.desc())
            .limit(5)
            .all()
        )
        entities_data = [
            {"entity_id": e.entity_id, "type": e.entity_type, "trust_score": round(e.trust_score, 1)}
            for e in top_entities
        ]

        # Top 5 winning features (min 3 samples)
        top_features = (
            self.db.query(FeatureMemory)
            .filter(FeatureMemory.org_id == self.org_id, FeatureMemory.samples >= 3)
            .order_by(FeatureMemory.win_rate.desc())
            .limit(5)
            .all()
        )
        features_data = [
            {"key": f.feature_key, "type": f.feature_type.value if hasattr(f.feature_type, 'value') else str(f.feature_type),
             "win_rate": round(f.win_rate, 2), "samples": f.samples}
            for f in top_features
        ]

        # Trust distribution
        avg_trust = sum(e.trust_score for e in top_entities) / len(top_entities) if top_entities else 0

        step.artifacts_json = {
            "entity_memory_count": entity_count,
            "feature_memory_count": feature_count,
            "top_entities": entities_data,
            "winning_features": features_data,
            "avg_trust_score": round(avg_trust, 1),
        }
        if entity_count == 0 and feature_count == 0:
            step.artifacts_json["note"] = "No brain data yet — will be populated after outcomes"
        step.status = "succeeded"

    # ── Step 3: saturation_check ─────────────────────────────────────────────

    def _step_saturation_check(self, run: FlywheelRun, step: FlywheelStep):
        """Analyze creative saturation: fatigued vs fresh ads, frequency and CTR trends."""
        from datetime import timedelta

        total_count = (
            self.db.query(MetaInsightsDaily)
            .filter(MetaInsightsDaily.org_id == self.org_id)
            .count()
        )

        if total_count == 0:
            step.artifacts_json = {
                "insights_daily_count": 0,
                "note": "No insights data yet — run meta_sync first",
            }
            step.status = "succeeded"
            return

        since = datetime.utcnow() - timedelta(days=14)
        insights = (
            self.db.query(MetaInsightsDaily)
            .filter(
                MetaInsightsDaily.org_id == self.org_id,
                MetaInsightsDaily.level == InsightLevel.AD,
                MetaInsightsDaily.date_start >= since,
            )
            .order_by(MetaInsightsDaily.date_start.desc())
            .limit(100)
            .all()
        )

        # Group by ad and detect fatigue
        ad_data: Dict[str, list] = {}
        for row in insights:
            ad_data.setdefault(row.entity_meta_id, []).append(row)

        saturated_ads = []
        fresh_ads = []
        total_spend = 0.0
        all_frequencies = []

        for ad_id, rows in ad_data.items():
            total_spend += sum(float(r.spend or 0) for r in rows)
            if len(rows) < 2:
                continue
            avg_freq = sum(r.frequency or 0 for r in rows) / len(rows)
            avg_ctr = sum(r.ctr or 0 for r in rows) / len(rows)
            first_ctr = rows[-1].ctr or 0
            last_ctr = rows[0].ctr or 0
            all_frequencies.append(avg_freq)

            if avg_freq > 3.0 and last_ctr < first_ctr:
                saturated_ads.append({
                    "name": str(ad_id)[:60],
                    "frequency": round(avg_freq, 1),
                    "ctr_decline": round(first_ctr - last_ctr, 2),
                })
            elif avg_freq < 2.0 and avg_ctr > 1.0:
                fresh_ads.append({
                    "name": str(ad_id)[:60],
                    "ctr": round(avg_ctr, 2),
                })

        avg_frequency = round(sum(all_frequencies) / len(all_frequencies), 1) if all_frequencies else 0

        step.artifacts_json = {
            "insights_daily_count": total_count,
            "ads_analyzed": len(ad_data),
            "saturated_count": len(saturated_ads),
            "fresh_count": len(fresh_ads),
            "saturated_ads": saturated_ads[:5],
            "fresh_ads": fresh_ads[:5],
            "avg_frequency": avg_frequency,
            "total_spend_14d": round(total_spend, 2),
        }
        step.status = "succeeded"

    # ── Step 4: unified_intelligence ─────────────────────────────────────────

    def _step_unified_intelligence(self, run: FlywheelRun, step: FlywheelStep):
        """Run unified intelligence analysis inline (no separate job/polling)."""
        from backend.src.services.unified_intelligence import UnifiedIntelligenceService
        from sqlalchemy.orm.attributes import flag_modified

        brand_profile_id = (run.config_json or {}).get("brand_profile_id")
        svc = UnifiedIntelligenceService(self.db, self.org_id)
        opportunities = svc.analyze(brand_profile_id=brand_profile_id)

        # Create a JobRun record so the Opportunities API can find results
        job_run = JobRun(
            id=uuid4(),
            org_id=self.org_id,
            job_type="unified_intelligence_analyze",
            status=JobRunStatus.SUCCEEDED,
            payload_json={"result": opportunities},
            started_at=step.started_at,
            finished_at=datetime.utcnow(),
            max_attempts=1,
            attempts=1,
        )
        self.db.add(job_run)

        step.job_run_id = job_run.id
        step.artifacts_json = {
            "job_run_id": str(job_run.id),
            "opportunities_count": len(opportunities),
        }

        logger.info(
            "FLYWHEEL_UNIFIED_INTELLIGENCE_DONE | run={} | opportunities={}",
            run.id, len(opportunities),
        )

    # ── Step 5: opportunities ────────────────────────────────────────────────

    def _step_opportunities(self, run: FlywheelRun, step: FlywheelStep):
        """Read results from latest unified_intelligence or opportunities job with full details."""
        job = (
            self.db.query(JobRun)
            .filter(
                JobRun.org_id == self.org_id,
                JobRun.job_type.in_(["opportunities_analyze", "unified_intelligence_analyze"]),
                JobRun.status == JobRunStatus.SUCCEEDED,
            )
            .order_by(JobRun.finished_at.desc())
            .first()
        )

        opportunities = []
        if job and job.payload_json:
            opportunities = job.payload_json.get("result", [])

        # Compute source breakdown
        source_counts = {"brandmap": 0, "ci": 0, "saturation": 0, "brain": 0}
        priority_counts = {"high": 0, "medium": 0, "low": 0}
        total_impact = 0.0
        opp_summaries = []

        for opp in opportunities:
            for src in opp.get("sources", []):
                if src in source_counts:
                    source_counts[src] += 1
            p = opp.get("priority", "medium")
            if p in priority_counts:
                priority_counts[p] += 1
            total_impact += opp.get("estimated_impact", 0)
            opp_summaries.append({
                "id": opp.get("id", ""),
                "gap_id": opp.get("gap_id", ""),
                "title": opp.get("title", ""),
                "priority": opp.get("priority", "medium"),
                "estimated_impact": opp.get("estimated_impact", 0),
            })

        step.artifacts_json = {
            "opportunities_count": len(opportunities),
            "source_job_id": str(job.id) if job else None,
            "opportunities": opp_summaries,
            "top_opportunity": opportunities[0] if opportunities else None,
            "priority_breakdown": priority_counts,
            "source_breakdown": source_counts,
            "total_estimated_impact": round(total_impact, 2),
        }
        step.status = "succeeded"

    # ── Step 6: creatives ────────────────────────────────────────────────────

    def _step_creatives(self, run: FlywheelRun, step: FlywheelStep):
        """Enqueue creatives_generate with full context from all previous steps."""
        # Gather context from all previous steps
        prev_steps = (
            self.db.query(FlywheelStep)
            .filter(FlywheelStep.flywheel_run_id == run.id)
            .order_by(FlywheelStep.step_order)
            .all()
        )
        step_artifacts = {s.step_name: (s.artifacts_json or {}) for s in prev_steps}

        # Extract opportunities data
        opp_artifacts = step_artifacts.get("opportunities", {})
        all_opportunities = opp_artifacts.get("opportunities", [])
        top_opp = opp_artifacts.get("top_opportunity", {}) or {}

        # Extract brain context (winning features, top entities)
        brain_artifacts = step_artifacts.get("brain_analysis", {})
        winning_features = brain_artifacts.get("winning_features", [])
        top_entities = brain_artifacts.get("top_entities", [])

        # Extract saturation context (fatigued creatives to avoid)
        sat_artifacts = step_artifacts.get("saturation_check", {})
        saturated_ads = sat_artifacts.get("saturated_ads", [])
        fresh_ads = sat_artifacts.get("fresh_ads", [])

        payload = {
            "angle_id": top_opp.get("gap_id", "general"),
            "n_variants": (run.config_json or {}).get("n_variants", 3),
            "brand_profile_id": (run.config_json or {}).get("brand_profile_id"),
            # Pass full context from all previous steps
            "flywheel_context": {
                "all_opportunities": all_opportunities[:8],
                "winning_features": winning_features,
                "top_entities": top_entities,
                "saturated_ads": saturated_ads,
                "fresh_ads": fresh_ads,
                "priority_breakdown": opp_artifacts.get("priority_breakdown", {}),
            },
        }

        # Find ad account for creative storage
        ad_account = None
        if run.ad_account_id:
            ad_account = (
                self.db.query(MetaAdAccount)
                .filter(MetaAdAccount.id == run.ad_account_id)
                .first()
            )
        if not ad_account:
            ad_account = (
                self.db.query(MetaAdAccount)
                .filter(MetaAdAccount.org_id == self.org_id)
                .first()
            )
        if ad_account:
            # Resolve MetaAdAccount → AdAccount (different tables, different UUIDs)
            # The Creative FK points to ad_accounts.id, not meta_ad_accounts.id
            from backend.src.database.models import AdAccount as LegacyAdAccount
            legacy = (
                self.db.query(LegacyAdAccount)
                .filter(LegacyAdAccount.meta_ad_account_id == ad_account.meta_account_id)
                .first()
            )
            if legacy:
                payload["ad_account_id"] = str(legacy.id)
            else:
                payload["ad_account_id"] = str(ad_account.id)  # fallback

        job_id = enqueue(
            task_name="creatives_generate",
            payload=payload,
            org_id=self.org_id,
            db=self.db,
        )
        step.job_run_id = UUID(job_id)
        step.artifacts_json = {
            "job_run_id": job_id,
            "angle_id": payload["angle_id"],
            "opportunities_used": len(all_opportunities),
            "brain_features_used": len(winning_features),
            "saturated_ads_avoided": len(saturated_ads),
        }
        self.db.commit()

        self._wait_for_job(job_id)

    # ── Step 7: content_studio ───────────────────────────────────────────────

    def _step_content_studio(self, run: FlywheelRun, step: FlywheelStep):
        """Enqueue content_studio_generate with latest creative + opportunity context."""
        # Get org's ad account IDs for scoping
        org_account_ids = [
            a.id for a in self.db.query(MetaAdAccount)
            .filter(MetaAdAccount.org_id == self.org_id)
            .all()
        ]

        # ── Gather opportunity context from previous steps ──
        prev_steps = (
            self.db.query(FlywheelStep)
            .filter(FlywheelStep.flywheel_run_id == run.id)
            .order_by(FlywheelStep.step_order)
            .all()
        )
        step_artifacts = {s.step_name: (s.artifacts_json or {}) for s in prev_steps}
        opp_artifacts = step_artifacts.get("opportunities", {})
        top_opp = opp_artifacts.get("top_opportunity", {}) or {}

        # Try to find the creative generated by the creatives step in this run
        creative = None
        creatives_step = (
            self.db.query(FlywheelStep)
            .filter(FlywheelStep.flywheel_run_id == run.id, FlywheelStep.step_name == "creatives")
            .first()
        )
        if creatives_step and creatives_step.job_run_id:
            # Find creative created by that job
            job = self.db.query(JobRun).filter(JobRun.id == creatives_step.job_run_id).first()
            if job and job.payload_json and job.payload_json.get("result"):
                result = job.payload_json["result"]
                creative_ids = [r.get("id") for r in result if r.get("id")] if isinstance(result, list) else []
                if creative_ids:
                    from uuid import UUID as _UUID
                    try:
                        creative = self.db.query(Creative).filter(Creative.id == _UUID(creative_ids[0])).first()
                    except (ValueError, TypeError):
                        pass

        # Fallback: get BEST scored creative for this org's ad accounts (not just first)
        if not creative and org_account_ids:
            creative = (
                self.db.query(Creative)
                .filter(Creative.ad_account_id.in_(org_account_ids))
                .order_by(Creative.overall_score.desc().nulls_last(), Creative.created_at.desc())
                .first()
            )

        if not creative:
            step.status = "skipped"
            step.artifacts_json = {"reason": "No creatives available for content generation"}
            return

        # Check if there's already a content pack for this creative
        existing_pack = (
            self.db.query(ContentPack)
            .filter(ContentPack.creative_id == creative.id)
            .first()
        )

        if existing_pack:
            step.artifacts_json = {
                "content_pack_id": str(existing_pack.id),
                "creative_id": str(creative.id),
                "note": "Using existing content pack",
            }
            step.status = "succeeded"
            return

        # Create and enqueue new pack
        from backend.src.services.content_creator_service import build_pack_from_creative

        channels = (run.config_json or {}).get("channels", [
            {"channel": "ig_reel", "format": "9x16_30s"},
        ])

        # Pass opportunity context into settings so it flows into the content generation prompt
        settings = {
            "goal": (run.config_json or {}).get("goal", "awareness"),
            "language": (run.config_json or {}).get("language", "es-AR"),
        }
        if top_opp:
            settings["opportunity"] = {
                "title": top_opp.get("title", ""),
                "description": top_opp.get("description", ""),
                "strategy": top_opp.get("strategy", ""),
                "primary_source": top_opp.get("primary_source", ""),
                "priority": top_opp.get("priority", ""),
                "gap_id": top_opp.get("gap_id", ""),
            }

        pack = build_pack_from_creative(
            db=self.db,
            org_id=str(self.org_id),
            creative_id=str(creative.id),
            channels=channels,
            settings=settings,
        )

        job_id = enqueue(
            task_name="content_studio_generate",
            payload={"pack_id": str(pack.id)},
            org_id=self.org_id,
            db=self.db,
        )
        pack.job_run_id = UUID(job_id)
        step.job_run_id = UUID(job_id)
        step.artifacts_json = {
            "job_run_id": job_id,
            "content_pack_id": str(pack.id),
            "creative_id": str(creative.id),
        }
        self.db.commit()

        self._wait_for_job(job_id)

    # ── Step 8: export ───────────────────────────────────────────────────────

    def _step_export(self, run: FlywheelRun, step: FlywheelStep):
        """Summarize all step outputs."""
        steps = (
            self.db.query(FlywheelStep)
            .filter(FlywheelStep.flywheel_run_id == run.id)
            .order_by(FlywheelStep.step_order)
            .all()
        )

        summary = {}
        for s in steps:
            summary[s.step_name] = {
                "status": s.status,
                "artifacts": s.artifacts_json or {},
            }

        step.artifacts_json = {"summary": summary}
        run.outputs_json = summary
        step.status = "succeeded"

    # ── Job polling ──────────────────────────────────────────────────────────

    def _wait_for_job(self, job_run_id: str):
        """Poll job_runs table until the job completes or times out."""
        deadline = time.monotonic() + _POLL_TIMEOUT

        while time.monotonic() < deadline:
            # Refresh session to see updates from other threads/processes
            self.db.expire_all()

            job = self.db.query(JobRun).filter(JobRun.id == UUID(job_run_id)).first()
            if not job:
                raise ValueError(f"JobRun {job_run_id} not found")

            if job.status == JobRunStatus.SUCCEEDED:
                return
            if job.status in (JobRunStatus.FAILED, JobRunStatus.DEAD, JobRunStatus.CANCELED):
                error_msg = job.last_error_message or f"Job {job_run_id} ended with status {job.status.value}"
                raise RuntimeError(error_msg)

            time.sleep(_POLL_INTERVAL)

        raise TimeoutError(f"Job {job_run_id} did not complete within {_POLL_TIMEOUT}s")
