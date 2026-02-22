"""Sprint 8 — Templates API: list and install vertical templates."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user
from backend.src.services import template_service

router = APIRouter()


class InstallTemplateRequest(BaseModel):
    overrides: Optional[dict] = None


@router.get("/")
def list_templates(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all available templates."""
    templates = template_service.list_templates(db)
    return [
        {
            "id": str(t.id),
            "slug": t.slug,
            "name": t.name,
            "description": t.description,
            "vertical": t.vertical,
            "default_config": t.default_config_json or {},
        }
        for t in templates
    ]


@router.get("/{template_id}")
def get_template(
    template_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get template detail."""
    from uuid import UUID
    template = template_service.get_template(db, UUID(template_id))
    if not template:
        raise HTTPException(404, "Template not found")

    return {
        "id": str(template.id),
        "slug": template.slug,
        "name": template.name,
        "description": template.description,
        "vertical": template.vertical,
        "default_config": template.default_config_json or {},
    }


@router.post("/{template_id}/install")
def install_template(
    template_id: str,
    body: InstallTemplateRequest = InstallTemplateRequest(),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Install a template for the current org."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    from uuid import UUID
    try:
        org_config = template_service.install_template(
            db, UUID(org_id), UUID(template_id), overrides=body.overrides,
        )
        db.commit()
    except ValueError as e:
        raise HTTPException(404, str(e))

    return {
        "message": "Template installed",
        "template_id": template_id,
        "config": org_config.config_json,
    }
