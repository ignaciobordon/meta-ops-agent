"""Sprint 8 — Org Config API: manage per-org configuration overrides."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user
from backend.src.services import template_service

router = APIRouter()


class UpdateConfigRequest(BaseModel):
    overrides: dict


@router.get("/")
def get_org_config(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current org config (merged template defaults + overrides)."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    from uuid import UUID
    return template_service.get_org_config(db, UUID(org_id))


@router.put("/")
def update_org_config(
    body: UpdateConfigRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update org config overrides (patch merge)."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    from uuid import UUID
    template_service.update_org_config(db, UUID(org_id), body.overrides)
    db.commit()
    return template_service.get_org_config(db, UUID(org_id))


@router.get("/feature-flags")
def get_feature_flags(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get feature flags for current org."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    from uuid import UUID
    return template_service.get_feature_flags(db, UUID(org_id))
