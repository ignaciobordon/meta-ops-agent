"""
Auth API - Login, Register, Refresh, Logout, Sessions endpoints.
Real JWT tokens with jti, token revocation, session tracking, refresh rotation.
"""
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4, UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.src.config import settings
from backend.src.database.models import (
    User, UserOrgRole, Organization, RoleEnum,
    RevokedToken, UserSession,
    Subscription, PlanEnum, SubscriptionStatusEnum, PLAN_LIMITS,
    Branding, Invite,
)
from backend.src.database.session import get_db
from backend.src.middleware.auth import (
    UserRole,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    verify_password,
    JWT_ACCESS_TTL_MINUTES,
)
from backend.src.middleware.rate_limit import login_limiter
from backend.src.utils.auth_events import (
    AuthEvent, log_auth_event, extract_client_ip, extract_device_info, hash_token,
)

router = APIRouter(tags=["auth"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    name: str
    password: str
    org_id: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class RefreshRequest(BaseModel):
    refresh_token: str


class BootstrapRequest(BaseModel):
    org_name: str
    admin_email: str
    admin_password: str
    admin_name: str = "Admin"


class BootstrapCheckResponse(BaseModel):
    needs_bootstrap: bool
    org_count: int


class MeResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    org_id: str | None


class SessionInfo(BaseModel):
    id: str
    device_info: str | None
    ip_address: str | None
    created_at: str
    last_used_at: str | None
    is_current: bool


# ── Helpers ──────────────────────────────────────────────────────────────────


def _create_session(
    db: Session,
    user_id: UUID,
    refresh_token: str,
    request: Request,
) -> UserSession:
    """Create a session row for the given user and refresh token."""
    ua = request.headers.get("User-Agent", "") if request else ""
    session = UserSession(
        id=uuid4(),
        user_id=user_id,
        refresh_token_hash=hash_token(refresh_token),
        device_info=extract_device_info(ua),
        ip_address=extract_client_ip(request),
        user_agent=ua,
        created_at=datetime.now(timezone.utc),
        last_used_at=datetime.now(timezone.utc),
    )
    db.add(session)
    return session


def _build_token_response(user, role: str, org_id: str, access_token: str, refresh_token: str) -> TokenResponse:
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=JWT_ACCESS_TTL_MINUTES * 60,
        user={
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "role": role,
            "org_id": org_id,
        },
    )


def _revoke_all_user_sessions(db: Session, user_id: UUID, reason: str):
    """Revoke all active sessions for a user (theft detection)."""
    active_sessions = db.query(UserSession).filter(
        UserSession.user_id == user_id,
        UserSession.revoked_at.is_(None),
    ).all()
    now = datetime.now(timezone.utc)
    for s in active_sessions:
        s.revoked_at = now


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/bootstrap-check", response_model=BootstrapCheckResponse)
def bootstrap_check(db: Session = Depends(get_db)):
    """Check if the system needs initial bootstrap (zero organizations)."""
    org_count = db.query(Organization).count()
    return BootstrapCheckResponse(needs_bootstrap=org_count == 0, org_count=org_count)


@router.post("/bootstrap", response_model=TokenResponse)
def bootstrap(body: BootstrapRequest, request: Request, db: Session = Depends(get_db)):
    """
    First-time setup: create organization + admin user in one call.
    Only works when DB has zero organizations (prevents abuse).
    Can be disabled via BOOTSTRAP_ENABLED=false env var.
    """
    # Step 10: Bootstrap hardening — env flag (re-read at runtime for safety)
    import os
    bootstrap_enabled = os.environ.get("BOOTSTRAP_ENABLED", str(settings.BOOTSTRAP_ENABLED)).lower()
    if bootstrap_enabled == "false":
        raise HTTPException(status_code=403, detail="Bootstrap is disabled via BOOTSTRAP_ENABLED=false")

    org_count = db.query(Organization).count()
    if org_count > 0:
        raise HTTPException(
            status_code=400,
            detail="Bootstrap is disabled. Organizations already exist. Use /login or /register."
        )

    existing = db.query(User).filter(User.email == body.admin_email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create organization
    slug = body.org_name.lower().replace(" ", "-").replace("_", "-")
    org = Organization(
        id=uuid4(),
        name=body.org_name,
        slug=slug,
        operator_armed=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(org)
    db.flush()

    # Create admin user
    user = User(
        id=uuid4(),
        email=body.admin_email,
        name=body.admin_name,
        password_hash=hash_password(body.admin_password),
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.flush()

    # Assign admin role
    user_org_role = UserOrgRole(
        id=uuid4(),
        user_id=user.id,
        org_id=org.id,
        role=RoleEnum.ADMIN,
        assigned_at=datetime.now(timezone.utc),
    )
    db.add(user_org_role)

    # Sprint 4: Create TRIAL subscription
    from datetime import timedelta
    trial_limits = PLAN_LIMITS[PlanEnum.TRIAL]
    subscription = Subscription(
        id=uuid4(),
        org_id=org.id,
        plan=PlanEnum.TRIAL,
        status=SubscriptionStatusEnum.TRIALING,
        trial_ends_at=datetime.now(timezone.utc) + timedelta(days=14),
        max_ad_accounts=trial_limits["max_ad_accounts"],
        max_decisions_per_month=trial_limits["max_decisions_per_month"],
        max_creatives_per_month=trial_limits["max_creatives_per_month"],
        allow_live_execution=trial_limits["allow_live_execution"],
        created_at=datetime.now(timezone.utc),
    )
    db.add(subscription)

    # Sprint 4: Create default branding
    branding = Branding(
        id=uuid4(),
        org_id=org.id,
        primary_color="#D4845C",
        accent_color="#8B9D5D",
        company_name=body.org_name,
        created_at=datetime.now(timezone.utc),
    )
    db.add(branding)

    access_token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        role="admin",
        org_id=str(org.id),
    )
    refresh_token = create_refresh_token(user_id=str(user.id))

    # Step 6: Create session
    _create_session(db, user.id, refresh_token, request)
    db.commit()

    log_auth_event(
        AuthEvent.BOOTSTRAP_CREATED,
        user_email=user.email,
        user_id=str(user.id),
        request=request,
        extra_data={"org_name": org.name, "org_id": str(org.id)},
    )

    return _build_token_response(user, "admin", str(org.id), access_token, refresh_token)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Authenticate user with email + password. Returns JWT tokens."""
    # Step 9: Login rate limiting
    client_ip = extract_client_ip(request)
    allowed, rate_headers = await login_limiter.is_allowed(client_ip)
    if not allowed:
        retry_after = rate_headers.get("Retry-After", "300")
        log_auth_event(
            AuthEvent.LOGIN_FAILED,
            user_email=body.email,
            request=request,
            reason="rate_limited",
        )
        raise HTTPException(
            status_code=429,
            detail=f"Too many login attempts. Try again in {retry_after} seconds.",
            headers=rate_headers,
        )

    user = db.query(User).filter(User.email == body.email).first()
    if not user:
        log_auth_event(AuthEvent.LOGIN_FAILED, user_email=body.email, request=request, reason="user_not_found")
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.password_hash or not verify_password(body.password, user.password_hash):
        log_auth_event(AuthEvent.LOGIN_FAILED, user_email=body.email, request=request, reason="invalid_password")
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Get user's org role
    user_org_role = db.query(UserOrgRole).filter(UserOrgRole.user_id == user.id).first()
    org_id = str(user_org_role.org_id) if user_org_role else ""
    role = user_org_role.role.value if user_org_role else "viewer"

    # Update last_login
    user.last_login = datetime.now(timezone.utc)

    access_token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        role=role,
        org_id=org_id,
    )
    refresh_token = create_refresh_token(user_id=str(user.id))

    # Step 6: Create session
    _create_session(db, user.id, refresh_token, request)
    db.commit()

    # Reset rate limiter on success
    await login_limiter.reset(client_ip)

    log_auth_event(
        AuthEvent.LOGIN_SUCCESS,
        user_email=user.email,
        user_id=str(user.id),
        request=request,
    )

    return _build_token_response(user, role, org_id, access_token, refresh_token)


@router.post("/register", response_model=TokenResponse)
def register(body: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    """Register a new user. First user in an org gets admin, rest get viewer."""
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    try:
        org_uuid = UUID(body.org_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid org_id format")

    org = db.query(Organization).filter(Organization.id == org_uuid).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    existing_members = db.query(UserOrgRole).filter(UserOrgRole.org_id == org_uuid).count()
    role = RoleEnum.ADMIN if existing_members == 0 else RoleEnum.VIEWER

    user = User(
        id=uuid4(),
        email=body.email,
        name=body.name,
        password_hash=hash_password(body.password),
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.flush()

    user_org_role = UserOrgRole(
        id=uuid4(),
        user_id=user.id,
        org_id=org_uuid,
        role=role,
        assigned_at=datetime.now(timezone.utc),
    )
    db.add(user_org_role)

    access_token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        role=role.value,
        org_id=body.org_id,
    )
    refresh_token = create_refresh_token(user_id=str(user.id))

    # Step 6: Create session
    _create_session(db, user.id, refresh_token, request)
    db.commit()

    log_auth_event(
        AuthEvent.LOGIN_SUCCESS,
        user_email=user.email,
        user_id=str(user.id),
        request=request,
        extra_data={"action": "register", "role": role.value},
    )

    return _build_token_response(user, role.value, body.org_id, access_token, refresh_token)


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(body: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    """
    Exchange a refresh token for new tokens.
    Implements rotation: old refresh token is revoked, new one issued.
    Theft detection: if old (already-rotated) token is reused, all sessions revoked.
    """
    payload = decode_token(body.refresh_token)

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_id = payload.get("sub")
    jti = payload.get("jti")

    try:
        user_uuid = UUID(user_id)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid user ID in token")

    # Step 7: Check if this refresh token's jti has been revoked (reuse detection)
    if jti:
        revoked = db.query(RevokedToken).filter(RevokedToken.jti == jti).first()
        if revoked:
            # Theft detected — this token was already rotated. Revoke ALL sessions.
            log_auth_event(
                AuthEvent.SUSPICIOUS_ACTIVITY,
                user_id=user_id,
                request=request,
                reason="refresh_token_reuse_detected",
            )
            _revoke_all_user_sessions(db, user_uuid, "theft_detected")
            db.commit()
            raise HTTPException(status_code=401, detail="Token reuse detected. All sessions revoked.")

    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Validate session exists and is active
    token_hash = hash_token(body.refresh_token)
    session = db.query(UserSession).filter(
        UserSession.refresh_token_hash == token_hash,
        UserSession.revoked_at.is_(None),
    ).first()

    if not session:
        log_auth_event(
            AuthEvent.REFRESH_FAILED,
            user_id=user_id,
            user_email=user.email,
            request=request,
            reason="session_not_found",
        )
        raise HTTPException(status_code=401, detail="Session not found or revoked")

    # Get current org role
    user_org_role = db.query(UserOrgRole).filter(UserOrgRole.user_id == user.id).first()
    org_id = str(user_org_role.org_id) if user_org_role else ""
    role = user_org_role.role.value if user_org_role else "viewer"

    # Create new tokens
    new_access = create_access_token(
        user_id=str(user.id),
        email=user.email,
        role=role,
        org_id=org_id,
    )
    new_refresh = create_refresh_token(user_id=str(user.id))

    # Revoke old refresh token jti
    if jti:
        db.add(RevokedToken(
            id=uuid4(),
            jti=jti,
            user_id=user_uuid,
            token_type="refresh",
            revoked_at=datetime.now(timezone.utc),
            reason="rotated",
        ))

    # Update session with new refresh token hash
    session.refresh_token_hash = hash_token(new_refresh)
    session.last_used_at = datetime.now(timezone.utc)
    db.commit()

    log_auth_event(
        AuthEvent.REFRESH_SUCCESS,
        user_email=user.email,
        user_id=str(user.id),
        request=request,
    )

    return _build_token_response(user, role, org_id, new_access, new_refresh)


@router.post("/logout")
def logout(
    request: Request,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Logout: revoke current access token and its session."""
    # Extract token from Authorization header to get jti
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            payload = decode_token(token)
            jti = payload.get("jti")
            if jti:
                db.add(RevokedToken(
                    id=uuid4(),
                    jti=jti,
                    user_id=UUID(user["id"]),
                    token_type="access",
                    revoked_at=datetime.now(timezone.utc),
                    reason="logout",
                ))
        except HTTPException:
            pass  # Token already invalid, still log out

    db.commit()

    log_auth_event(
        AuthEvent.LOGOUT,
        user_email=user["email"],
        user_id=user["id"],
        request=request,
    )

    return {"message": "Logged out successfully"}


@router.get("/sessions", response_model=List[SessionInfo])
def list_sessions(
    request: Request,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all active sessions for the current user."""
    user_uuid = UUID(user["id"])
    sessions = db.query(UserSession).filter(
        UserSession.user_id == user_uuid,
        UserSession.revoked_at.is_(None),
    ).order_by(UserSession.last_used_at.desc()).all()

    # Determine current session by matching the token's user + most recent
    result = []
    for i, s in enumerate(sessions):
        result.append(SessionInfo(
            id=str(s.id),
            device_info=s.device_info,
            ip_address=s.ip_address,
            created_at=s.created_at.isoformat() if s.created_at else "",
            last_used_at=s.last_used_at.isoformat() if s.last_used_at else None,
            is_current=(i == 0),  # Most recently used = likely current
        ))

    return result


@router.delete("/sessions/{session_id}")
def revoke_session(
    session_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke a specific session. User can only revoke their own sessions."""
    user_uuid = UUID(user["id"])
    try:
        sess_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID")

    session = db.query(UserSession).filter(
        UserSession.id == sess_uuid,
        UserSession.user_id == user_uuid,
        UserSession.revoked_at.is_(None),
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.revoked_at = datetime.now(timezone.utc)
    db.commit()

    log_auth_event(
        AuthEvent.SESSION_REVOKED,
        user_email=user["email"],
        user_id=user["id"],
        request=request,
        extra_data={"session_id": session_id},
    )

    return {"message": "Session revoked"}


@router.get("/me", response_model=MeResponse)
def get_me(user: dict = Depends(get_current_user)):
    """Get current authenticated user info."""
    return MeResponse(
        id=user["id"],
        email=user["email"],
        name=user["name"],
        role=user["role"].value if hasattr(user["role"], "value") else user["role"],
        org_id=user.get("org_id"),
    )


class AcceptInviteRequest(BaseModel):
    name: str
    password: str


@router.post("/accept-invite/{token}", response_model=TokenResponse)
def accept_invite(
    token: str,
    body: AcceptInviteRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Accept an invite and create a new user account."""
    invite = db.query(Invite).filter(Invite.token == token).first()
    if not invite:
        raise HTTPException(404, "Invite not found or already used")

    if invite.accepted_at:
        raise HTTPException(400, "Invite has already been accepted")

    if invite.expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, "Invite has expired")

    # Check if email already registered
    existing = db.query(User).filter(User.email == invite.email).first()
    if existing:
        # User exists, just add role
        existing_role = db.query(UserOrgRole).filter(
            UserOrgRole.user_id == existing.id,
            UserOrgRole.org_id == invite.org_id,
        ).first()
        if existing_role:
            raise HTTPException(400, "You are already a member of this organization")

        role = UserOrgRole(
            id=uuid4(),
            user_id=existing.id,
            org_id=invite.org_id,
            role=invite.role or RoleEnum.VIEWER,
            assigned_at=datetime.now(timezone.utc),
        )
        db.add(role)
        invite.accepted_at = datetime.now(timezone.utc)

        access_token = create_access_token(
            user_id=str(existing.id),
            email=existing.email,
            role=(invite.role or RoleEnum.VIEWER).value,
            org_id=str(invite.org_id),
        )
        refresh_token = create_refresh_token(user_id=str(existing.id))
        _create_session(db, existing.id, refresh_token, request)
        db.commit()
        return _build_token_response(
            existing, (invite.role or RoleEnum.VIEWER).value,
            str(invite.org_id), access_token, refresh_token,
        )

    # Create new user
    user = User(
        id=uuid4(),
        email=invite.email,
        name=body.name,
        password_hash=hash_password(body.password),
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.flush()

    role = UserOrgRole(
        id=uuid4(),
        user_id=user.id,
        org_id=invite.org_id,
        role=invite.role or RoleEnum.VIEWER,
        assigned_at=datetime.now(timezone.utc),
    )
    db.add(role)

    invite.accepted_at = datetime.now(timezone.utc)

    access_token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        role=(invite.role or RoleEnum.VIEWER).value,
        org_id=str(invite.org_id),
    )
    refresh_token = create_refresh_token(user_id=str(user.id))
    _create_session(db, user.id, refresh_token, request)
    db.commit()

    return _build_token_response(
        user, (invite.role or RoleEnum.VIEWER).value,
        str(invite.org_id), access_token, refresh_token,
    )
