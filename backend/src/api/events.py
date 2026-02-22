"""Sprint 8 — Product Events API: tracking and funnel analytics."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user
from backend.src.services import event_service

router = APIRouter()


class TrackEventRequest(BaseModel):
    event_name: str
    properties: Optional[dict] = None


@router.post("/track")
def track_event(
    body: TrackEventRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Track a product event."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    from uuid import UUID
    event = event_service.track(
        db, UUID(org_id), UUID(user["id"]),
        body.event_name, body.properties,
    )
    db.commit()
    return {"id": str(event.id), "event_name": body.event_name}


@router.get("/funnel")
def get_funnel(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get onboarding funnel stats (admin: global, others: own org)."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    from uuid import UUID
    # Admins see global funnel, others see their org only
    if user.get("role") == "admin":
        return event_service.get_funnel(db)
    return event_service.get_funnel(db, UUID(org_id))


@router.get("/")
def list_events(
    event_name: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List recent product events for the org."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    from uuid import UUID
    return event_service.get_events(db, UUID(org_id), event_name, limit)
