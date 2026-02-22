"""
Sprint 6 – BLOQUE G (P1-A): Rule-Based Insight Engine
Analyzes recent insights data to generate actionable signals/alerts.
Uses entity_memory baselines when available, falls back to rolling averages.
"""
from datetime import datetime, timedelta
from typing import Dict, List
from uuid import UUID

from sqlalchemy.orm import Session

from backend.src.database.models import (
    AlertSeverity,
    EntityMemory,
    InsightLevel,
    MetaAdAccount,
    MetaAlert,
    MetaInsightsDaily,
)
from src.utils.logging_config import logger


class InsightEngine:
    """Rule-based insight engine for detecting performance anomalies."""

    # Default thresholds
    CTR_LOW_THRESHOLD = 0.5  # % — below this is concerning
    CPA_HIGH_MULTIPLIER = 1.5  # CPA > 1.5x baseline → alert
    ROAS_LOW_THRESHOLD = 1.0  # ROAS below 1.0 → losing money
    FREQUENCY_HIGH = 3.0  # Frequency above this → fatigue risk
    SPEND_SPIKE_MULTIPLIER = 2.0  # Spend > 2x avg → spike

    # Suggested actions per alert type
    SUGGESTED_ACTIONS = {
        "ctr_low": [
            "Refresh creative with new angle or visual",
            "Review audience targeting — may be too broad",
            "A/B test different ad copy variants",
        ],
        "cpa_high": [
            "Lower daily budget to reduce exposure",
            "Narrow targeting to higher-intent audiences",
            "Pause and reallocate budget to better performers",
        ],
        "roas_low": [
            "Review conversion tracking setup",
            "Shift budget to campaigns with ROAS > 1.5x",
            "Test higher-value audience segments",
        ],
        "frequency_decay": [
            "Rotate creative — audience is fatigued",
            "Expand audience to reduce overlap",
            "Pause and launch with fresh creative",
        ],
        "spend_spike_no_conv": [
            "Pause immediately — spending without results",
            "Check if conversion pixel is firing correctly",
            "Review budget caps and bid strategy",
        ],
    }

    def __init__(self, db: Session):
        self.db = db

    def analyze(self, org_id: UUID, ad_account_id: UUID, days: int = 7) -> Dict:
        """Analyze recent insights and generate alerts."""
        since = datetime.utcnow() - timedelta(days=days)
        alerts_created = 0

        meta_account = self.db.query(MetaAdAccount).filter(
            MetaAdAccount.id == ad_account_id,
            MetaAdAccount.org_id == org_id,
        ).first()

        if not meta_account:
            return {"status": "no_account", "alerts": 0}

        # Get recent insights grouped by entity
        insights = self.db.query(MetaInsightsDaily).filter(
            MetaInsightsDaily.org_id == org_id,
            MetaInsightsDaily.ad_account_id == ad_account_id,
            MetaInsightsDaily.date_start >= since,
        ).order_by(MetaInsightsDaily.entity_meta_id, MetaInsightsDaily.date_start).all()

        if not insights:
            return {"status": "no_data", "alerts": 0}

        # Group by entity
        entity_data: Dict[str, List[MetaInsightsDaily]] = {}
        for row in insights:
            key = f"{row.level.value}:{row.entity_meta_id}"
            entity_data.setdefault(key, []).append(row)

        for key, rows in entity_data.items():
            level_str, entity_id = key.split(":", 1)

            # Get entity memory baseline if available
            entity_mem = self.db.query(EntityMemory).filter(
                EntityMemory.org_id == org_id,
                EntityMemory.entity_type == level_str,
                EntityMemory.entity_id == entity_id,
            ).first()

            baseline = (entity_mem.baseline_ema_json or {}) if entity_mem else {}

            # Compute rolling averages from recent data
            avg_spend = sum(r.spend or 0 for r in rows) / len(rows)
            avg_ctr = sum(r.ctr or 0 for r in rows) / len(rows)
            avg_cpm = sum(r.cpm or 0 for r in rows) / len(rows)
            total_conversions = sum(r.conversions or 0 for r in rows)
            total_spend = sum(r.spend or 0 for r in rows)
            avg_frequency = sum(r.frequency or 0 for r in rows) / len(rows)
            cpa = total_spend / total_conversions if total_conversions > 0 else None

            latest = rows[-1]

            # Rule 1: CTR low vs baseline
            ctr_baseline = baseline.get("ctr", self.CTR_LOW_THRESHOLD)
            if latest.ctr is not None and latest.ctr < ctr_baseline * 0.7:
                self._create_alert(
                    org_id, ad_account_id, "ctr_low", AlertSeverity.HIGH,
                    f"CTR dropped to {latest.ctr:.2f}% (baseline: {ctr_baseline:.2f}%)",
                    level_str, entity_id,
                    {"current_ctr": latest.ctr, "baseline_ctr": ctr_baseline},
                )
                alerts_created += 1

            # Rule 2: CPA high
            cpa_baseline = baseline.get("cpa")
            if cpa is not None and cpa_baseline and cpa > cpa_baseline * self.CPA_HIGH_MULTIPLIER:
                self._create_alert(
                    org_id, ad_account_id, "cpa_high", AlertSeverity.HIGH,
                    f"CPA spiked to ${cpa:.2f} ({self.CPA_HIGH_MULTIPLIER}x baseline ${cpa_baseline:.2f})",
                    level_str, entity_id,
                    {"current_cpa": cpa, "baseline_cpa": cpa_baseline},
                )
                alerts_created += 1

            # Rule 3: ROAS low
            if latest.purchase_roas is not None and latest.purchase_roas < self.ROAS_LOW_THRESHOLD:
                self._create_alert(
                    org_id, ad_account_id, "roas_low", AlertSeverity.MEDIUM,
                    f"ROAS below break-even at {latest.purchase_roas:.2f}x",
                    level_str, entity_id,
                    {"current_roas": latest.purchase_roas},
                )
                alerts_created += 1

            # Rule 4: Frequency high + CTR decay
            if avg_frequency > self.FREQUENCY_HIGH and len(rows) >= 3:
                ctr_trend = (rows[-1].ctr or 0) - (rows[0].ctr or 0)
                if ctr_trend < 0:
                    self._create_alert(
                        org_id, ad_account_id, "frequency_decay", AlertSeverity.MEDIUM,
                        f"High frequency ({avg_frequency:.1f}) with declining CTR ({ctr_trend:+.2f}%)",
                        level_str, entity_id,
                        {"frequency": avg_frequency, "ctr_trend": ctr_trend},
                    )
                    alerts_created += 1

            # Rule 5: Spend spike without conversions
            if latest.spend and avg_spend > 0 and latest.spend > avg_spend * self.SPEND_SPIKE_MULTIPLIER:
                if (latest.conversions or 0) == 0:
                    self._create_alert(
                        org_id, ad_account_id, "spend_spike_no_conv", AlertSeverity.CRITICAL,
                        f"Spend spiked to ${latest.spend:.2f} (avg ${avg_spend:.2f}) with 0 conversions",
                        level_str, entity_id,
                        {"current_spend": latest.spend, "avg_spend": avg_spend},
                    )
                    alerts_created += 1

        logger.info(
            "INSIGHT_ENGINE_DONE | org={} | acc={} | entities={} | alerts={}",
            org_id, ad_account_id, len(entity_data), alerts_created,
        )
        return {"status": "success", "alerts": alerts_created, "entities_analyzed": len(entity_data)}

    def _create_alert(
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
        # Deduplicate: don't create if same alert type+entity exists in last 24h
        recent = self.db.query(MetaAlert).filter(
            MetaAlert.org_id == org_id,
            MetaAlert.alert_type == alert_type,
            MetaAlert.entity_meta_id == entity_meta_id,
            MetaAlert.resolved_at.is_(None),
            MetaAlert.detected_at >= datetime.utcnow() - timedelta(hours=24),
        ).first()

        if recent:
            return

        # Enrich payload with suggested actions for this alert type
        payload["suggested_actions"] = self.SUGGESTED_ACTIONS.get(alert_type, [])

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
