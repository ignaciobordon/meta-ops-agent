"""
Audit API - Exposes CP7 (Operator) execution logs from REAL data.
No mock emails or fake stats. User emails from DB join.
Stats calculated from execution_result JSON field.
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone

from backend.src.database.session import get_db
from backend.src.database.models import AuditEntry, DecisionPack, DecisionState, User
from backend.src.middleware.auth import get_current_user
from backend.src.utils.tenant import get_org_ad_account_ids
from src.utils.logging_config import set_trace_id
from uuid import UUID, uuid4

router = APIRouter(tags=["audit"])


# Response Models
class AuditEntryResponse(BaseModel):
    id: str
    timestamp: str
    user_email: str
    action_type: str
    entity_type: str
    entity_id: str
    status: str  # "success", "failed", "dry_run"
    changes: Dict[str, Any]
    trace_id: str
    error_message: str | None


@router.get("/", response_model=List[AuditEntryResponse])
def list_audit_entries(
    limit: int = 50,
    status: str = None,
    action_type: str = None,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    List execution audit log from CP7 Operator.
    Scoped to user's organization. User emails resolved from REAL User table join.
    """
    trace_id = f"audit-{uuid4().hex[:12]}"
    set_trace_id(trace_id)

    try:
        org_id = user.get("org_id", "")
        org_accounts = get_org_ad_account_ids(org_id, db)

        # Query executed decisions scoped to org
        query = db.query(DecisionPack).filter(
            DecisionPack.executed_at.isnot(None)
        )
        if org_accounts:
            query = query.filter(DecisionPack.ad_account_id.in_(org_accounts))
        else:
            return []

        if action_type:
            from backend.src.database.models import ActionType
            query = query.filter(DecisionPack.action_type == ActionType(action_type))

        decisions = query.order_by(DecisionPack.executed_at.desc()).limit(limit).all()

        entries = []
        for d in decisions:
            # Determine status from execution_result
            exec_result = d.execution_result or {}
            if exec_result.get("dry_run", False):
                entry_status = "dry_run"
            elif exec_result.get("success", False):
                entry_status = "success"
            else:
                entry_status = "failed"

            # Filter by status if requested
            if status and entry_status != status:
                continue

            # Resolve user email from REAL User table
            user_email = "system"
            if d.created_by_user_id:
                user = db.query(User).filter(User.id == d.created_by_user_id).first()
                if user:
                    user_email = user.email

            # Extract changes
            changes = {
                "from": d.before_snapshot,
                "to": d.after_proposal,
            }

            entries.append(AuditEntryResponse(
                id=str(d.id),
                timestamp=d.executed_at.isoformat() if d.executed_at else d.created_at.isoformat(),
                user_email=user_email,
                action_type=d.action_type.value,
                entity_type=d.entity_type,
                entity_id=d.entity_id,
                status=entry_status,
                changes=changes,
                trace_id=d.trace_id,
                error_message=exec_result.get("error_message") or exec_result.get("error")
            ))

        return entries

    except Exception as e:
        raise HTTPException(500, f"Failed to load audit log: {str(e)}")


@router.get("/stats/summary")
def get_audit_stats(
    days: int = 7,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Get audit statistics for the last N days.
    Scoped to user's organization. REAL calculations from execution_result JSON field.
    """
    trace_id = f"audit-{uuid4().hex[:12]}"
    set_trace_id(trace_id)

    try:
        org_id = user.get("org_id", "")
        org_accounts = get_org_ad_account_ids(org_id, db)

        if not org_accounts:
            return {
                "total_executions": 0, "successful": 0,
                "failed": 0, "dry_run": 0, "period_days": days,
            }

        since = datetime.now(timezone.utc) - timedelta(days=days)

        # Get all executed decisions in period scoped to org
        executed_decisions = db.query(DecisionPack).filter(
            DecisionPack.executed_at >= since,
            DecisionPack.ad_account_id.in_(org_accounts),
        ).all()

        # Calculate REAL stats from execution_result
        successful = 0
        failed = 0
        dry_run = 0

        for d in executed_decisions:
            exec_result = d.execution_result or {}
            if exec_result.get("dry_run", False):
                dry_run += 1
            elif exec_result.get("success", False):
                successful += 1
            else:
                failed += 1

        return {
            "total_executions": len(executed_decisions),
            "successful": successful,
            "failed": failed,
            "dry_run": dry_run,
            "period_days": days,
        }

    except Exception as e:
        raise HTTPException(500, f"Failed to get audit stats: {str(e)}")


@router.get("/{entry_id}", response_model=AuditEntryResponse)
def get_audit_entry(
    entry_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Get details for a specific audit entry.
    Scoped to user's organization. User email resolved from REAL User table.
    """
    trace_id = f"audit-{uuid4().hex[:12]}"
    set_trace_id(trace_id)

    try:
        org_id = user.get("org_id", "")
        org_accounts = get_org_ad_account_ids(org_id, db)

        decision = db.query(DecisionPack).filter(
            DecisionPack.id == UUID(entry_id)
        ).first()

        if not decision:
            raise HTTPException(404, "Audit entry not found")

        # Enforce org isolation
        if org_accounts and decision.ad_account_id not in org_accounts:
            raise HTTPException(404, "Audit entry not found")

        # Determine status
        exec_result = decision.execution_result or {}
        if exec_result.get("dry_run", False):
            entry_status = "dry_run"
        elif exec_result.get("success", False):
            entry_status = "success"
        else:
            entry_status = "failed"

        # Resolve user email from REAL User table
        user_email = "system"
        if decision.created_by_user_id:
            user = db.query(User).filter(User.id == decision.created_by_user_id).first()
            if user:
                user_email = user.email

        return AuditEntryResponse(
            id=str(decision.id),
            timestamp=decision.executed_at.isoformat() if decision.executed_at else decision.created_at.isoformat(),
            user_email=user_email,
            action_type=decision.action_type.value,
            entity_type=decision.entity_type,
            entity_id=decision.entity_id,
            status=entry_status,
            changes={
                "from": decision.before_snapshot,
                "to": decision.after_proposal,
            },
            trace_id=decision.trace_id,
            error_message=exec_result.get("error_message") or exec_result.get("error")
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to get audit entry: {str(e)}")
