"""Decision Pack API endpoints."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.src.database.models import DecisionPack as DBDecisionPack
from backend.src.database.models import DecisionRanking, DecisionState, Organization
from backend.src.database.session import get_db
from backend.src.middleware.auth import require_operator_or_admin, require_admin, get_current_user
from backend.src.services.decision_service import DecisionService
from backend.src.services.ranking_service import DecisionRanker
from backend.src.services.usage_service import UsageService
from backend.src.utils.tenant import get_org_ad_account_ids

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────


class DecisionCreate(BaseModel):
    ad_account_id: UUID
    user_id: UUID
    action_type: str
    entity_type: str
    entity_id: str
    entity_name: str
    payload: dict
    rationale: str
    source: str = "Manual"


class DecisionResponse(BaseModel):
    id: UUID
    trace_id: str
    state: str
    action_type: str
    entity_type: str
    entity_id: str
    entity_name: str
    rationale: Optional[str]
    source: str
    before_snapshot: dict
    after_proposal: dict
    policy_checks: List[dict]
    risk_score: float
    created_at: datetime
    validated_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ApprovalRequest(BaseModel):
    approver_user_id: UUID


class RejectionRequest(BaseModel):
    reason: str


class ExecutionRequest(BaseModel):
    dry_run: bool = False


class RankedDecisionResponse(BaseModel):
    id: UUID
    trace_id: str
    state: str
    action_type: str
    entity_type: str
    entity_id: str
    entity_name: str
    rationale: Optional[str]
    source: str
    before_snapshot: dict
    after_proposal: dict
    policy_checks: List[dict]
    risk_score: float
    created_at: datetime
    validated_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    score_total: float = 0.0
    score_impact: float = 0.0
    score_risk: float = 0.0
    score_confidence: float = 0.0
    score_freshness: float = 1.0
    explanation: Dict[str, Any] = {}

    class Config:
        from_attributes = True


class RankExplanationResponse(BaseModel):
    decision_id: UUID
    score_total: float
    score_impact: float
    score_risk: float
    score_confidence: float
    score_freshness: float
    rank_version: int = 1
    explanation: Dict[str, Any] = {}


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/", response_model=DecisionResponse, dependencies=[Depends(require_operator_or_admin)])
def create_decision(
    decision_data: DecisionCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Create a new draft decision. Requires operator or admin role. Enforces plan limits."""
    org_id = user.get("org_id", "")
    usage_service = UsageService(db)
    usage_service.check_limit(org_id, "decision_create")

    service = DecisionService(db)
    decision = service.create_draft(
        ad_account_id=decision_data.ad_account_id,
        user_id=decision_data.user_id,
        action_type=decision_data.action_type,
        entity_type=decision_data.entity_type,
        entity_id=decision_data.entity_id,
        entity_name=decision_data.entity_name,
        payload=decision_data.payload,
        rationale=decision_data.rationale,
        source=decision_data.source,
    )
    usage_service.record_usage(org_id, "decision_create")
    return decision


