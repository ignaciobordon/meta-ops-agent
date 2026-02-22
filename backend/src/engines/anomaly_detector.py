"""
Sprint 6 – BLOQUE G (P1-B): Anomaly Detector
Robust z-score using MAD (Median Absolute Deviation).
Coherent with Sprint 5 volatility tracking.
"""
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from backend.src.database.models import (
    AlertSeverity,
    InsightLevel,
    MetaAdAccount,
    MetaAlert,
    MetaInsightsDaily,
)
from src.utils.logging_config import logger


class AnomalyDetector:
    """Detects metric anomalies using robust z-scores (MAD-based)."""

    # Modified z-score thresholds
    Z_CRITICAL = 3.5
    Z_HIGH = 2.5
    Z_MEDIUM = 2.0
    MIN_SAMPLES = 5  # Need at least 5 days of data

    # Metrics to monitor
    MONITORED_METRICS = ["spend", "ctr", "cpm", "cpc", "frequency"]

    def __init__(self, db: Session):
        self.db = db

    def detect(self, org_id: UUID, ad_account_id: UUID, days: int = 30) -> Dict:
        """Run anomaly detection across all entities for an ad account."""
        since = datetime.utcnow() - timedelta(days=days)
        anomalies_found = 0

        meta_account = self.db.query(MetaAdAccount).filter(
            MetaAdAccount.id == ad_account_id,
            MetaAdAccount.org_id == org_id,
        ).first()

        if not meta_account:
            return {"status": "no_account", "anomalies": 0}

        insights = self.db.query(MetaInsightsDaily).filter(
            MetaInsightsDaily.org_id == org_id,
            MetaInsightsDaily.ad_account_id == ad_account_id,
            MetaInsightsDaily.date_start >= since,
        ).order_by(MetaInsightsDaily.entity_meta_id, MetaInsightsDaily.date_start).all()

        if not insights:
            return {"status": "no_data", "anomalies": 0}

        # Group by entity
        entity_data: Dict[str, List[MetaInsightsDaily]] = {}
        for row in insights:
            key = f"{row.level.value}:{row.entity_meta_id}"
            entity_data.setdefault(key, []).append(row)

        for key, rows in entity_data.items():
            if len(rows) < self.MIN_SAMPLES:
                continue

            level_str, entity_id = key.split(":", 1)
            latest = rows[-1]

            for metric in self.MONITORED_METRICS:
                values = [getattr(r, metric) or 0.0 for r in rows]
                latest_val = getattr(latest, metric) or 0.0

                z_score = self._robust_z_score(values, latest_val)
                if z_score is None:
                    continue

                severity = self._z_to_severity(abs(z_score))
                if severity is None:
                    continue

                direction = "spike" if z_score > 0 else "drop"
                median_val = statistics.median(values)

                self._create_anomaly_alert(
                    org_id, ad_account_id,
                    f"anomaly_{metric}_{direction}",
                    severity,
                    f"{metric.upper()} {direction}: {latest_val:.2f} (median: {median_val:.2f}, z-score: {z_score:.1f})",
                    level_str, entity_id,
                    {
                        "metric": metric,
                        "current_value": latest_val,
                        "median": median_val,
                        "z_score": round(z_score, 2),
                        "direction": direction,
                    },
                )
                anomalies_found += 1

        logger.info(
            "ANOMALY_DETECTOR_DONE | org={} | acc={} | anomalies={}",
            org_id, ad_account_id, anomalies_found,
        )
        return {"status": "success", "anomalies": anomalies_found}

    def _robust_z_score(self, values: List[float], current: float) -> Optional[float]:
        """
        Compute modified z-score using MAD (Median Absolute Deviation).
        More robust than standard z-score against outliers.
        """
        if len(values) < self.MIN_SAMPLES:
            return None

        median = statistics.median(values)
        mad = statistics.median([abs(v - median) for v in values])

        if mad == 0:
            # All values are the same; use std deviation fallback
            if len(set(values)) == 1:
                return 0.0 if current == median else None
            std = statistics.stdev(values)
            if std == 0:
                return None
            return (current - statistics.mean(values)) / std

        # Modified z-score: 0.6745 is the 0.75th quartile of the standard normal
        return 0.6745 * (current - median) / mad

    def _z_to_severity(self, abs_z: float) -> Optional[AlertSeverity]:
        """Convert absolute z-score to alert severity."""
        if abs_z >= self.Z_CRITICAL:
            return AlertSeverity.CRITICAL
        if abs_z >= self.Z_HIGH:
            return AlertSeverity.HIGH
        if abs_z >= self.Z_MEDIUM:
            return AlertSeverity.MEDIUM
        return None  # Below threshold

    def _create_anomaly_alert(
        self,
        org_id: UUID,
        ad_account_id: UUID,
        alert_type: str,
        severity: AlertSeverity,
        message: str,
        entity_type: str,
        entity_meta_id: str,
        payload: Dict,
    ):
        # Deduplicate: same alert type+entity+metric in last 24h
        recent = self.db.query(MetaAlert).filter(
            MetaAlert.org_id == org_id,
            MetaAlert.alert_type == alert_type,
            MetaAlert.entity_meta_id == entity_meta_id,
            MetaAlert.resolved_at.is_(None),
            MetaAlert.detected_at >= datetime.utcnow() - timedelta(hours=24),
        ).first()

        if recent:
            return

        alert = MetaAlert(
            org_id=org_id,
            ad_account_id=ad_account_id,
            alert_type=alert_type,
            severity=severity,
            message=message,
            entity_type=entity_type,
            entity_meta_id=entity_meta_id,
            payload_json=payload,
        )
        self.db.add(alert)
