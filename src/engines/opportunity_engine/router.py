"""FastAPI router for Opportunity Detection Engine (standalone, not yet mounted)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .engine import OpportunityEngine
from .models import CanonicalItem, Opportunity, OpportunityRunReport
from .storage import InMemoryOpportunityStore

# ── Router setup ─────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/opportunities", tags=["Competitive Intelligence"])

# Singleton (would be injected via dependency in production)
_store = InMemoryOpportunityStore()
_engine = OpportunityEngine(storage=_store)


class RunRequest(BaseModel):
    detector_name: Optional[str] = None
    since: Optional[datetime] = None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/ci")
def list_ci_opportunities(
    type: Optional[str] = Query(None, description="Filter by opportunity type"),
    min_priority: float = Query(0.0, ge=0, le=1),
    min_confidence: float = Query(0.0, ge=0, le=1),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict]:
    """List detected competitive intelligence opportunities."""
    opps = _engine.get_opportunities(
        opp_type=type,
        min_priority=min_priority,
        min_confidence=min_confidence,
        limit=limit,
    )
    return [o.model_dump() for o in opps]


@router.post("/run")
def trigger_run(
    request: RunRequest | None = None,
) -> dict:
    """Trigger a detection run (uses stored canonical items)."""
    items = _store.get_items()
    if not items:
        return {"status": "no_data", "message": "No canonical items loaded. Load data first."}

    req = request or RunRequest()

    if req.detector_name:
        report = _engine.run_detector(req.detector_name, items)
    elif req.since:
        report = _engine.run_since(req.since, items)
    else:
        report = _engine.run_all(items)

    return report.model_dump()


@router.get("/{opportunity_id}")
def get_opportunity(opportunity_id: str) -> dict:
    """Get a specific opportunity by ID."""
    opp = _engine.get_opportunity(opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return opp.model_dump()
