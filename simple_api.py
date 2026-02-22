"""
Simplified API server - implements core logic inline to avoid import issues.
This is a working MVP that demonstrates the full workflow.
"""
# CRITICAL: Add to path BEFORE any imports - project root MUST be first!
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "backend"))
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session
from backend.src.database.session import init_db, get_db
from backend.src.database.models import (
    Organization,
    DecisionPack,
    DecisionState,
    ActionType,
    AdAccount,
    MetaConnection,
)

# Import core components
from src.core.policy_engine import PolicyEngine
from src.core.operator import Operator
from src.schemas.policy import ActionRequest
from src.schemas.operator import DecisionPack as CoreDecisionPack
from src.utils.logging_config import get_trace_id, set_trace_id

# Import API routers
from backend.src.api import creatives, saturation, opportunities, policies, audit

app = FastAPI(
    title="Meta Ops Agent API",
    version="1.0.0",
    description="Autonomous Meta Ads management with human-in-the-loop approval",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(creatives.router)
app.include_router(saturation.router)
app.include_router(opportunities.router)
app.include_router(policies.router)
app.include_router(audit.router)

policy_engine = PolicyEngine()


# Health check
@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "meta-ops-agent"}


# Organizations
@app.get("/api/orgs")
def list_orgs(db: Session = Depends(get_db)):
    orgs = db.query(Organization).all()
    return [
        {
            "id": str(o.id),
            "name": o.name,
            "slug": o.slug,
            "operator_armed": o.operator_armed,
            "created_at": o.created_at.isoformat(),
        }
        for o in orgs
    ]


@app.post("/api/orgs/{org_id}/operator-armed")
def toggle_operator_armed(org_id: str, body: dict, db: Session = Depends(get_db)):
    org = db.query(Organization).filter(Organization.id == UUID(org_id)).first()
    if not org:
        raise HTTPException(404, "Organization not found")

    org.operator_armed = body.get("enabled", False)
    db.commit()
    db.refresh(org)

    return {
        "id": str(org.id),
        "name": org.name,
        "slug": org.slug,
        "operator_armed": org.operator_armed,
        "created_at": org.created_at.isoformat(),
    }


# Decisions
@app.get("/api/decisions")
def list_decisions(state: str = None, limit: int = 50, db: Session = Depends(get_db)):
    query = db.query(DecisionPack)
    if state:
        try:
            query = query.filter(DecisionPack.state == DecisionState(state))
        except ValueError:
            pass

    decisions = query.order_by(DecisionPack.created_at.desc()).limit(limit).all()

    return [
        {
            "id": str(d.id),
            "trace_id": d.trace_id,
            "state": d.state.value,
            "action_type": d.action_type.value,
            "entity_type": d.entity_type,
            "entity_id": d.entity_id,
            "entity_name": d.entity_name,
            "rationale": d.rationale,
            "source": d.source,
            "before_snapshot": d.before_snapshot,
            "after_proposal": d.after_proposal,
            "policy_checks": d.policy_checks,
            "risk_score": d.risk_score,
            "created_at": d.created_at.isoformat(),
            "validated_at": d.validated_at.isoformat() if d.validated_at else None,
            "approved_at": d.approved_at.isoformat() if d.approved_at else None,
            "executed_at": d.executed_at.isoformat() if d.executed_at else None,
        }
        for d in decisions
    ]


@app.post("/api/decisions")
def create_decision(body: dict, db: Session = Depends(get_db)):
    trace_id = f"draft-{uuid4().hex[:12]}"
    set_trace_id(trace_id)

    # Build action request
    action_request = ActionRequest(
        action_type=body["action_type"],
        entity_id=body["entity_id"],
        entity_type=body["entity_type"],
        payload=body["payload"],
        trace_id=trace_id,
    )

    # Create decision pack
    decision = DecisionPack(
        ad_account_id=UUID(body["ad_account_id"]),
        created_by_user_id=UUID(body["user_id"]),
        state=DecisionState.DRAFT,
        trace_id=trace_id,
        action_type=ActionType(body["action_type"]),
        entity_type=body["entity_type"],
        entity_id=body["entity_id"],
        entity_name=body["entity_name"],
        action_request=action_request.model_dump(),
        rationale=body["rationale"],
        source=body.get("source", "Manual"),
        before_snapshot=body["payload"].get("before", {}),
        after_proposal=body["payload"].get("after", {}),
    )

    db.add(decision)
    db.commit()
    db.refresh(decision)

    return {
        "id": str(decision.id),
        "trace_id": decision.trace_id,
        "state": decision.state.value,
        "action_type": decision.action_type.value,
        "entity_type": decision.entity_type,
        "entity_id": decision.entity_id,
        "entity_name": decision.entity_name,
        "rationale": decision.rationale,
        "source": decision.source,
        "before_snapshot": decision.before_snapshot,
        "after_proposal": decision.after_proposal,
        "policy_checks": decision.policy_checks,
        "risk_score": decision.risk_score,
        "created_at": decision.created_at.isoformat(),
        "validated_at": None,
        "approved_at": None,
        "executed_at": None,
    }