@router.get("/", response_model=List[DecisionResponse])
def list_decisions(
    ad_account_id: Optional[UUID] = Query(None),
    state: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List decisions with optional filters. Scoped to user's organization."""
    org_id = user.get("org_id", "")
    org_accounts = get_org_ad_account_ids(org_id, db)

    service = DecisionService(db)
    state_enum = DecisionState(state) if state else None
    decisions = service.list_decisions(
        ad_account_id=ad_account_id,
        state=state_enum,
        limit=limit,
        org_ad_account_ids=org_accounts,
    )
    return decisions


@router.get("/ranked", response_model=List[RankedDecisionResponse])
def list_ranked_decisions(
    state: Optional[str] = Query("pending_approval"),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List decisions ranked by score. Scoped to user's organization."""
    org_id = user.get("org_id", "")
    org_accounts = get_org_ad_account_ids(org_id, db)

    service = DecisionService(db)
    state_enum = DecisionState(state) if state else None
    decisions = service.list_decisions(
        state=state_enum,
        limit=limit,
        org_ad_account_ids=org_accounts,
    )

    if not decisions:
        return []

    try:
        org_uuid = UUID(org_id)
    except (ValueError, AttributeError):
        return []

    ranker = DecisionRanker()
    rankings = ranker.rank_decisions(org_uuid, decisions, db)

    # Build response with ranking scores
    ranked_map = {r.decision_id: r for r in rankings}
    result = []
    for ranking in rankings:
        decision = next((d for d in decisions if d.id == ranking.decision_id), None)
        if not decision:
            continue
        result.append(RankedDecisionResponse(
            id=decision.id,
            trace_id=decision.trace_id,
            state=decision.state.value if hasattr(decision.state, 'value') else str(decision.state),
            action_type=decision.action_type.value if hasattr(decision.action_type, 'value') else str(decision.action_type),
            entity_type=decision.entity_type or "",
            entity_id=decision.entity_id or "",
            entity_name=decision.entity_name or "",
            rationale=decision.rationale,
            source=decision.source or "",
            before_snapshot=decision.before_snapshot or {},
            after_proposal=decision.after_proposal or {},
            policy_checks=decision.policy_checks or [],
            risk_score=decision.risk_score or 0.0,
            created_at=decision.created_at,
            validated_at=decision.validated_at,
            approved_at=decision.approved_at,
            executed_at=decision.executed_at,
            score_total=ranking.score_total,
            score_impact=ranking.score_impact,
            score_risk=ranking.score_risk,
            score_confidence=ranking.score_confidence,
            score_freshness=ranking.score_freshness,
            explanation=ranking.explanation_json or {},
        ))

    return result


@router.get("/{decision_id}", response_model=DecisionResponse)
def get_decision(
    decision_id: UUID,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get a decision by ID. Scoped to user's organization."""
    org_id = user.get("org_id", "")
    org_accounts = get_org_ad_account_ids(org_id, db)

    service = DecisionService(db)
    decision = service.get_decision(decision_id)
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    # Enforce org isolation
    if org_accounts and decision.ad_account_id not in org_accounts:
        raise HTTPException(status_code=404, detail="Decision not found")

    return decision


@router.get("/{decision_id}/rank-explanation", response_model=RankExplanationResponse)
def get_rank_explanation(
    decision_id: UUID,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get detailed ranking score breakdown for a decision."""
    org_id = user.get("org_id", "")
    org_accounts = get_org_ad_account_ids(org_id, db)

    decision = db.query(DBDecisionPack).filter(DBDecisionPack.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")
    if org_accounts and decision.ad_account_id not in org_accounts:
        raise HTTPException(status_code=404, detail="Decision not found")

    ranking = db.query(DecisionRanking).filter(
        DecisionRanking.decision_id == decision_id
    ).first()

    if not ranking:
        # Generate ranking on-the-fly
        try:
            org_uuid = UUID(org_id)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="Invalid org context")
        ranker = DecisionRanker()
        rankings = ranker.rank_decisions(org_uuid, [decision], db)
        ranking = rankings[0] if rankings else None

    if not ranking:
        raise HTTPException(status_code=404, detail="Ranking not available")

    return RankExplanationResponse(
        decision_id=decision_id,
        score_total=ranking.score_total,
        score_impact=ranking.score_impact,
        score_risk=ranking.score_risk,
        score_confidence=ranking.score_confidence,
        score_freshness=ranking.score_freshness,
        rank_version=ranking.rank_version or 1,
        explanation=ranking.explanation_json or {},
    )


@router.post("/{decision_id}/validate", response_model=DecisionResponse, dependencies=[Depends(require_operator_or_admin)])
def validate_decision(decision_id: UUID, db: Session = Depends(get_db)):
    """Validate a draft decision via Policy Engine. Requires operator+."""
    service = DecisionService(db)
    try:
        decision = service.validate_decision(decision_id)
        return decision
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{decision_id}/request-approval", response_model=DecisionResponse, dependencies=[Depends(require_operator_or_admin)])
def request_approval(decision_id: UUID, db: Session = Depends(get_db)):
    """Submit a READY decision for approval. Requires operator+."""
    service = DecisionService(db)
    try:
        decision = service.request_approval(decision_id)
        return decision
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{decision_id}/approve", response_model=DecisionResponse, dependencies=[Depends(require_operator_or_admin)])
def approve_decision(
    decision_id: UUID, approval: ApprovalRequest, db: Session = Depends(get_db)
):
    """Approve a pending decision. Requires operator+ role."""
    service = DecisionService(db)
    try:
        decision = service.approve_decision(decision_id, approval.approver_user_id)
        return decision
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{decision_id}/reject", response_model=DecisionResponse, dependencies=[Depends(require_operator_or_admin)])
def reject_decision(
    decision_id: UUID, rejection: RejectionRequest, db: Session = Depends(get_db)
):
    """Reject a pending decision. Requires operator+."""
    service = DecisionService(db)
    try:
        decision = service.reject_decision(decision_id, rejection.reason)
        return decision
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{decision_id}/execute", response_model=DecisionResponse, dependencies=[Depends(require_admin)])
def execute_decision(
    decision_id: UUID,
    execution: ExecutionRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Execute an approved decision via Operator. Requires admin role."""
    service = DecisionService(db)

    # Get decision to find its org
    decision = service.get_decision(decision_id)
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    # Get ad_account → connection → org
    from backend.src.database.models import AdAccount, MetaConnection
    ad_account = db.query(AdAccount).filter(AdAccount.id == decision.ad_account_id).first()
    if not ad_account:
        raise HTTPException(status_code=404, detail="Ad account not found")

    connection = db.query(MetaConnection).filter(MetaConnection.id == ad_account.connection_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Meta connection not found")

    org = db.query(Organization).filter(Organization.id == connection.org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Enforce plan execution mode (TRIAL forces dry_run)
    org_id = user.get("org_id", "")
    usage_service = UsageService(db)
    actual_dry_run = usage_service.enforce_execution_mode(org_id, execution.dry_run)

    # Check operator_armed unless dry_run
    if not actual_dry_run and not org.operator_armed:
        raise HTTPException(
            status_code=403,
            detail="Operator Armed must be enabled to execute live changes"
        )

    try:
        decision = service.execute_decision(
            decision_id, operator_armed=org.operator_armed, dry_run=actual_dry_run
        )
        return decision
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
