"""
Simple API server in project root - avoids import issues.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sys
from pathlib import Path

# Ensure backend is in path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from backend.src.database.session import init_db, get_db
from backend.src.database.models import Organization, DecisionPack as DBDecisionPack, DecisionState
from backend.src.services.decision_service import DecisionService
from sqlalchemy.orm import Session
from fastapi import Depends

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


# Simple health check
@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "meta-ops-agent"}


# Organizations
@app.get("/api/orgs")
def list_orgs(db: Session = Depends(get_db)):
    from backend.src.database.models import Organization
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
    from backend.src.database.models import Organization
    from uuid import UUID

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
    from backend.src.database.models import DecisionPack

    query = db.query(DecisionPack)
    if state:
        query = query.filter(DecisionPack.state == state)

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
    service = DecisionService(db)
    from uuid import UUID

    decision = service.create_draft(
        ad_account_id=UUID(body["ad_account_id"]),
        user_id=UUID(body["user_id"]),
        action_type=body["action_type"],
        entity_type=body["entity_type"],
        entity_id=body["entity_id"],
        entity_name=body["entity_name"],
        payload=body["payload"],
        rationale=body["rationale"],
        source=body.get("source", "Manual"),
    )

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
    service = DecisionService(db)
    from uuid import UUID

    decision = service.validate_decision(UUID(decision_id))

    return {
        "id": str(decision.id),
        "trace_id": decision.trace_id,
        "state": decision.state.value,
        "policy_checks": decision.policy_checks,
    }


@app.post("/api/decisions/{decision_id}/request-approval")
def request_approval(decision_id: str, db: Session = Depends(get_db)):
    service = DecisionService(db)
    from uuid import UUID

    decision = service.request_approval(UUID(decision_id))
    return {"id": str(decision.id), "state": decision.state.value}


@app.post("/api/decisions/{decision_id}/approve")
def approve_decision(decision_id: str, body: dict, db: Session = Depends(get_db)):
    service = DecisionService(db)
    from uuid import UUID

    decision = service.approve_decision(UUID(decision_id), UUID(body["approver_user_id"]))
    return {"id": str(decision.id), "state": decision.state.value}


@app.post("/api/decisions/{decision_id}/reject")
def reject_decision(decision_id: str, body: dict, db: Session = Depends(get_db)):
    service = DecisionService(db)
    from uuid import UUID

    decision = service.reject_decision(UUID(decision_id), body["reason"])
    return {"id": str(decision.id), "state": decision.state.value}


@app.post("/api/decisions/{decision_id}/execute")
def execute_decision(decision_id: str, body: dict, db: Session = Depends(get_db)):
    service = DecisionService(db)
    from uuid import UUID
    from backend.src.database.models import AdAccount, MetaConnection, Organization

    decision = service.get_decision(UUID(decision_id))
    if not decision:
        raise HTTPException(404, "Decision not found")

    # Get org
    ad_account = db.query(AdAccount).filter(AdAccount.id == decision.ad_account_id).first()
    connection = db.query(MetaConnection).filter(MetaConnection.id == ad_account.connection_id).first()
    org = db.query(Organization).filter(Organization.id == connection.org_id).first()

    dry_run = body.get("dry_run", False)

    if not dry_run and not org.operator_armed:
        raise HTTPException(403, "Operator Armed must be ON to execute live changes")

    decision = service.execute_decision(UUID(decision_id), org.operator_armed, dry_run)
    return {"id": str(decision.id), "state": decision.state.value}


@app.on_event("startup")
async def startup():
    print("Initializing database...")
    init_db()
    print("API server ready at http://localhost:8000")
    print("API docs at http://localhost:8000/docs")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
