"""
FASE 5.3: Real JWT Authentication + Role-Based Access Control (RBAC)
No mock users. Real JWT tokens signed with SECRET_KEY.
Roles: admin, operator, viewer.
All requests logged with user_id + role + trace_id.
"""
import hashlib
import bcrypt
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Optional
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.src.config import settings
from backend.src.database.session import get_db
from src.utils.logging_config import logger


# ── Config from centralized settings ─────────────────────────────────────────

JWT_SECRET = settings.JWT_SECRET
JWT_ALGORITHM = settings.JWT_ALGORITHM
JWT_ACCESS_TTL_MINUTES = settings.JWT_ACCESS_TTL_MINUTES
JWT_REFRESH_TTL_DAYS = settings.JWT_REFRESH_TTL_DAYS


def _get_jwt_secret() -> str:
    """Get JWT secret, raising if not configured."""
    secret = settings.JWT_SECRET
    if not secret:
        raise HTTPException(
            status_code=500,
            detail="JWT_SECRET not configured. Set JWT_SECRET in .env"
        )
    return secret


# ── Roles & Permissions ──────────────────────────────────────────────────────


class UserRole(str, Enum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


class Permission(str, Enum):
    # Read
    READ_DASHBOARD = "read:dashboard"
    READ_DECISIONS = "read:decisions"
    READ_AUDIT = "read:audit"
    READ_CREATIVES = "read:creatives"
    READ_SATURATION = "read:saturation"
    READ_OPPORTUNITIES = "read:opportunities"
    READ_POLICIES = "read:policies"
    READ_ORGS = "read:orgs"
    # Write
    CREATE_DECISIONS = "create:decisions"
    APPROVE_DECISIONS = "approve:decisions"
    EXECUTE_DECISIONS = "execute:decisions"
    UPLOAD_DATA = "upload:data"
    # Admin
    MANAGE_ORGS = "manage:orgs"
    MANAGE_USERS = "manage:users"
    MANAGE_SETTINGS = "manage:settings"
    CONNECT_META = "connect:meta"


ROLE_PERMISSIONS = {
    UserRole.VIEWER: [
        Permission.READ_DASHBOARD,
        Permission.READ_DECISIONS,
        Permission.READ_AUDIT,
        Permission.READ_CREATIVES,
        Permission.READ_SATURATION,
        Permission.READ_OPPORTUNITIES,
        Permission.READ_POLICIES,
        Permission.READ_ORGS,
    ],
    UserRole.OPERATOR: [
        Permission.READ_DASHBOARD,
        Permission.READ_DECISIONS,
        Permission.READ_AUDIT,
        Permission.READ_CREATIVES,
        Permission.READ_SATURATION,
        Permission.READ_OPPORTUNITIES,
        Permission.READ_POLICIES,
        Permission.READ_ORGS,
        Permission.CREATE_DECISIONS,
        Permission.APPROVE_DECISIONS,
        Permission.UPLOAD_DATA,
    ],
    UserRole.ADMIN: list(Permission),  # All permissions
}


# ── Password hashing ────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Hash password with bcrypt (12 rounds)."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against bcrypt hash. Falls back to legacy SHA-256 for migration."""
    # Try bcrypt first (new hashes start with $2b$)
    if hashed.startswith("$2b$") or hashed.startswith("$2a$"):
        return bcrypt.checkpw(password.encode(), hashed.encode())
    # Legacy SHA-256 fallback for existing users
    salt = settings.PASSWORD_SALT
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() == hashed


# ── JWT Token Creation ───────────────────────────────────────────────────────


def create_access_token(
    user_id: str,
    email: str,
    role: str,
    org_id: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a real signed JWT access token."""
    secret = _get_jwt_secret()
    if expires_delta is None:
        expires_delta = timedelta(minutes=JWT_ACCESS_TTL_MINUTES)

    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "org_id": org_id,
        "type": "access",
        "jti": str(uuid4()),
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """Create a longer-lived refresh token."""
    secret = _get_jwt_secret()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "jti": str(uuid4()),
        "iat": now,
        "exp": now + timedelta(days=JWT_REFRESH_TTL_DAYS),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises HTTPException on failure."""
    secret = _get_jwt_secret()
    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ── FastAPI Dependencies ─────────────────────────────────────────────────────

security = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> dict:
    """
    Extract and validate user from real JWT token.
    No mock users. Token required on all protected endpoints.
    Logs user_id + role + trace_id on every request.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")

    payload = decode_token(credentials.credentials)

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_id = payload.get("sub")
    role_str = payload.get("role")
    org_id = payload.get("org_id")
    email = payload.get("email")

    if not user_id or not role_str:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    # Validate role is known
    try:
        role = UserRole(role_str)
    except ValueError:
        raise HTTPException(status_code=401, detail=f"Unknown role: {role_str}")

    # Check token revocation (if jti present — backward compat for old tokens)
    jti = payload.get("jti")
    if jti:
        from backend.src.database.models import RevokedToken
        revoked = db.query(RevokedToken).filter(RevokedToken.jti == jti).first()
        if revoked:
            raise HTTPException(status_code=401, detail="Token has been revoked")

    # Verify user still exists in DB
    from uuid import UUID as PyUUID
    from backend.src.database.models import User
    try:
        user_uuid = PyUUID(user_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=401, detail="Invalid user ID in token")
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Log the authenticated request
    trace_id = getattr(request.state, "trace_id", "no-trace")
    logger.info(
        f"AUTH | user_id={user_id} | role={role_str} | email={email} | "
        f"path={request.url.path} | trace_id={trace_id}"
    )

    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "role": role,
        "org_id": org_id,
    }


def require_role(allowed_roles: List[UserRole]):
    """Dependency to require specific role(s) for endpoint access."""
    def role_checker(user: dict = Depends(get_current_user)):
        user_role = user.get("role")
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required role: {[r.value for r in allowed_roles]}"
            )
        return user
    return role_checker


def require_permission(required_permission: Permission):
    """Dependency to require specific permission for endpoint access."""
    def permission_checker(user: dict = Depends(get_current_user)):
        user_role = user.get("role")
        user_permissions = ROLE_PERMISSIONS.get(user_role, [])
        if required_permission not in user_permissions:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required: {required_permission.value}"
            )
        return user
    return permission_checker


# ── Convenience Dependencies ─────────────────────────────────────────────────

require_admin = require_role([UserRole.ADMIN])
require_operator_or_admin = require_role([UserRole.OPERATOR, UserRole.ADMIN])
require_any_authenticated = require_role([UserRole.VIEWER, UserRole.OPERATOR, UserRole.ADMIN])
