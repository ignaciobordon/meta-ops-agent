"""
Sprint 6 – BLOQUE B: Meta Marketing API Client
Wraps all Meta Graph API calls with safe_call + rate limit handling + token refresh.
Tokens are NEVER logged.
"""
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from backend.src.database.models import MetaAlert, MetaConnection, AlertSeverity
from backend.src.utils.resilience import CircuitBreaker, safe_call_sync
from backend.src.utils.token_crypto import decrypt_token
from src.utils.logging_config import logger

# Module-level circuit breaker shared across calls
_meta_cb = CircuitBreaker(failure_threshold=5, cooldown_seconds=120)

# Meta Graph API base
META_API_VERSION = "v21.0"
META_BASE_URL = f"https://graph.facebook.com/{META_API_VERSION}"

# Default fields per entity type
CAMPAIGN_FIELDS = [
    "id", "name", "objective", "status", "effective_status",
    "daily_budget", "lifetime_budget", "bid_strategy",
    "created_time", "updated_time",
]

ADSET_FIELDS = [
    "id", "name", "campaign_id", "status", "effective_status",
    "daily_budget", "lifetime_budget", "optimization_goal",
    "billing_event", "start_time", "end_time",
]

AD_FIELDS = [
    "id", "name", "adset_id", "status", "effective_status",
    "creative{id}",
]

INSIGHT_FIELDS = [
    "spend", "impressions", "clicks", "ctr", "cpm", "cpc",
    "frequency", "actions", "conversions", "purchase_roas",
]


class MetaRateLimitError(Exception):
    """Raised when Meta returns rate limit headers or error codes."""
    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


class MetaTokenExpiredError(Exception):
    """Raised when Meta returns 190 (token expired) or 102 (session invalidated)."""
    pass


class MetaApiClient:
    """
    Meta Marketing API client with resilience patterns.
    Never calls Meta API directly — always via safe_call_sync with circuit breaker.
    """

    def __init__(self, db: Session, connection: MetaConnection):
        self.db = db
        self.connection = connection
        self._access_token: Optional[str] = None

    def _get_token(self) -> str:
        """Decrypt access token. Never cache across requests for security."""
        if not self._access_token:
            self._access_token = decrypt_token(self.connection.access_token_encrypted)
        return self._access_token

    def _check_token_expiry(self):
        """Check if token is expired before making a call."""
        if self.connection.token_expires_at and self.connection.token_expires_at < datetime.utcnow():
            self._mark_needs_reauth("Token expired (token_expires_at passed)")
            raise MetaTokenExpiredError("Access token has expired")

    def _mark_needs_reauth(self, reason: str):
        """Mark connection as expired and create an alert."""
        self.connection.status = "expired"
        alert = MetaAlert(
            org_id=self.connection.org_id,
            alert_type="reauth_required",
            severity=AlertSeverity.CRITICAL,
            message=f"Meta connection needs re-authentication: {reason}",
            detected_at=datetime.utcnow(),
        )
        self.db.add(alert)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
        logger.warning(
            "META_TOKEN_EXPIRED | org_id={} | connection_id={} | reason={}",
            self.connection.org_id, self.connection.id, reason,
        )

    def _do_request(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single HTTP GET to Meta Graph API (sync, called via safe_call)."""
        import httpx

        self._check_token_expiry()

        params["access_token"] = self._get_token()
        resp = httpx.get(url, params=params, timeout=30)

        # Handle rate limiting
        if resp.status_code == 429 or (
            resp.status_code == 400
            and resp.json().get("error", {}).get("code") in (4, 17, 32)
        ):
            retry_after = int(resp.headers.get("Retry-After", "60"))
            raise MetaRateLimitError(
                f"Meta rate limited: {resp.status_code}", retry_after=retry_after
            )

        # Handle token expiration
        if resp.status_code == 400:
            error_data = resp.json().get("error", {})
            if error_data.get("code") in (190, 102):
                self._mark_needs_reauth(error_data.get("message", "Token invalid"))
                raise MetaTokenExpiredError(error_data.get("message", "Token invalid"))

        resp.raise_for_status()
        return resp.json()

    def _paginated_get(
        self, url: str, params: Dict[str, Any], limit: int = 500
    ) -> List[Dict[str, Any]]:
        """Fetch all pages from a paginated Meta API endpoint."""
        all_data: List[Dict[str, Any]] = []
        params["limit"] = min(limit, 500)

        while url:
            result = safe_call_sync(
                self._do_request,
                url,
                params,
                timeout_seconds=30,
                max_retries=2,
                backoff_base=2.0,
                circuit_breaker=_meta_cb,
            )
            all_data.extend(result.get("data", []))

            # Follow pagination cursor
            paging = result.get("paging", {})
            url = paging.get("next")
            params = {}  # next URL contains all params

            if len(all_data) >= 10000:
                logger.warning("META_PAGINATION_LIMIT | Stopping at 10k records")
                break

        return all_data

    # ── Public API Methods ────────────────────────────────────────────────────

    def get_ad_accounts(self) -> List[Dict[str, Any]]:
        """Get ad accounts for the connected user."""
        url = f"{META_BASE_URL}/me/adaccounts"
        params = {"fields": "account_id,name,currency,timezone_name,account_status"}
        return self._paginated_get(url, params)

    def get_campaigns(
        self, ad_account_meta_id: str, fields: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Get campaigns for an ad account."""
        url = f"{META_BASE_URL}/{ad_account_meta_id}/campaigns"
        params = {"fields": ",".join(fields or CAMPAIGN_FIELDS)}
        return self._paginated_get(url, params)

    def get_adsets(
        self, ad_account_meta_id: str, fields: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Get adsets for an ad account."""
        url = f"{META_BASE_URL}/{ad_account_meta_id}/adsets"
        params = {"fields": ",".join(fields or ADSET_FIELDS)}
        return self._paginated_get(url, params)

    def get_ads(
        self, ad_account_meta_id: str, fields: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Get ads for an ad account."""
        url = f"{META_BASE_URL}/{ad_account_meta_id}/ads"
        params = {"fields": ",".join(fields or AD_FIELDS)}
        return self._paginated_get(url, params)

    def get_insights(
        self,
        ad_account_meta_id: str,
        level: str = "campaign",
        time_range: Optional[Dict[str, str]] = None,
        date_preset: Optional[str] = None,
        fields: Optional[List[str]] = None,
        breakdowns: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get insights (performance data) for an ad account."""
        url = f"{META_BASE_URL}/{ad_account_meta_id}/insights"
        # Ensure entity ID field is included so rows can be linked to entities
        requested_fields = list(fields or INSIGHT_FIELDS)
        level_id_field = {"campaign": "campaign_id", "adset": "adset_id", "ad": "ad_id"}.get(level)
        if level_id_field and level_id_field not in requested_fields:
            requested_fields.append(level_id_field)
        params: Dict[str, Any] = {
            "fields": ",".join(requested_fields),
            "level": level,
        }

        if time_range:
            import json
            params["time_range"] = json.dumps(time_range)
        elif date_preset:
            params["date_preset"] = date_preset
        else:
            params["date_preset"] = "last_7d"

        if breakdowns:
            params["breakdowns"] = ",".join(breakdowns)

        params["time_increment"] = 1  # Daily breakdown

        return self._paginated_get(url, params)
