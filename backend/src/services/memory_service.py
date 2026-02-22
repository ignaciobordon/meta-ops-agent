"""
Sprint 5 – BLOQUE D: MemoryUpdater
Updates entity memory (EMA baselines, volatility, trust) and feature memory
(win_rate, avg_delta) from outcome episodes.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from backend.src.database.models import (
    Creative,
    DecisionOutcome,
    EntityMemory,
    FeatureMemory,
    FeatureType,
    OutcomeLabel,
)
from src.utils.logging_config import logger


class MemoryUpdater:
    """Accumulates learning from outcome episodes into entity + feature memory."""

    EMA_ALPHA = 0.3  # Smoothing factor for exponential moving average
    TRUST_WIN = 5
    TRUST_NEUTRAL = 1
    TRUST_LOSS = -10

    def __init__(self, db: Session):
        self.db = db

    def update_from_outcome(self, outcome: DecisionOutcome) -> None:
        """Update entity and feature memory from a labeled outcome."""
        if outcome.outcome_label == OutcomeLabel.UNKNOWN:
            return

        self._update_entity_memory(outcome)
        self._update_feature_memory(outcome)

    def _update_entity_memory(self, outcome: DecisionOutcome) -> None:
        """Upsert entity memory with EMA, volatility, and trust updates."""
        mem = self.db.query(EntityMemory).filter(
            EntityMemory.org_id == outcome.org_id,
            EntityMemory.entity_type == outcome.entity_type,
            EntityMemory.entity_id == outcome.entity_id,
        ).first()

        if not mem:
            mem = EntityMemory(
                org_id=outcome.org_id,
                entity_type=outcome.entity_type,
                entity_id=outcome.entity_id,
                baseline_ema_json={},
                volatility_json={},
                trust_score=50.0,
            )
            self.db.add(mem)

        # Update EMA baselines from after_metrics
        after_metrics = (outcome.after_metrics_json or {}).get("metrics", {})
        old_ema = mem.baseline_ema_json or {}
        old_vol = mem.volatility_json or {}
        new_ema = {}
        new_vol = {}

        for key, value in after_metrics.items():
            try:
                val = float(value)
            except (TypeError, ValueError):
                continue

            if key in old_ema:
                # EMA: new = alpha * value + (1 - alpha) * old
                ema = self.EMA_ALPHA * val + (1 - self.EMA_ALPHA) * float(old_ema[key])
                # Volatility (rolling MAD): alpha * |value - ema| + (1-alpha) * old_vol
                deviation = abs(val - ema)
                vol = self.EMA_ALPHA * deviation + (1 - self.EMA_ALPHA) * float(old_vol.get(key, deviation))
            else:
                # First observation: EMA = value, volatility = 0
                ema = val
                vol = 0.0

            new_ema[key] = round(ema, 6)
            new_vol[key] = round(vol, 6)

        mem.baseline_ema_json = new_ema
        mem.volatility_json = new_vol

        # Update trust score
        if outcome.outcome_label == OutcomeLabel.WIN:
            mem.trust_score = min(100.0, mem.trust_score + self.TRUST_WIN)
        elif outcome.outcome_label == OutcomeLabel.NEUTRAL:
            mem.trust_score = min(100.0, mem.trust_score + self.TRUST_NEUTRAL)
        elif outcome.outcome_label == OutcomeLabel.LOSS:
            mem.trust_score = max(0.0, mem.trust_score + self.TRUST_LOSS)

        mem.last_outcome_label = outcome.outcome_label
        mem.last_seen_at = datetime.utcnow()

    def _update_feature_memory(self, outcome: DecisionOutcome) -> None:
        """Update feature memory by action_type and creative tags."""
        is_win = 1.0 if outcome.outcome_label == OutcomeLabel.WIN else 0.0
        delta = outcome.delta_metrics_json or {}

        # Always update by action_type
        self._upsert_feature(
            org_id=outcome.org_id,
            feature_type=FeatureType.ACTION_TYPE,
            feature_key=outcome.action_type.value if hasattr(outcome.action_type, 'value') else str(outcome.action_type),
            is_win=is_win,
            delta=delta,
        )

        # Update by creative tags if available
        creative = self.db.query(Creative).filter(
            Creative.meta_ad_id == outcome.entity_id,
        ).first()

        if creative and creative.tags:
            for tag_obj in creative.tags:
                tag_key = None
                if isinstance(tag_obj, dict):
                    tag_key = tag_obj.get("l1") or tag_obj.get("tag")
                elif isinstance(tag_obj, str):
                    tag_key = tag_obj

                if tag_key:
                    self._upsert_feature(
                        org_id=outcome.org_id,
                        feature_type=FeatureType.TAG,
                        feature_key=tag_key,
                        is_win=is_win,
                        delta=delta,
                    )

    def _upsert_feature(
        self,
        org_id: UUID,
        feature_type: FeatureType,
        feature_key: str,
        is_win: float,
        delta: dict,
    ) -> None:
        """Upsert a feature memory record with running averages."""
        mem = self.db.query(FeatureMemory).filter(
            FeatureMemory.org_id == org_id,
            FeatureMemory.feature_type == feature_type,
            FeatureMemory.feature_key == feature_key,
        ).first()

        if not mem:
            mem = FeatureMemory(
                org_id=org_id,
                feature_type=feature_type,
                feature_key=feature_key,
                win_rate=is_win,
                avg_delta_json=delta,
                samples=1,
            )
            self.db.add(mem)
            return

        # Running average for win_rate
        old_samples = mem.samples or 0
        new_samples = old_samples + 1
        mem.win_rate = round((mem.win_rate * old_samples + is_win) / new_samples, 6)
        mem.samples = new_samples

        # Running average for delta metrics
        old_delta = mem.avg_delta_json or {}
        new_delta = {}
        all_keys = set(list(old_delta.keys()) + list(delta.keys()))
        for key in all_keys:
            old_val = float(old_delta.get(key, 0))
            new_val = float(delta.get(key, 0))
            new_delta[key] = round((old_val * old_samples + new_val) / new_samples, 6)
        mem.avg_delta_json = new_delta
