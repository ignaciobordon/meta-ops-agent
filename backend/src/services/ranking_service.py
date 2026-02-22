"""
Sprint 5 – BLOQUE E: Decision Ranking Engine
Scores and ranks pending decisions by: Total = Impact * Confidence * Freshness - Risk
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from backend.src.database.models import (
    DecisionOutcome,
    DecisionPack,
    DecisionRanking,
    DecisionState,
    EntityMemory,
    FeatureMemory,
    FeatureType,
)
from src.utils.logging_config import logger


class DecisionRanker:
    """Scores and ranks decisions for the approval queue."""

    def rank_decisions(
        self,
        org_id: UUID,
        decisions: List[DecisionPack],
        db: Session,
    ) -> List[DecisionRanking]:
        """Score each decision, sort by total desc, upsert DecisionRanking rows."""
        rankings = []
        for decision in decisions:
            ranking = self._score_decision(org_id, decision, db)
            rankings.append(ranking)

        # Sort by score_total descending
        rankings.sort(key=lambda r: r.score_total, reverse=True)
        db.commit()
        return rankings

    def _score_decision(
        self,
        org_id: UUID,
        decision: DecisionPack,
        db: Session,
    ) -> DecisionRanking:
        """Compute Impact * Confidence * Freshness - Risk for a decision."""
        impact = self._compute_impact(org_id, decision, db)
        confidence = self._compute_confidence(org_id, decision, db)
        freshness = self._compute_freshness(org_id, decision, db)
        risk = self._compute_risk(decision)

        total = max(0.0, impact * confidence * freshness - risk)

        explanation = {
            "impact": f"{impact:.3f} — win_rate for {decision.action_type}",
            "confidence": f"{confidence:.3f} — trust * samples factor",
            "freshness": f"{freshness:.3f} — recency penalty for similar actions",
            "risk": f"{risk:.3f} — policy violations + volatility",
            "formula": "Total = Impact * Confidence * Freshness - Risk",
        }

        # Upsert ranking
        existing = db.query(DecisionRanking).filter(
            DecisionRanking.decision_id == decision.id
        ).first()

        if existing:
            existing.score_total = round(total, 4)
            existing.score_impact = round(impact, 4)
            existing.score_confidence = round(confidence, 4)
            existing.score_freshness = round(freshness, 4)
            existing.score_risk = round(risk, 4)
            existing.rank_version = (existing.rank_version or 0) + 1
            existing.explanation_json = explanation
            existing.updated_at = datetime.utcnow()
            return existing
        else:
            ranking = DecisionRanking(
                decision_id=decision.id,
                org_id=org_id,
                score_total=round(total, 4),
                score_impact=round(impact, 4),
                score_confidence=round(confidence, 4),
                score_freshness=round(freshness, 4),
                score_risk=round(risk, 4),
                explanation_json=explanation,
            )
            db.add(ranking)
            return ranking

    def _compute_impact(
        self,
        org_id: UUID,
        decision: DecisionPack,
        db: Session,
    ) -> float:
        """Impact 0-1: from feature_memory win_rate for this action_type."""
        action_key = decision.action_type.value if hasattr(decision.action_type, 'value') else str(decision.action_type)

        feature = db.query(FeatureMemory).filter(
            FeatureMemory.org_id == org_id,
            FeatureMemory.feature_type == FeatureType.ACTION_TYPE,
            FeatureMemory.feature_key == action_key,
        ).first()

        if feature and feature.samples >= 1:
            # win_rate is already 0-1, boost slightly for exploration (low samples)
            exploration_bonus = max(0.0, 0.1 * (1 - min(feature.samples, 10) / 10))
            return min(1.0, feature.win_rate + exploration_bonus)

        # No data: neutral impact with exploration bonus
        return 0.4

    def _compute_confidence(
        self,
        org_id: UUID,
        decision: DecisionPack,
        db: Session,
    ) -> float:
        """Confidence 0-1: trust_score * 0.6 + sample_factor * 0.4."""
        entity_mem = db.query(EntityMemory).filter(
            EntityMemory.org_id == org_id,
            EntityMemory.entity_type == decision.entity_type,
            EntityMemory.entity_id == decision.entity_id,
        ).first()

        trust_factor = (entity_mem.trust_score / 100.0) if entity_mem else 0.5

        action_key = decision.action_type.value if hasattr(decision.action_type, 'value') else str(decision.action_type)
        feature = db.query(FeatureMemory).filter(
            FeatureMemory.org_id == org_id,
            FeatureMemory.feature_type == FeatureType.ACTION_TYPE,
            FeatureMemory.feature_key == action_key,
        ).first()

        # Saturates at 20 samples
        sample_factor = min(1.0, (feature.samples / 20.0)) if feature else 0.1

        return trust_factor * 0.6 + sample_factor * 0.4

    def _compute_freshness(
        self,
        org_id: UUID,
        decision: DecisionPack,
        db: Session,
    ) -> float:
        """Freshness 0.2-1.0: penalizes recent similar actions on same entity."""
        cutoff = datetime.utcnow() - timedelta(hours=48)

        recent_count = db.query(DecisionOutcome).filter(
            DecisionOutcome.org_id == org_id,
            DecisionOutcome.entity_id == decision.entity_id,
            DecisionOutcome.action_type == decision.action_type,
            DecisionOutcome.executed_at >= cutoff,
        ).count()

        # -0.3 per action in last 48h, floor at 0.2
        return max(0.2, 1.0 - 0.3 * recent_count)

    def _compute_risk(self, decision: DecisionPack) -> float:
        """Risk 0-1: from policy violations + volatility signals."""
        risk = 0.0
        policy_checks = decision.policy_checks or []

        for check in policy_checks:
            if not check.get("passed", True):
                severity = check.get("severity", "warning")
                if severity == "blocking":
                    risk += 0.3
                elif severity == "warning":
                    risk += 0.1

        # Base risk from risk_score field
        if decision.risk_score and decision.risk_score > 0:
            risk += min(0.2, decision.risk_score / 10.0)

        return min(1.0, risk)
