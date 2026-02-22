"""
Meta OAuth Adapter - handles HTTP communication with Meta Graph API.
Scopes: ads_read only (FASE 5.4 is read-only).
No live mutations. Safe mode by default.
"""
from typing import Any, Dict, List
from urllib.parse import urlencode

import httpx

from src.utils.logging_config import logger


META_GRAPH_BASE = "https://graph.facebook.com"
META_GRAPH_VERSION = "v21.0"
META_OAUTH_DIALOG = "https://www.facebook.com"


class MetaOAuthAdapter:
    """Stateless adapter for Meta OAuth and Graph API read operations."""

    def __init__(self, app_id: str, app_secret: str, redirect_uri: str, scopes: str = "ads_read"):
        self.app_id = app_id
        self.app_secret = app_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes

    def get_authorization_url(self, state: str) -> str:
        """
        Build the Meta OAuth authorization URL.
        User will be redirected to this URL to grant access.
        Scopes are configurable via META_OAUTH_SCOPES env var.
        """
        params = {
            "client_id": self.app_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "scope": self.scopes,
            "response_type": "code",
        }
        url = f"{META_OAUTH_DIALOG}/{META_GRAPH_VERSION}/dialog/oauth?{urlencode(params)}"
        logger.info(f"META_OAUTH | authorization_url_generated | state={state[:8]}...")
        return url

    async def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """
        Exchange authorization code for short-lived access token.
        Returns: {"access_token": str, "token_type": str, "expires_in": int}
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{META_GRAPH_BASE}/{META_GRAPH_VERSION}/oauth/access_token",
                params={
                    "client_id": self.app_id,
                    "client_secret": self.app_secret,
                    "redirect_uri": self.redirect_uri,
                    "code": code,
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            # NEVER log the token value
            logger.info(
                f"META_OAUTH | code_exchanged | expires_in={data.get('expires_in')}"
            )
            return data

    async def exchange_for_long_lived_token(
        self, short_lived_token: str
    ) -> Dict[str, Any]:
        """
        Exchange short-lived token (~1-2 hours) for long-lived token (~60 days).
        Returns: {"access_token": str, "token_type": str, "expires_in": int}
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{META_GRAPH_BASE}/{META_GRAPH_VERSION}/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": self.app_id,
                    "client_secret": self.app_secret,
                    "fb_exchange_token": short_lived_token,
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(
                f"META_OAUTH | long_lived_token_obtained | expires_in={data.get('expires_in')}"
            )
            return data

    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """
        Get the Meta user info (id, name) for the authenticated user.
        Returns: {"id": str, "name": str}
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{META_GRAPH_BASE}/{META_GRAPH_VERSION}/me",
                params={"access_token": access_token, "fields": "id,name"},
                timeout=15.0,
            )
            resp.raise_for_status()
            return resp.json()

    async def list_ad_accounts(self, access_token: str) -> List[Dict[str, Any]]:
        """
        Fetch all ad accounts accessible by this token.
        Returns list of: {"id": str, "name": str, "currency": str, ...}
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{META_GRAPH_BASE}/{META_GRAPH_VERSION}/me/adaccounts",
                params={
                    "access_token": access_token,
                    "fields": "id,name,currency,spend_cap,timezone_name,account_status",
                    "limit": 100,
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            accounts = data.get("data", [])
            logger.info(
                f"META_OAUTH | ad_accounts_listed | count={len(accounts)}"
            )
            return accounts

    async def debug_token(self, access_token: str) -> Dict[str, Any]:
        """
        Call Meta's GET /debug_token to inspect token permissions, scopes,
        app_id, expiration, and validity.
        Uses app_id|app_secret as the input_token inspector.
        Returns: {"data": {"app_id": str, "is_valid": bool, "scopes": [...], ...}}
        """
        app_token = f"{self.app_id}|{self.app_secret}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{META_GRAPH_BASE}/{META_GRAPH_VERSION}/debug_token",
                params={
                    "input_token": access_token,
                    "access_token": app_token,
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info("META_OAUTH | debug_token_called | is_valid={}".format(
                data.get("data", {}).get("is_valid")
            ))
            return data

    async def verify_token_live(self, access_token: str) -> Dict[str, Any]:
        """
        Make a lightweight GET /me call to verify the token is still valid
        against Meta's servers in real time.
        Returns: {"id": str, "name": str} or raises on invalid token.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{META_GRAPH_BASE}/{META_GRAPH_VERSION}/me",
                params={"access_token": access_token, "fields": "id,name"},
                timeout=10.0,
            )
            if resp.status_code == 400:
                error_data = resp.json().get("error", {})
                raise ValueError(
                    f"Token invalid: {error_data.get('message', 'Unknown error')} "
                    f"(code={error_data.get('code')}, subcode={error_data.get('error_subcode')})"
                )
            resp.raise_for_status()
            return resp.json()
