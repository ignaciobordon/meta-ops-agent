"""
FASE 5.4: Meta OAuth + Multi-Account API endpoints.
Safe mode: connection, persistence, account selection, data reading (ads_read).
No live mutations.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.src.adapters.meta_oauth import MetaOAuthAdapter
from backend.src.config import settings
from backend.src.database.models import AdAccount, MetaConnection, ConnectionStatus
from backend.src.database.session import get_db
from backend.src.middleware.auth import (
    Permission,
    get_current_user,
    require_any_authenticated,
    require_permission,
)
from backend.src.services.meta_service import MetaService
from src.utils.logging_config import logger

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────


class OAuthStartResponse(BaseModel):
    authorization_url: str
    message: str = "Redirect user to this URL to begin Meta OAuth"


class AdAccountResponse(BaseModel):
    id: UUID
    meta_ad_account_id: str
    name: str
    currency: str
    spend_cap: Optional[float] = None
    meta_metadata: Optional[dict] = None
    synced_at: Optional[datetime] = None
    is_active: bool = False

    class Config:
        from_attributes = True


class SelectAccountRequest(BaseModel):
    ad_account_id: UUID


class SelectAccountResponse(BaseModel):
    org_id: UUID
    active_ad_account_id: UUID
    active_ad_account_name: str
    message: str = "Active ad account updated"


class ActiveAccountResponse(BaseModel):
    ad_account_id: Optional[UUID] = None
    meta_ad_account_id: Optional[str] = None
    name: Optional[str] = None
    currency: Optional[str] = None
    connection_status: Optional[str] = None
    has_active_account: bool = False


class MetaVerifyResponse(BaseModel):
    connected: bool
    connection_status: Optional[str] = None
    ad_accounts_count: int = 0
    api_reachable: bool = False
    error: Optional[str] = None
    token_valid: bool = False
    scopes: List[str] = []
    meta_user_id: Optional[str] = None
    meta_user_name: Optional[str] = None
    token_expires_at: Optional[str] = None
    recommended_fix: Optional[str] = None


class DebugTokenResponse(BaseModel):
    is_valid: bool
    app_id: Optional[str] = None
    user_id: Optional[str] = None
    scopes: List[str] = []
    expires_at: Optional[str] = None
    issued_at: Optional[str] = None
    data_access_expires_at: Optional[str] = None
    granular_scopes: Optional[List[dict]] = None
    error: Optional[str] = None


# ── Helper ────────────────────────────────────────────────────────────────────


def _get_adapter() -> MetaOAuthAdapter:
    """Create adapter from centralized settings."""
    app_id = settings.META_APP_ID
    app_secret = settings.META_APP_SECRET
    redirect_uri = settings.META_OAUTH_REDIRECT_URI
    scopes = settings.META_OAUTH_SCOPES
    if not app_id or not app_secret:
        raise HTTPException(
            status_code=500,
            detail="META_APP_ID and META_APP_SECRET must be configured",
        )
    if app_id.startswith("REPLACE_") or app_secret.startswith("REPLACE_"):
        raise HTTPException(
            status_code=500,
            detail="META_APP_ID and META_APP_SECRET contain placeholder values. "
                   "Set real credentials from developers.facebook.com in .env",
        )
    return MetaOAuthAdapter(
        app_id=app_id,
        app_secret=app_secret,
        redirect_uri=redirect_uri,
        scopes=scopes,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/oauth/start",
    response_model=OAuthStartResponse,
    dependencies=[Depends(require_permission(Permission.CONNECT_META))],
)
def oauth_start(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Initiate Meta OAuth flow. Admin only (CONNECT_META permission).
    Returns the Meta authorization URL for the frontend to redirect to.
    """
    adapter = _get_adapter()
    service = MetaService(db=db, adapter=adapter)

    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no associated organization")

    url = service.generate_oauth_url(
        org_id=UUID(org_id),
        user_id=UUID(user["id"]),
    )
    return OAuthStartResponse(authorization_url=url)