@app.post("/api/decisions/{decision_id}/validate")
def validate_decision(decision_id: str, db: Session = Depends(get_db)):
    decision = db.query(DecisionPack).filter(DecisionPack.id == UUID(decision_id)).first()
    if not decision:
        raise HTTPException(404, "Decision not found")

    if decision.state != DecisionState.DRAFT:
        raise HTTPException(400, f"Can only validate DRAFT decisions, current state: {decision.state.value}")

    set_trace_id(decision.trace_id)
    decision.state = DecisionState.VALIDATING
    db.commit()

    # Validate
    action_request = ActionRequest.model_validate(decision.action_request)
    policy_result = policy_engine.validate(action_request)

    # Store result
    decision.policy_result = policy_result.model_dump()
    decision.policy_checks = [
        {
            "rule_name": v.rule_name,
            "passed": False,
            "severity": v.severity,
            "message": v.message,
        }
        for v in policy_result.violations
    ]

    decision.state = DecisionState.READY if policy_result.approved else DecisionState.BLOCKED
    decision.validated_at = datetime.utcnow()
    db.commit()
    db.refresh(decision)

    return {
        "id": str(decision.id),
        "trace_id": decision.trace_id,
        "state": decision.state.value,
        "policy_checks": decision.policy_checks,
    }


@app.post("/api/decisions/{decision_id}/request-approval")
def request_approval(decision_id: str, db: Session = Depends(get_db)):
    decision = db.query(DecisionPack).filter(DecisionPack.id == UUID(decision_id)).first()
    if not decision:
        raise HTTPException(404, "Decision not found")

    if decision.state != DecisionState.READY:
        raise HTTPException(400, f"Can only request approval for READY decisions, current state: {decision.state.value}")

    decision.state = DecisionState.PENDING_APPROVAL
    decision.expires_at = datetime.utcnow() + timedelta(hours=24)
    db.commit()
    db.refresh(decision)

    return {"id": str(decision.id), "state": decision.state.value}


@app.post("/api/decisions/{decision_id}/approve")
def approve_decision(decision_id: str, body: dict, db: Session = Depends(get_db)):
    decision = db.query(DecisionPack).filter(DecisionPack.id == UUID(decision_id)).first()
    if not decision:
        raise HTTPException(404, "Decision not found")

    if decision.state != DecisionState.PENDING_APPROVAL:
        raise HTTPException(400, f"Can only approve PENDING decisions, current state: {decision.state.value}")

    decision.state = DecisionState.APPROVED
    decision.approved_by_user_id = UUID(body["approver_user_id"])
    decision.approved_at = datetime.utcnow()
    db.commit()
    db.refresh(decision)

    return {"id": str(decision.id), "state": decision.state.value}


@app.post("/api/decisions/{decision_id}/reject")
def reject_decision(decision_id: str, body: dict, db: Session = Depends(get_db)):
    decision = db.query(DecisionPack).filter(DecisionPack.id == UUID(decision_id)).first()
    if not decision:
        raise HTTPException(404, "Decision not found")

    if decision.state != DecisionState.PENDING_APPROVAL:
        raise HTTPException(400, f"Can only reject PENDING decisions, current state: {decision.state.value}")

    decision.state = DecisionState.REJECTED
    decision.rejected_at = datetime.utcnow()
    decision.execution_result = {"rejected_reason": body["reason"]}
    db.commit()
    db.refresh(decision)

    return {"id": str(decision.id), "state": decision.state.value}


@app.post("/api/decisions/{decision_id}/execute")
def execute_decision(decision_id: str, body: dict, db: Session = Depends(get_db)):
    decision = db.query(DecisionPack).filter(DecisionPack.id == UUID(decision_id)).first()
    if not decision:
        raise HTTPException(404, "Decision not found")

    if decision.state != DecisionState.APPROVED:
        raise HTTPException(400, f"Can only execute APPROVED decisions, current state: {decision.state.value}")

    # Get org
    ad_account = db.query(AdAccount).filter(AdAccount.id == decision.ad_account_id).first()
    connection = db.query(MetaConnection).filter(MetaConnection.id == ad_account.connection_id).first()
    org = db.query(Organization).filter(Organization.id == connection.org_id).first()

    dry_run = body.get("dry_run", False)

    if not dry_run and not org.operator_armed:
        raise HTTPException(403, "Operator Armed must be ON to execute live changes")

    set_trace_id(decision.trace_id)

    # Execute
    decision.state = DecisionState.EXECUTING
    db.commit()

    try:
        action_request = ActionRequest.model_validate(decision.action_request)
        core_pack = CoreDecisionPack(
            action_request=action_request,
            rationale=decision.rationale or "",
            source=decision.source or "UI",
        )

        operator = Operator(dry_run=dry_run)
        exec_log = operator.execute(core_pack)

        decision.execution_result = {
            "success": exec_log.action_result.success if exec_log.action_result else False,
            "api_response": exec_log.action_result.api_response if exec_log.action_result else {},
            "error_message": exec_log.action_result.error_message if exec_log.action_result else "",
            "dry_run": dry_run,
        }

        if exec_log.action_result and exec_log.action_result.success:
            decision.state = DecisionState.EXECUTED
        else:
            decision.state = DecisionState.FAILED

        decision.executed_at = datetime.utcnow()
        db.commit()
        db.refresh(decision)

        return {"id": str(decision.id), "state": decision.state.value}

    except Exception as e:
        decision.state = DecisionState.FAILED
        decision.execution_result = {"error": str(e)}
        db.commit()
        raise HTTPException(500, str(e))


@app.on_event("startup")
async def startup():
    print("\n" + "="*60)
    print("META OPS AGENT - API SERVER")
    print("="*60)
    print("Initializing database...")
    init_db()
    print("[OK] Database initialized")
    print("\nAPI server ready at: http://localhost:8000")
    print("API docs at: http://localhost:8000/docs")
    print("="*60 + "\n")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
