"""Organization management endpoints — includes members, invites, and branding."""
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.src.database.models import (
    AdAccount, MetaConnection, Organization, User, UserOrgRole, RoleEnum,
    Branding, Invite,
)
from backend.src.database.session import get_db
from backend.src.middleware.auth import require_admin, get_current_user

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────


class OrgCreate(BaseModel):
    name: str
    slug: str


class OrgResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    operator_armed: bool
    created_at: datetime

    class Config:
        from_attributes = True


class OperatorArmedToggle(BaseModel):
    enabled: bool


class AdAccountResponse(BaseModel):
    id: UUID
    meta_ad_account_id: str
    name: str
    currency: str

    class Config:
        from_attributes = True


class MemberResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    joined_at: str


class InviteRequest(BaseModel):
    email: str
    role: str = "viewer"


class InviteResponse(BaseModel):
    id: str
    email: str
    role: str
    token: str
    expires_at: str
    created_at: str
    accepted_at: Optional[str] = None


class BrandingResponse(BaseModel):
    id: str
    logo_url: Optional[str] = None
    primary_color: str
    accent_color: str
    company_name: Optional[str] = None
    custom_domain: Optional[str] = None

    class Config:
        from_attributes = True


class BrandingUpdate(BaseModel):
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    accent_color: Optional[str] = None
    company_name: Optional[str] = None
    custom_domain: Optional[str] = None


# ── Org CRUD ─────────────────────────────────────────────────────────────────


@router.post("/", response_model=OrgResponse, dependencies=[Depends(require_admin)])
def create_org(org_data: OrgCreate, db: Session = Depends(get_db)):
    """Create a new organization. Requires admin role."""
    existing = db.query(Organization).filter(Organization.slug == org_data.slug).first()
    if existing:
        raise HTTPException(status_code=400, detail="Slug already exists")

    org = Organization(name=org_data.name, slug=org_data.slug)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@router.get("/", response_model=List[OrgResponse])
def list_orgs(db: Session = Depends(get_db)):
    """List all organizations."""
    orgs = db.query(Organization).all()
    return orgs


