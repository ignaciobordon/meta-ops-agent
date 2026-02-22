"""Sprint 8 — Onboarding API: step management and status."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user
from backend.src.services import onboarding_service

router = APIRouter()


class StepAdvanceRequest(BaseModel):
    template_id: Optional[str] = None


@router.get("/status")
def get_onboarding_status(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current onboarding progress."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    from uuid import UUID
    return onboarding_service.get_progress(db, UUID(org_id))


@router.post("/step/{step}")
def advance_onboarding_step(
    step: str,
    body: StepAdvanceRequest = StepAdvanceRequest(),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Advance onboarding to a specific step."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    from uuid import UUID
    data = {}
    if body.template_id:
        data["template_id"] = body.template_id

    try:
        state = onboarding_service.advance_step(
            db, UUID(org_id), step, data=data, user_id=UUID(user["id"]),
        )
        db.commit()
    except ValueError as e:
        raise HTTPException(400, str(e))

    return onboarding_service.get_progress(db, UUID(org_id))


@router.post("/complete")
def complete_onboarding(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark onboarding as complete."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    from uuid import UUID
    try:
        onboarding_service.complete_onboarding(db, UUID(org_id))
        db.commit()
    except ValueError as e:
        raise HTTPException(400, str(e))

    return onboarding_service.get_progress(db, UUID(org_id))
