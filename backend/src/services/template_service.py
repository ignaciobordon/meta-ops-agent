"""Sprint 8 — Template + OrgConfig service: install templates, manage org config."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from backend.src.database.models import OrgConfig, OrgTemplate


def list_templates(db: Session) -> List[OrgTemplate]:
    """List all active templates."""
    return db.query(OrgTemplate).filter(OrgTemplate.is_active == True).order_by(OrgTemplate.name).all()


def get_template(db: Session, template_id: UUID) -> Optional[OrgTemplate]:
    """Get a single template by ID."""
    return db.query(OrgTemplate).filter(OrgTemplate.id == template_id).first()


def get_template_by_slug(db: Session, slug: str) -> Optional[OrgTemplate]:
    """Get a template by slug."""
    return db.query(OrgTemplate).filter(OrgTemplate.slug == slug).first()


def install_template(
    db: Session,
    org_id: UUID,
    template_id: UUID,
    overrides: Optional[dict] = None,
) -> OrgConfig:
    """Install a template for an org, creating or updating OrgConfig."""
    template = db.query(OrgTemplate).filter(OrgTemplate.id == template_id).first()
    if not template:
        raise ValueError(f"Template not found: {template_id}")

    # Merge template defaults with overrides
    config = dict(template.default_config_json or {})
    if overrides:
        config.update(overrides)

    org_config = db.query(OrgConfig).filter(OrgConfig.org_id == org_id).first()
    if org_config:
        org_config.template_id = template_id
        org_config.config_json = config
        org_config.updated_at = datetime.utcnow()
    else:
        org_config = OrgConfig(
            org_id=org_id,
            template_id=template_id,
            config_json=config,
        )
        db.add(org_config)

    db.flush()
    return org_config


def get_org_config(db: Session, org_id: UUID) -> dict:
    """Get merged org config (template defaults + org overrides)."""
    org_config = db.query(OrgConfig).filter(OrgConfig.org_id == org_id).first()
    if not org_config:
        return {"config": {}, "feature_flags": {}, "template_id": None}

    # If template exists, merge template defaults with org overrides
    merged = {}
    if org_config.template_id:
        template = db.query(OrgTemplate).filter(OrgTemplate.id == org_config.template_id).first()
        if template and template.default_config_json:
            merged.update(template.default_config_json)

    if org_config.config_json:
        merged.update(org_config.config_json)

    return {
        "config": merged,
        "feature_flags": org_config.feature_flags_json or {},
        "template_id": str(org_config.template_id) if org_config.template_id else None,
    }


def update_org_config(db: Session, org_id: UUID, overrides: dict) -> OrgConfig:
    """Update org config overrides (patch merge)."""
    org_config = db.query(OrgConfig).filter(OrgConfig.org_id == org_id).first()
    if not org_config:
        org_config = OrgConfig(org_id=org_id, config_json=overrides)
        db.add(org_config)
    else:
        current = dict(org_config.config_json or {})
        current.update(overrides)
        org_config.config_json = current
        org_config.updated_at = datetime.utcnow()

    db.flush()
    return org_config


def get_feature_flags(db: Session, org_id: UUID) -> dict:
    """Get feature flags for an org."""
    org_config = db.query(OrgConfig).filter(OrgConfig.org_id == org_id).first()
    if not org_config:
        return {}
    return org_config.feature_flags_json or {}
