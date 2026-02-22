"""
Meta OAuth Service - orchestrates OAuth flow, token persistence,
ad account syncing, and account selection.
FASE 5.4: Read-only. No live mutations to Meta.
"""
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from backend.src.adapters.meta_oauth import MetaOAuthAdapter
from backend.src.database.models import (
    AdAccount, ConnectionStatus, MetaConnection, Organization,
)
from backend.src.utils.token_crypto import decrypt_token, encrypt_token
from src.utils.logging_config import logger


# In-memory OAuth state store.
# Production: use Redis or DB-backed store.
_oauth_states: Dict[str, Dict[str, Any]] = {}
STATE_TTL_SECONDS = 300  # 5 minutes


class MetaService:
    """Manages Meta connections, OAuth flow, and ad account selection."""

    def __init__(self, db: Session, adapter: MetaOAuthAdapter):
        self.db = db
        self.adapter = adapter

    # ── OAuth Flow ─────────────────────────────────────────────────────

    def generate_oauth_url(self, org_id: UUID, user_id: UUID) -> str:
        """
        Generate OAuth authorization URL with CSRF state token.
        Returns the URL the frontend should redirect/navigate to.
        """
        state = secrets.token_hex(32)
        _oauth_states[state] = {
            "org_id": str(org_id),
            "user_id": str(user_id),
            "created_at": time.time(),
        }
        self._cleanup_expired_states()

        url = self.adapter.get_authorization_url(state)
        logger.info(
            f"META_OAUTH_START | org_id={org_id} | user_id={user_id} | state={state[:8]}..."
        )
        return url

    @staticmethod
    def validate_state(state: str) -> Optional[Dict[str, Any]]:
        """Validate and consume OAuth state token. Returns state data or None.
        Handles URL encoding artifacts (e.g. '+' injected by redirect chain).
        """
        # Try exact match first
        data = _oauth_states.pop(state, None)
        if not data:
            # Normalize: strip '+' and spaces that may be injected during redirect
            normalized = state.replace("+", "").replace(" ", "")
            data = _oauth_states.pop(normalized, None)
        if not data:
            # Try matching against all stored states with normalization
            for stored_state in list(_oauth_states.keys()):
                if stored_state.replace("+", "").replace(" ", "") == state.replace("+", "").replace(" ", ""):
                    data = _oauth_states.pop(stored_state, None)
                    break
        if not data:
            return None
        if time.time() - data["created_at"] > STATE_TTL_SECONDS:
            return None
        return data

    async def complete_oauth(self, code: str, state: str) -> MetaConnection:
        """
        Complete OAuth callback:
        1. Validate state
        2. Exchange code for short-lived token
        3. Exchange for long-lived token
        4. Get Meta user info
        5. Encrypt and persist tokens
        6. Sync ad accounts
        """
        # 1. Validate state
        state_data = self.validate_state(state)
        if not state_data:
            raise ValueError("Invalid or expired OAuth state")

        org_id = UUID(state_data["org_id"])
        user_id = UUID(state_data["user_id"])

        # 2. Exchange code for short-lived token
        token_data = await self.adapter.exchange_code_for_token(code)
        short_token = token_data["access_token"]

        # 3. Exchange for long-lived token
        long_data = await self.adapter.exchange_for_long_lived_token(short_token)
        access_token = long_data["access_token"]
        expires_in = long_data.get("expires_in", 5184000)  # default ~60 days

        # 4. Get Meta user info
        user_info = await self.adapter.get_user_info(access_token)

        # 5. Encrypt and persist
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        granted_scopes = [s.strip() for s in self.adapter.scopes.split(",") if s.strip()]

        connection = MetaConnection(
            id=uuid4(),
            org_id=org_id,
            connected_by_user_id=user_id,
            access_token_encrypted=encrypt_token(access_token),
            token_expires_at=expires_at,
            scopes=granted_scopes,
            status=ConnectionStatus.ACTIVE,
            meta_user_id=user_info.get("id"),
            meta_user_name=user_info.get("name"),
            connected_at=datetime.now(timezone.utc),
        )
        self.db.add(connection)
        self.db.flush()

        # 6. Sync ad accounts (non-fatal — connection is saved even if sync fails)
        try:
            await self._sync_ad_accounts(connection, access_token)
        except Exception as e:
            logger.warning(
                f"META_OAUTH | ad_account_sync_failed | connection_id={connection.id} | "
                f"error={str(e)[:200]}. Connection saved without ad accounts."
            )

        self.db.commit()
        self.db.refresh(connection)

        logger.info(
            f"META_OAUTH_COMPLETE | connection_id={connection.id} | "
            f"org_id={org_id} | user_id={user_id} | "
            f"meta_user={user_info.get('name')} | "
            f"accounts_synced={len(connection.ad_accounts)}"
        )
        return connection

    # ── Ad Account Management ──────────────────────────────────────────

    async def _sync_ad_accounts(
        self, connection: MetaConnection, access_token: str
    ) -> List[AdAccount]:
        """Fetch ad accounts from Meta and upsert into DB."""
        raw_accounts = await self.adapter.list_ad_accounts(access_token)
        synced = []
        for acct in raw_accounts:
            meta_id = acct["id"]  # e.g. "act_123456789"
            # Upsert: check if this meta_ad_account_id already exists
            existing = (
                self.db.query(AdAccount)
                .filter(AdAccount.meta_ad_account_id == meta_id)
                .first()
            )
            if existing:
                existing.name = acct.get("name", existing.name)
                existing.currency = acct.get("currency", existing.currency)
                existing.spend_cap = (
                    float(acct["spend_cap"]) / 100
                    if acct.get("spend_cap")
                    else None
                )
                existing.meta_metadata = {
                    "timezone": acct.get("timezone_name"),
                    "account_status": acct.get("account_status"),
                }
                existing.synced_at = datetime.now(timezone.utc)
                existing.connection_id = connection.id
                synced.append(existing)
            else:
                ad_account = AdAccount(
                    id=uuid4(),
                    connection_id=connection.id,
                    meta_ad_account_id=meta_id,
                    name=acct.get("name", meta_id),
                    currency=acct.get("currency", "USD"),
                    spend_cap=(
                        float(acct["spend_cap"]) / 100
                        if acct.get("spend_cap")
                        else None
                    ),
                    meta_metadata={
                        "timezone": acct.get("timezone_name"),
                        "account_status": acct.get("account_status"),
                    },
                    synced_at=datetime.now(timezone.utc),
                )
                self.db.add(ad_account)
                synced.append(ad_account)
        return synced

    def list_org_ad_accounts(self, org_id: UUID) -> List[AdAccount]:
        """List all ad accounts for an org (across all active connections)."""
        connections = (
            self.db.query(MetaConnection)
            .filter(
                MetaConnection.org_id == org_id,
                MetaConnection.status == ConnectionStatus.ACTIVE,
            )
            .all()
        )
        conn_ids = [c.id for c in connections]
        if not conn_ids:
            return []
        return (
            self.db.query(AdAccount)
            .filter(AdAccount.connection_id.in_(conn_ids))
            .all()
        )

    def select_active_account(
        self, org_id: UUID, ad_account_id: UUID
    ) -> Organization:
        """Set the active ad account for an org."""
        org = self.db.query(Organization).filter(Organization.id == org_id).first()
        if not org:
            raise ValueError(f"Organization {org_id} not found")

        # Verify the ad account exists
        ad_account = (
            self.db.query(AdAccount)
            .filter(AdAccount.id == ad_account_id)
            .first()
        )
        if not ad_account:
            raise ValueError(f"Ad account {ad_account_id} not found")

        # Verify it belongs to this org
        connection = (
            self.db.query(MetaConnection)
            .filter(MetaConnection.id == ad_account.connection_id)
            .first()
        )
        if not connection or connection.org_id != org_id:
            raise ValueError("Ad account does not belong to this organization")

        org.active_ad_account_id = ad_account_id
        self.db.commit()
        self.db.refresh(org)

        logger.info(
            f"META_ACCOUNT_SELECTED | org_id={org_id} | "
            f"ad_account_id={ad_account_id} | name={ad_account.name}"
        )
        return org

    def get_active_account(self, org_id: UUID) -> Optional[AdAccount]:
        """Get the currently active ad account for an org."""
        org = self.db.query(Organization).filter(Organization.id == org_id).first()
        if not org or not org.active_ad_account_id:
            return None
        return (
            self.db.query(AdAccount)
            .filter(AdAccount.id == org.active_ad_account_id)
            .first()
        )

    def get_decrypted_token(self, connection_id: UUID) -> str:
        """
        Decrypt and return the access token for a connection.
        Checks expiry. Returns token or raises.
        """
        conn = (
            self.db.query(MetaConnection)
            .filter(MetaConnection.id == connection_id)
            .first()
        )
        if not conn:
            raise ValueError(f"Connection {connection_id} not found")

        if conn.status != ConnectionStatus.ACTIVE:
            raise ValueError(f"Connection status is {conn.status.value}, not active")

        if conn.token_expires_at and conn.token_expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            conn.status = ConnectionStatus.EXPIRED
            self.db.commit()
            raise ValueError("Token has expired. Please re-authenticate with Meta.")

        return decrypt_token(conn.access_token_encrypted)

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _cleanup_expired_states():
        """Remove expired OAuth states from memory."""
        now = time.time()
        expired = [
            k for k, v in _oauth_states.items()
            if now - v["created_at"] > STATE_TTL_SECONDS
        ]
        for k in expired:
            _oauth_states.pop(k, None)
