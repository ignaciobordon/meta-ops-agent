"""
Dashboard API - Real KPIs computed from database.
No hardcoded values. All metrics derived from DecisionPack and AdAccount tables.
Multi-tenant: scoped to the authenticated user's organization.
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone

from backend.src.database.session import get_db
from backend.src.database.models import DecisionPack, DecisionState
from backend.src.middleware.auth import get_current_user
from backend.src.utils.tenant import get_org_ad_account_ids

router = APIRouter(tags=["dashboard"])


@router.get("/kpis")
def get_dashboard_kpis(
    days: int = 1,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Get real-time KPIs for the dashboard.
    Scoped to user's organization via ad_account_ids.
    """
    try:
        org_id = user.get("org_id", "")
        org_accounts = get_org_ad_account_ids(org_id, db)

        now = datetime.now(timezone.utc)
        since = now - timedelta(days=days)
        prev_since = since - timedelta(days=days)

        # Base query scoped to org
        base_q = db.query(DecisionPack)
        if org_accounts:
            base_q = base_q.filter(DecisionPack.ad_account_id.in_(org_accounts))
        else:
            # No accounts → no data
            return _empty_kpis(days)

        # ── Pending Approvals ─────────────────────────────────────────────
        pending_count = base_q.filter(
            DecisionPack.state == DecisionState.PENDING_APPROVAL
        ).count()

        # ── Executed Today ────────────────────────────────────────────────
        executed_current = base_q.filter(
            DecisionPack.executed_at >= since,
            DecisionPack.state.in_([DecisionState.EXECUTED, DecisionState.FAILED])
        ).count()

        executed_previous = base_q.filter(
            DecisionPack.executed_at >= prev_since,
            DecisionPack.executed_at < since,
            DecisionPack.state.in_([DecisionState.EXECUTED, DecisionState.FAILED])
        ).count()

        executed_change = executed_current - executed_previous

        # ── Total Decisions (all time) ────────────────────────────────────
        total_decisions = base_q.count()

        # ── Blocked by Policy ─────────────────────────────────────────────
        blocked_count = base_q.filter(
            DecisionPack.state == DecisionState.BLOCKED
        ).count()

        # ── Success Rate (last N days) ────────────────────────────────────
        executed_in_period = base_q.filter(
            DecisionPack.executed_at >= since
        ).all()

        successful = sum(
            1 for d in executed_in_period
            if (d.execution_result or {}).get("success", False)
            and not (d.execution_result or {}).get("dry_run", False)
        )

        dry_runs = sum(
            1 for d in executed_in_period
            if (d.execution_result or {}).get("dry_run", False)
        )

        total_exec = len(executed_in_period)
        success_rate = (successful / total_exec * 100) if total_exec > 0 else 0

        return {
            "kpis": [
                {
                    "label": "Pending Approvals",
                    "value": str(pending_count),
                    "change": None,
                    "trend": None,
                },
                {
                    "label": "Executed Today",
                    "value": str(executed_current),
                    "change": f"+{executed_change}" if executed_change >= 0 else str(executed_change),
                    "trend": "up" if executed_change > 0 else ("down" if executed_change < 0 else None),
                },
                {
                    "label": "Blocked by Policy",
                    "value": str(blocked_count),
                    "change": None,
                    "trend": None,
                },
                {
                    "label": "Dry Runs Today",
                    "value": str(dry_runs),
                    "change": None,
                    "trend": None,
                },
            ],
            "summary": {
                "total_decisions": total_decisions,
                "success_rate": round(success_rate, 1),
                "executed_period": total_exec,
                "successful": successful,
                "dry_runs": dry_runs,
                "period_days": days,
            }
        }

    except Exception as e:
        raise HTTPException(500, f"Failed to load dashboard KPIs: {str(e)}")


def _empty_kpis(days: int) -> dict:
    """Return empty KPIs when org has no ad accounts."""
    return {
        "kpis": [
            {"label": "Pending Approvals", "value": "0", "change": None, "trend": None},
            {"label": "Executed Today", "value": "0", "change": "+0", "trend": None},
            {"label": "Blocked by Policy", "value": "0", "change": None, "trend": None},
            {"label": "Dry Runs Today", "value": "0", "change": None, "trend": None},
        ],
        "summary": {
            "total_decisions": 0, "success_rate": 0, "executed_period": 0,
            "successful": 0, "dry_runs": 0, "period_days": days,
        }
    }
