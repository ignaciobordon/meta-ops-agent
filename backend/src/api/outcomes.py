"""
Sprint 5 – BLOQUE C: Outcomes API
Internal endpoint for processing pending outcome jobs + decision outcomes listing.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.src.database.models import DecisionOutcome, DecisionPack
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user, require_admin
from backend.src.services.outcome_service import OutcomeScheduler
from backend.src.utils.tenant import get_org_ad_account_ids

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────


class OutcomeResponse(BaseModel):
    id: UUID
    decision_id: UUID
    entity_type: str
    entity_id: str
    action_type: str
    horizon_minutes: int
    dry_run: bool
    outcome_label: Optional[str] = None
    confidence: float = 0.0
    before_metrics_json: Optional[Dict[str, Any]] = None
    after_metrics_json: Optional[Dict[str, Any]] = None
    delta_metrics_json: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    executed_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class RunOutcomesResponse(BaseModel):
    processed: int
    results: List[Dict[str, Any]]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/internal/run-outcomes", response_model=RunOutcomesResponse, dependencies=[Depends(require_admin)])
def run_pending_outcomes(
    limit: int = Query(50, le=500),
    db: Session = Depends(get_db),
):
    """Process pending outcome capture jobs. Admin only."""
    scheduler = OutcomeScheduler(db)
    results = scheduler.process_pending(limit=limit)
    return RunOutcomesResponse(processed=len(results), results=results)


@router.get("/decisions/{decision_id}/outcomes", response_model=List[OutcomeResponse])
def get_decision_outcomes(
    decision_id: UUID,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List outcomes for a decision. Org-scoped."""
    org_id = user.get("org_id", "")
    org_accounts = get_org_ad_account_ids(org_id, db)

    # Verify decision belongs to org
    decision = db.query(DecisionPack).filter(DecisionPack.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")
    if org_accounts and decision.ad_account_id not in org_accounts:
        raise HTTPException(status_code=404, detail="Decision not found")

    outcomes = db.query(DecisionOutcome).filter(
        DecisionOutcome.decision_id == decision_id,
    ).order_by(DecisionOutcome.horizon_minutes).all()

    return outcomes
