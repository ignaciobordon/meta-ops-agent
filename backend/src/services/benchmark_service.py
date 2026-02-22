"""Sprint 8 — Benchmark service: org vs own 30-day baseline."""
from datetime import datetime, timedelta
from typing import List
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.src.database.models import (
    InsightLevel,
    MetaInsightsDaily,
    OrgBenchmark,
)

BENCHMARK_METRICS = ["spend", "ctr", "cpc", "cpm", "frequency"]


def compute_benchmarks(
    db: Session,
    org_id: UUID,
    ad_account_id: UUID,
    period_days: int = 30,
) -> List[OrgBenchmark]:
    """Compute benchmarks: compare last 7 days avg vs 30-day baseline."""
    now = datetime.utcnow()
    baseline_start = now - timedelta(days=period_days)
    recent_start = now - timedelta(days=7)

    def _avg_metric(since: datetime, metric_col):
        result = db.query(func.avg(metric_col)).filter(
            MetaInsightsDaily.org_id == org_id,
            MetaInsightsDaily.ad_account_id == ad_account_id,
            MetaInsightsDaily.level == InsightLevel.CAMPAIGN,
            MetaInsightsDaily.date_start >= since,
            metric_col.isnot(None),
        ).scalar()
        return float(result) if result is not None else 0.0

    benchmarks = []
    metric_columns = {
        "spend": MetaInsightsDaily.spend,
        "ctr": MetaInsightsDaily.ctr,
        "cpc": MetaInsightsDaily.cpc,
        "cpm": MetaInsightsDaily.cpm,
        "frequency": MetaInsightsDaily.frequency,
    }

    for metric_name, col in metric_columns.items():
        baseline_val = _avg_metric(baseline_start, col)
        current_val = _avg_metric(recent_start, col)
        delta_pct = ((current_val - baseline_val) / baseline_val * 100) if baseline_val > 0 else 0.0

        # Upsert benchmark row
        existing = db.query(OrgBenchmark).filter(
            OrgBenchmark.org_id == org_id,
            OrgBenchmark.ad_account_id == ad_account_id,
            OrgBenchmark.metric_name == metric_name,
        ).first()

        if existing:
            existing.baseline_value = round(baseline_val, 4)
            existing.current_value = round(current_val, 4)
            existing.delta_pct = round(delta_pct, 2)
            existing.period_days = period_days
            existing.computed_at = now
            benchmarks.append(existing)
        else:
            bm = OrgBenchmark(
                org_id=org_id,
                ad_account_id=ad_account_id,
                metric_name=metric_name,
                baseline_value=round(baseline_val, 4),
                current_value=round(current_val, 4),
                delta_pct=round(delta_pct, 2),
                period_days=period_days,
                computed_at=now,
            )
            db.add(bm)
            benchmarks.append(bm)

    db.flush()
    return benchmarks


def get_benchmarks(db: Session, org_id: UUID) -> List[dict]:
    """Get all benchmarks for an org."""
    rows = db.query(OrgBenchmark).filter(OrgBenchmark.org_id == org_id).all()
    return [
        {
            "metric_name": b.metric_name,
            "baseline_value": b.baseline_value,
            "current_value": b.current_value,
            "delta_pct": b.delta_pct,
            "period_days": b.period_days,
            "computed_at": b.computed_at.isoformat() if b.computed_at else None,
        }
        for b in rows
    ]