@router.get("/oauth/callback")
async def oauth_callback(
    code: str = Query(..., description="Authorization code from Meta"),
    state: str = Query(..., description="CSRF state token"),
    db: Session = Depends(get_db),
):
    """
    OAuth callback from Meta. Exchanges code for tokens, syncs ad accounts.
    This endpoint is called by Meta's redirect, not by the frontend directly.
    On success, redirects to frontend with success indicator.
    """
    adapter = _get_adapter()
    service = MetaService(db=db, adapter=adapter)

    frontend_url = settings.FRONTEND_URL.rstrip("/")

    try:
        connection = await service.complete_oauth(code=code, state=state)
        logger.info(
            "META_OAUTH_SUCCESS | accounts={} | connection_id={}",
            len(connection.ad_accounts), connection.id,
        )
        return RedirectResponse(
            url=(
                f"{frontend_url}/control-panel?meta_connected=true"
                f"&connection_id={connection.id}"
                f"&accounts={len(connection.ad_accounts)}"
            )
        )
    except ValueError as e:
        logger.warning(
            "META_OAUTH_VALUE_ERROR | error_type=validation | error={}",
            str(e)[:200],
        )
        return RedirectResponse(
            url=f"{frontend_url}/control-panel?meta_error={str(e)}&error_type=validation"
        )
    except Exception as e:
        logger.error(
            "META_OAUTH_FAILED | error_type=unexpected | error={}",
            str(e)[:200],
        )
        return RedirectResponse(
            url=f"{frontend_url}/control-panel?meta_error=connection_failed&error_type=unexpected"
        )


