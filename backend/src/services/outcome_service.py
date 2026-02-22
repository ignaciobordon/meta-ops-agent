"""
Sprint 5 – BLOQUE C: Outcome System
OutcomeCollector — captures before/after metrics for executed decisions.
OutcomeLabeler — rule-based classification of outcomes.
OutcomeScheduler — processes pending after-capture jobs.
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from backend.src.database.models import (
    ActionType,
    DecisionOutcome,
    DecisionPack,
    EntityMemory,
    OutcomeLabel,
    ScheduledJob,
)
from backend.src.providers.provider_factory import MetricsProviderFactory
from src.utils.logging_config import logger


class OutcomeLabeler:
    """Rule-based outcome classification using noise bands from entity memory."""

    def label(
        self,
        outcome: DecisionOutcome,
        entity_memory: Optional[EntityMemory] = None,
    ) -> Tuple[OutcomeLabel, float]:
        before = outcome.before_metrics_json or {}
        after = outcome.after_metrics_json or {}
        delta = outcome.delta_metrics_json or {}

        # No metrics → UNKNOWN
        if not before or not after or not before.get("available", True) is False and not after.get("available", True) is False:
            pass
        if not delta:
            return OutcomeLabel.UNKNOWN, 0.0

        # Get noise bands from entity memory (or defaults)
        volatility = {}
        if entity_memory and entity_memory.volatility_json:
            volatility = entity_memory.volatility_json

        roas_noise = volatility.get("roas", 0.05)
        cpa_noise = volatility.get("cpa", 0.1)
        ctr_noise = volatility.get("ctr", 0.02)

        # Extract deltas (normalized as fractions)
        roas_delta = delta.get("roas", 0.0)
        cpa_delta = delta.get("cpa", 0.0)
        ctr_delta = delta.get("ctr", 0.0)
        spend_delta = delta.get("spend", 0.0)

        # WIN: positive ROAS movement AND CPA not worse (or improving)
        if roas_delta > roas_noise and cpa_delta <= cpa_noise:
            confidence = min(1.0, abs(roas_delta) / max(roas_noise * 3, 0.01))
            return OutcomeLabel.WIN, round(confidence, 4)

        # Also WIN if CTR up significantly and CPA down
        if ctr_delta > ctr_noise * 2 and cpa_delta < 0:
            confidence = min(1.0, abs(ctr_delta) / max(ctr_noise * 3, 0.01))
            return OutcomeLabel.WIN, round(confidence, 4)

        # LOSS: CPA spiked hard OR ROAS dropped hard
        if cpa_delta > cpa_noise * 1.5 or roas_delta < -roas_noise * 1.5:
            confidence = min(1.0, max(abs(cpa_delta) / max(cpa_noise * 3, 0.01),
                                     abs(roas_delta) / max(roas_noise * 3, 0.01)))
            return OutcomeLabel.LOSS, round(confidence, 4)

        # NEUTRAL: within noise band
        return OutcomeLabel.NEUTRAL, 0.5


class OutcomeCollector:
    """Captures before/after metric snapshots for executed decisions."""

    HORIZONS = [60, 1440, 4320]  # 1h, 24h, 72h

    def __init__(self, db: Session):
        self.db = db
        self.labeler = OutcomeLabeler()

    def capture_before(
        self,
        decision: DecisionPack,
        org_id: UUID,
        dry_run: bool = False,
    ) -> List[DecisionOutcome]:
        """Create outcome rows with before_metrics for each horizon."""
        provider = MetricsProviderFactory.get_provider(org_id, self.db)

        snapshot = provider.get_snapshot(
            org_id=org_id,
            entity_type=decision.entity_type or "unknown",
            entity_id=decision.entity_id or "unknown",
        )

        before_json = {
            "provider": snapshot.provider,
            "available": snapshot.available,
            "metrics": snapshot.metrics,
            "timestamp": snapshot.timestamp.isoformat(),
        }

        executed_at = decision.executed_at or datetime.utcnow()
        outcomes = []

        for horizon in self.HORIZONS:
            outcome = DecisionOutcome(
                org_id=org_id,
                decision_id=decision.id,
                entity_type=decision.entity_type or "unknown",
                entity_id=decision.entity_id or "unknown",
                action_type=decision.action_type,
                executed_at=executed_at,
                dry_run=dry_run,
                horizon_minutes=horizon,
                before_metrics_json=before_json,
            )
            self.db.add(outcome)
            self.db.flush()  # Get ID

            # Schedule after-capture job
            job = ScheduledJob(
                org_id=org_id,
                job_type="outcome_capture",
                reference_id=outcome.id,
                scheduled_for=executed_at + timedelta(minutes=horizon),
            )
            self.db.add(job)
            outcomes.append(outcome)

        return outcomes

    def capture_after(self, outcome_id: UUID) -> Optional[DecisionOutcome]:
        """Capture after-metrics, compute delta, label outcome."""
        outcome = self.db.query(DecisionOutcome).filter(
            DecisionOutcome.id == outcome_id
        ).first()

        if not outcome:
            logger.warning(f"OUTCOME_NOT_FOUND | {outcome_id}")
            return None

        # Idempotent: skip if already captured
        if outcome.after_metrics_json and outcome.after_metrics_json.get("metrics"):
            return outcome

        provider = MetricsProviderFactory.get_provider(outcome.org_id, self.db)

        snapshot = provider.get_snapshot(
            org_id=outcome.org_id,
            entity_type=outcome.entity_type,
            entity_id=outcome.entity_id,
        )

        after_json = {
            "provider": snapshot.provider,
            "available": snapshot.available,
            "metrics": snapshot.metrics,
            "timestamp": snapshot.timestamp.isoformat(),
        }

        outcome.after_metrics_json = after_json

        # Compute delta
        before_metrics = (outcome.before_metrics_json or {}).get("metrics", {})
        after_metrics = snapshot.metrics
        delta = {}
        for key in set(list(before_metrics.keys()) + list(after_metrics.keys())):
            before_val = before_metrics.get(key, 0)
            after_val = after_metrics.get(key, 0)
            try:
                delta[key] = round(float(after_val) - float(before_val), 6)
            except (TypeError, ValueError):
                delta[key] = 0.0

        outcome.delta_metrics_json = delta

        # Label outcome
        entity_mem = self.db.query(EntityMemory).filter(
            EntityMemory.org_id == outcome.org_id,
            EntityMemory.entity_type == outcome.entity_type,
            EntityMemory.entity_id == outcome.entity_id,
        ).first()

        label, confidence = self.labeler.label(outcome, entity_mem)
        outcome.outcome_label = label
        outcome.confidence = confidence

        # Update memory (BLOQUE D — imported lazily to avoid circular)
        if label != OutcomeLabel.UNKNOWN:
            try:
                from backend.src.services.memory_service import MemoryUpdater
                MemoryUpdater(self.db).update_from_outcome(outcome)
            except Exception as e:
                logger.warning(f"MEMORY_UPDATE_FAILED | {outcome.id} | {e}")

        return outcome


class OutcomeScheduler:
    """Processes pending outcome capture jobs."""

    def __init__(self, db: Session):
        self.db = db
        self.collector = OutcomeCollector(db)

    def process_pending(self, limit: int = 50) -> List[Dict]:
        """Process scheduled outcome captures that are due."""
        now = datetime.utcnow()

        jobs = self.db.query(ScheduledJob).filter(
            ScheduledJob.job_type == "outcome_capture",
            ScheduledJob.scheduled_for <= now,
            ScheduledJob.completed_at.is_(None),
        ).order_by(ScheduledJob.scheduled_for).limit(limit).all()

        results = []
        for job in jobs:
            try:
                outcome = self.collector.capture_after(job.reference_id)
                job.completed_at = datetime.utcnow()

                results.append({
                    "job_id": str(job.id),
                    "outcome_id": str(job.reference_id),
                    "label": outcome.outcome_label.value if outcome else "not_found",
                    "status": "completed",
                })
            except Exception as e:
                logger.error(f"OUTCOME_JOB_FAILED | job_id={job.id} | {e}")
                results.append({
                    "job_id": str(job.id),
                    "outcome_id": str(job.reference_id),
                    "status": "failed",
                    "error": str(e),
                })

        self.db.commit()
        return results
