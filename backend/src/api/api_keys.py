"""API Key management endpoints — CRUD + org-scoped authentication."""
import hashlib
import secrets
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.src.database.models import ApiKey
from backend.src.database.session import get_db
from backend.src.middleware.auth import require_admin, get_current_user

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────


class ApiKeyCreate(BaseModel):
    name: str
    scopes: List[str] = ["read"]
    expires_in_days: Optional[int] = None


class ApiKeyCreatedResponse(BaseModel):
    """Returned ONCE on creation — includes plaintext key."""
    id: str
    name: str
    key: str  # plaintext — only shown once
    key_prefix: str
    scopes: List[str]
    expires_at: Optional[str] = None
    created_at: str


class ApiKeyResponse(BaseModel):
    """Public view — key is masked."""
    id: str
    name: str
    key_prefix: str
    scopes: List[str]
    last_used_at: Optional[str] = None
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None
    created_at: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _hash_key(raw_key: str) -> str:
    """SHA-256 hash of API key for storage."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _generate_key() -> str:
    """Generate moa_ prefixed API key: moa_ + 32 hex chars."""
    return f"moa_{secrets.token_hex(16)}"


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/", response_model=ApiKeyCreatedResponse, dependencies=[Depends(require_admin)])
def create_api_key(
    body: ApiKeyCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a new API key. Admin only. Returns plaintext key ONCE."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization associated with user")

    raw_key = _generate_key()
    key_hash = _hash_key(raw_key)
    key_prefix = raw_key[:8]  # "moa_xxxx"

    expires_at = None
    if body.expires_in_days:
        from datetime import timedelta
        expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)

    api_key = ApiKey(
        id=uuid4(),
        org_id=UUID(org_id),
        created_by_user_id=UUID(user["id"]),
        name=body.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        scopes=body.scopes,
        expires_at=expires_at,
        created_at=datetime.now(timezone.utc),
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    return ApiKeyCreatedResponse(
        id=str(api_key.id),
        name=api_key.name,
        key=raw_key,
        key_prefix=key_prefix,
        scopes=api_key.scopes or ["read"],
        expires_at=api_key.expires_at.isoformat() if api_key.expires_at else None,
        created_at=api_key.created_at.isoformat(),
    )


@router.get("/", response_model=List[ApiKeyResponse])
def list_api_keys(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List API keys for current organization (masked)."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization associated with user")

    keys = db.query(ApiKey).filter(
        ApiKey.org_id == UUID(org_id),
        ApiKey.revoked_at.is_(None),
    ).order_by(ApiKey.created_at.desc()).all()

    return [
        ApiKeyResponse(
            id=str(k.id),
            name=k.name,
            key_prefix=k.key_prefix,
            scopes=k.scopes or ["read"],
            last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
            expires_at=k.expires_at.isoformat() if k.expires_at else None,
            revoked_at=None,
            created_at=k.created_at.isoformat() if k.created_at else "",
        )
        for k in keys
    ]


@router.delete("/{key_id}", dependencies=[Depends(require_admin)])
def revoke_api_key(
    key_id: UUID,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke an API key. Admin only."""
    org_id = user.get("org_id", "")
    api_key = db.query(ApiKey).filter(
        ApiKey.id == key_id,
        ApiKey.org_id == UUID(org_id),
    ).first()

    if not api_key:
        raise HTTPException(404, "API key not found")

    api_key.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"message": "API key revoked"}


# ── API Key Authentication Helper ────────────────────────────────────────────


def authenticate_api_key(raw_key: str, db: Session) -> dict:
    """
    Authenticate a request using an API key.
    Returns a user-like dict with org_id and scopes.
    Used by rate_limit middleware and can be used as auth fallback.
    """
    key_hash = _hash_key(raw_key)
    api_key = db.query(ApiKey).filter(
        ApiKey.key_hash == key_hash,
        ApiKey.revoked_at.is_(None),
    ).first()

    if not api_key:
        return None

    # Check expiration
    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        return None

    # Update last_used_at
    api_key.last_used_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "org_id": str(api_key.org_id),
        "key_id": str(api_key.id),
        "scopes": api_key.scopes or ["read"],
        "name": api_key.name,
    }