@router.get(
    "/adaccounts",
    response_model=List[AdAccountResponse],
    dependencies=[Depends(require_any_authenticated)],
)
def list_ad_accounts(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List all ad accounts for the current user's org.
    Any authenticated user can view.
    """
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no associated organization")

    adapter = _get_adapter()
    service = MetaService(db=db, adapter=adapter)
    accounts = service.list_org_ad_accounts(UUID(org_id))

    # Get active account to mark is_active
    active = service.get_active_account(UUID(org_id))
    active_id = active.id if active else None

    return [
        AdAccountResponse(
            id=a.id,
            meta_ad_account_id=a.meta_ad_account_id,
            name=a.name,
            currency=a.currency,
            spend_cap=a.spend_cap,
            meta_metadata=a.meta_metadata,
            synced_at=a.synced_at,
            is_active=(a.id == active_id),
        )
        for a in accounts
    ]


@router.post(
    "/adaccounts/select",
    response_model=SelectAccountResponse,
    dependencies=[Depends(require_any_authenticated)],
)
def select_ad_account(
    body: SelectAccountRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Set the active ad account for the current org.
    Any authenticated user can select (decisions are org-level).
    """
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no associated organization")

    adapter = _get_adapter()
    service = MetaService(db=db, adapter=adapter)

    try:
        service.select_active_account(
            org_id=UUID(org_id),
            ad_account_id=body.ad_account_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Get the account name for response
    account = db.query(AdAccount).filter(AdAccount.id == body.ad_account_id).first()

    return SelectAccountResponse(
        org_id=UUID(org_id),
        active_ad_account_id=body.ad_account_id,
        active_ad_account_name=account.name if account else "Unknown",
    )


@router.get(
    "/adaccounts/active",
    response_model=ActiveAccountResponse,
    dependencies=[Depends(require_any_authenticated)],
)
def get_active_account(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get the currently active ad account for the org.
    Any authenticated user can view.
    """
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no associated organization")

    adapter = _get_adapter()
    service = MetaService(db=db, adapter=adapter)
    account = service.get_active_account(UUID(org_id))

    if not account:
        return ActiveAccountResponse(has_active_account=False)

    # Get connection status
    conn = db.query(MetaConnection).filter(
        MetaConnection.id == account.connection_id
    ).first()

    return ActiveAccountResponse(
        ad_account_id=account.id,
        meta_ad_account_id=account.meta_ad_account_id,
        name=account.name,
        currency=account.currency,
        connection_status=conn.status.value if conn else "unknown",
        has_active_account=True,
    )


@router.get(
    "/verify",
    response_model=MetaVerifyResponse,
    dependencies=[Depends(require_any_authenticated)],
)
async def verify_connection(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Verify Meta connection health by making REAL calls to Meta's Graph API.
    1. Checks local connection exists
    2. Decrypts token
    3. Calls GET /me on Meta to validate token is live
    4. Counts ad accounts in DB
    """
    org_id = user.get("org_id")
    if not org_id:
        return MetaVerifyResponse(connected=False, error="No org_id in token")

    conn = (
        db.query(MetaConnection)
        .filter(MetaConnection.org_id == UUID(org_id))
        .first()
    )

    if not conn:
        return MetaVerifyResponse(connected=False, error="No Meta connection found")

    ad_accounts_count = (
        db.query(AdAccount)
        .filter(AdAccount.connection_id == conn.id)
        .count()
    )

    token_valid = False
    api_reachable = False
    error_msg = None
    scopes: List[str] = conn.scopes or []
    recommended_fix = None
    meta_user_id = conn.meta_user_id
    meta_user_name = conn.meta_user_name
    token_expires_at = conn.token_expires_at.isoformat() if conn.token_expires_at else None

    if conn.status == ConnectionStatus.ACTIVE:
        try:
            adapter = _get_adapter()
            service = MetaService(db=db, adapter=adapter)
            access_token = service.get_decrypted_token(conn.id)

            # REAL call to Meta API to verify token is still valid
            live_info = await adapter.verify_token_live(access_token)
            token_valid = True
            api_reachable = True
            meta_user_id = live_info.get("id", meta_user_id)
            meta_user_name = live_info.get("name", meta_user_name)

            logger.info(
                "META_VERIFY_OK | org={} | meta_user={} | accounts={}",
                org_id, meta_user_name, ad_accounts_count,
            )
        except ValueError as e:
            error_msg = str(e)[:200]
            error_lower = error_msg.lower()
            if "expired" in error_lower or "code=190" in error_lower:
                conn.status = ConnectionStatus.EXPIRED
                db.commit()
                recommended_fix = "Token expired. Re-authenticate with Meta via Settings > Connect Meta."
            elif "not active" in error_lower:
                recommended_fix = "Connection is not active. Reconnect your Meta account."
            else:
                recommended_fix = "Token validation failed against Meta API. Try reconnecting."
        except Exception as e:
            error_msg = str(e)[:200]
            logger.warning("META_VERIFY_FAILED | org={} | error={}", org_id, error_msg)
            recommended_fix = "Could not reach Meta API. Check internet connection or try again."
    elif conn.status == ConnectionStatus.EXPIRED:
        recommended_fix = "Token expired. Re-authenticate with Meta via Settings > Connect Meta."
    elif conn.status == ConnectionStatus.REVOKED:
        recommended_fix = "Access was revoked. Reconnect your Meta account and re-authorize."

    return MetaVerifyResponse(
        connected=conn.status == ConnectionStatus.ACTIVE and token_valid,
        connection_status=conn.status.value,
        ad_accounts_count=ad_accounts_count,
        api_reachable=api_reachable,
        error=error_msg,
        token_valid=token_valid,
        scopes=scopes,
        meta_user_id=meta_user_id,
        meta_user_name=meta_user_name,
        token_expires_at=token_expires_at,
        recommended_fix=recommended_fix,
    )


@router.get(
    "/debug-token",
    response_model=DebugTokenResponse,
    dependencies=[Depends(require_permission(Permission.CONNECT_META))],
)
async def debug_token_endpoint(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Inspect the current Meta access token via Meta's /debug_token API.
    Returns real permissions, scopes, app_id, expiration, and validity.
    Admin only (CONNECT_META permission).
    """
    org_id = user.get("org_id")
    if not org_id:
        return DebugTokenResponse(is_valid=False, error="No org_id in token")

    conn = (
        db.query(MetaConnection)
        .filter(
            MetaConnection.org_id == UUID(org_id),
            MetaConnection.status == ConnectionStatus.ACTIVE,
        )
        .first()
    )
    if not conn:
        return DebugTokenResponse(is_valid=False, error="No active Meta connection found")

    try:
        adapter = _get_adapter()
        service = MetaService(db=db, adapter=adapter)
        access_token = service.get_decrypted_token(conn.id)

        debug_data = await adapter.debug_token(access_token)
        token_info = debug_data.get("data", {})

        from datetime import datetime, timezone
        expires_at = None
        if token_info.get("expires_at"):
            expires_at = datetime.fromtimestamp(
                token_info["expires_at"], tz=timezone.utc
            ).isoformat()

        issued_at = None
        if token_info.get("issued_at"):
            issued_at = datetime.fromtimestamp(
                token_info["issued_at"], tz=timezone.utc
            ).isoformat()

        data_access_expires = None
        if token_info.get("data_access_expires_at"):
            data_access_expires = datetime.fromtimestamp(
                token_info["data_access_expires_at"], tz=timezone.utc
            ).isoformat()

        return DebugTokenResponse(
            is_valid=token_info.get("is_valid", False),
            app_id=token_info.get("app_id"),
            user_id=token_info.get("user_id"),
            scopes=token_info.get("scopes", []),
            expires_at=expires_at,
            issued_at=issued_at,
            data_access_expires_at=data_access_expires,
            granular_scopes=token_info.get("granular_scopes"),
        )
    except Exception as e:
        logger.error("META_DEBUG_TOKEN_FAILED | org={} | error={}", org_id, str(e)[:200])
        return DebugTokenResponse(is_valid=False, error=str(e)[:200])