@router.get("/members", response_model=List[MemberResponse])
def list_members(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all members of the current user's organization."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization associated with user")

    org_uuid = UUID(org_id)
    roles = db.query(UserOrgRole).filter(UserOrgRole.org_id == org_uuid).all()

    members = []
    for role in roles:
        u = db.query(User).filter(User.id == role.user_id).first()
        if u:
            members.append(MemberResponse(
                id=str(u.id),
                email=u.email,
                name=u.name,
                role=role.role.value,
                joined_at=role.assigned_at.isoformat() if role.assigned_at else "",
            ))
    return members


@router.get("/branding", response_model=BrandingResponse)
def get_branding(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get branding for the current user's organization."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization associated with user")

    org_uuid = UUID(org_id)
    branding = db.query(Branding).filter(Branding.org_id == org_uuid).first()
    if not branding:
        return BrandingResponse(
            id="", primary_color="#D4845C", accent_color="#8B9D5D",
        )

    return BrandingResponse(
        id=str(branding.id),
        logo_url=branding.logo_url,
        primary_color=branding.primary_color or "#D4845C",
        accent_color=branding.accent_color or "#8B9D5D",
        company_name=branding.company_name,
        custom_domain=branding.custom_domain,
    )


@router.put("/branding", response_model=BrandingResponse, dependencies=[Depends(require_admin)])
def update_branding(
    body: BrandingUpdate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update branding for the current user's organization. Admin only."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization associated with user")

    # Validate hex colors
    hex_pattern = re.compile(r'^#[0-9A-Fa-f]{6}$')
    if body.primary_color and not hex_pattern.match(body.primary_color):
        raise HTTPException(400, "Invalid primary_color format. Use hex: #RRGGBB")
    if body.accent_color and not hex_pattern.match(body.accent_color):
        raise HTTPException(400, "Invalid accent_color format. Use hex: #RRGGBB")

    org_uuid = UUID(org_id)
    branding = db.query(Branding).filter(Branding.org_id == org_uuid).first()

    if not branding:
        branding = Branding(
            id=uuid4(), org_id=org_uuid,
            created_at=datetime.now(timezone.utc),
        )
        db.add(branding)

    if body.logo_url is not None:
        branding.logo_url = body.logo_url
    if body.primary_color is not None:
        branding.primary_color = body.primary_color
    if body.accent_color is not None:
        branding.accent_color = body.accent_color
    if body.company_name is not None:
        branding.company_name = body.company_name
    if body.custom_domain is not None:
        branding.custom_domain = body.custom_domain
    branding.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(branding)

    return BrandingResponse(
        id=str(branding.id),
        logo_url=branding.logo_url,
        primary_color=branding.primary_color or "#D4845C",
        accent_color=branding.accent_color or "#8B9D5D",
        company_name=branding.company_name,
        custom_domain=branding.custom_domain,
    )


# ── Invites ──────────────────────────────────────────────────────────────────


@router.post("/invites", response_model=InviteResponse, dependencies=[Depends(require_admin)])
def create_invite(
    body: InviteRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create an invite for a new team member. Admin only."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization associated with user")

    org_uuid = UUID(org_id)

    # Check for existing user in org
    existing_user = db.query(User).filter(User.email == body.email).first()
    if existing_user:
        existing_role = db.query(UserOrgRole).filter(
            UserOrgRole.user_id == existing_user.id,
            UserOrgRole.org_id == org_uuid,
        ).first()
        if existing_role:
            raise HTTPException(400, "User is already a member of this organization")

    # Check for pending invite
    existing_invite = db.query(Invite).filter(
        Invite.email == body.email,
        Invite.org_id == org_uuid,
        Invite.accepted_at.is_(None),
    ).first()
    if existing_invite:
        raise HTTPException(400, "A pending invite already exists for this email")

    # Validate role
    try:
        role = RoleEnum(body.role)
    except ValueError:
        raise HTTPException(400, f"Invalid role: {body.role}")

    token = secrets.token_urlsafe(48)
    invite = Invite(
        id=uuid4(),
        org_id=org_uuid,
        invited_by_user_id=UUID(user["id"]),
        email=body.email,
        role=role,
        token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        created_at=datetime.now(timezone.utc),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    return InviteResponse(
        id=str(invite.id),
        email=invite.email,
        role=invite.role.value,
        token=invite.token,
        expires_at=invite.expires_at.isoformat(),
        created_at=invite.created_at.isoformat(),
    )


@router.get("/invites", response_model=List[InviteResponse])
def list_invites(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List pending invites for the current org."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization associated with user")

    org_uuid = UUID(org_id)
    invites = db.query(Invite).filter(
        Invite.org_id == org_uuid,
        Invite.accepted_at.is_(None),
    ).order_by(Invite.created_at.desc()).all()

    return [
        InviteResponse(
            id=str(inv.id),
            email=inv.email,
            role=inv.role.value if inv.role else "viewer",
            token=inv.token,
            expires_at=inv.expires_at.isoformat() if inv.expires_at else "",
            created_at=inv.created_at.isoformat() if inv.created_at else "",
            accepted_at=inv.accepted_at.isoformat() if inv.accepted_at else None,
        )
        for inv in invites
    ]


@router.delete("/invites/{invite_id}", dependencies=[Depends(require_admin)])
def revoke_invite(
    invite_id: UUID,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke a pending invite. Admin only."""
    org_id = user.get("org_id", "")
    org_uuid = UUID(org_id)

    invite = db.query(Invite).filter(
        Invite.id == invite_id,
        Invite.org_id == org_uuid,
    ).first()
    if not invite:
        raise HTTPException(404, "Invite not found")

    db.delete(invite)
    db.commit()
    return {"message": "Invite revoked"}


# ── Org Settings ─────────────────────────────────────────────────────────────


class OrgSettingsUpdate(BaseModel):
    conversion_model: Optional[str] = None  # "online", "offline", "hybrid"


@router.get("/settings")
def get_org_settings(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get organization settings (including conversion_model)."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization associated with user")

    org = db.query(Organization).filter(Organization.id == UUID(org_id)).first()
    if not org:
        raise HTTPException(404, "Organization not found")

    return org.settings or {}


@router.put("/settings")
def update_org_settings(
    body: OrgSettingsUpdate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update organization settings (patch merge)."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization associated with user")

    org = db.query(Organization).filter(Organization.id == UUID(org_id)).first()
    if not org:
        raise HTTPException(404, "Organization not found")

    # Validate conversion_model
    if body.conversion_model is not None:
        if body.conversion_model not in ("online", "offline", "hybrid"):
            raise HTTPException(400, "conversion_model must be 'online', 'offline', or 'hybrid'")

    settings = dict(org.settings or {})
    if body.conversion_model is not None:
        settings["conversion_model"] = body.conversion_model

    org.settings = settings
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(org, "settings")
    db.commit()

    return settings


# ── Existing org endpoints ───────────────────────────────────────────────────


@router.get("/{org_id}", response_model=OrgResponse)
def get_org(org_id: UUID, db: Session = Depends(get_db)):
    """Get organization by ID."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.post("/{org_id}/operator-armed", response_model=OrgResponse, dependencies=[Depends(require_admin)])
def toggle_operator_armed(
    org_id: UUID, toggle: OperatorArmedToggle, db: Session = Depends(get_db)
):
    """Toggle Operator Armed mode. Requires admin role."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    org.operator_armed = toggle.enabled
    db.commit()
    db.refresh(org)
    return org


@router.get("/{org_id}/ad-accounts", response_model=List[AdAccountResponse])
def list_ad_accounts(org_id: UUID, db: Session = Depends(get_db)):
    """List all ad accounts for an organization."""
    connections = db.query(MetaConnection).filter(MetaConnection.org_id == org_id).all()
    connection_ids = [c.id for c in connections]

    ad_accounts = (
        db.query(AdAccount)
        .filter(AdAccount.connection_id.in_(connection_ids))
        .all()
    )
    return ad_accounts
