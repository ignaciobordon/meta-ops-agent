"""
CP7 — Meta API Client
Wrapper around Facebook Marketing API for safe, auditable ad account operations.
Supports DRY_RUN mode for testing without actual execution.
"""
from __future__ import annotations

import os
from typing import Any, Dict

from src.utils.logging_config import logger


class MetaAPIClient:
    """
    Wrapper around Meta Marketing API.

    In DRY_RUN mode (default), simulates API calls without executing.
    In LIVE mode, requires META_ACCESS_TOKEN and executes real changes.
    """

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.access_token = os.getenv("META_ACCESS_TOKEN", "")
        self.ad_account_id = os.getenv("META_AD_ACCOUNT_ID", "")

        if not self.dry_run and not self.access_token:
            raise EnvironmentError(
                "META_ACCESS_TOKEN required for live execution. "
                "Set DRY_RUN=True for testing or provide token."
            )

        # Lazy import Facebook SDK only when needed (not in dry-run)
        self.facebook_business = None
        if not self.dry_run:
            try:
                from facebook_business.api import FacebookAdsApi
                from facebook_business.adobjects.adaccount import AdAccount

                FacebookAdsApi.init(access_token=self.access_token)
                self.ad_account = AdAccount(self.ad_account_id)
                self.facebook_business = True
                logger.info(f"META_API_INITIALIZED | account={self.ad_account_id} | mode=LIVE")
            except ImportError:
                raise ImportError(
                    "facebook-business SDK not installed. "
                    "Run: pip install facebook-business"
                )
        else:
            logger.info("META_API_INITIALIZED | mode=DRY_RUN (no actual execution)")

    # ── Budget Operations ─────────────────────────────────────────────────────

    def update_adset_budget(
        self, adset_id: str, new_budget: float, current_budget: float
    ) -> Dict[str, Any]:
        """Update daily budget for an adset."""
        if self.dry_run:
            return self._simulate_response(
                action="update_adset_budget",
                params={
                    "adset_id": adset_id,
                    "current_budget": current_budget,
                    "new_budget": new_budget,
                },
            )

        # Real execution (requires facebook-business SDK)
        from facebook_business.adobjects.adset import AdSet

        adset = AdSet(adset_id)
        response = adset.api_update(
            fields=[],
            params={"daily_budget": int(new_budget * 100)},  # Cents
        )
        logger.info(
            f"META_API_EXECUTED | action=update_budget "
            f"| adset={adset_id} | budget={new_budget}"
        )
        return response.export_all_data()

    # ── Creative Operations ───────────────────────────────────────────────────

    def pause_ad(self, ad_id: str) -> Dict[str, Any]:
        """Pause an ad."""
        if self.dry_run:
            return self._simulate_response(action="pause_ad", params={"ad_id": ad_id})

        from facebook_business.adobjects.ad import Ad

        ad = Ad(ad_id)
        response = ad.api_update(fields=[], params={"status": "PAUSED"})
        logger.info(f"META_API_EXECUTED | action=pause_ad | ad={ad_id}")
        return response.export_all_data()

    def duplicate_ad(self, ad_id: str, new_name: str) -> Dict[str, Any]:
        """Duplicate an ad (for the 'no direct edit' rule)."""
        if self.dry_run:
            return self._simulate_response(
                action="duplicate_ad", params={"ad_id": ad_id, "new_name": new_name}
            )

        from facebook_business.adobjects.ad import Ad

        ad = Ad(ad_id)
        # Create a copy via the API
        response = ad.create_copy(params={"name": new_name, "status": "PAUSED"})
        logger.info(
            f"META_API_EXECUTED | action=duplicate_ad | original={ad_id} | copy={response.get('id')}"
        )
        return response

    # ── AdSet Operations ──────────────────────────────────────────────────────

    def pause_adset(self, adset_id: str) -> Dict[str, Any]:
        """Pause an adset."""
        if self.dry_run:
            return self._simulate_response(
                action="pause_adset", params={"adset_id": adset_id}
            )

        from facebook_business.adobjects.adset import AdSet

        adset = AdSet(adset_id)
        response = adset.api_update(fields=[], params={"status": "PAUSED"})
        logger.info(f"META_API_EXECUTED | action=pause_adset | adset={adset_id}")
        return response.export_all_data()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _simulate_response(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate a successful API response in dry-run mode."""
        logger.info(
            f"META_API_DRY_RUN | action={action} | params={params} | executed=FALSE"
        )
        return {
            "success": True,
            "dry_run": True,
            "action": action,
            "params": params,
            "simulated_response": {
                "id": f"simulated_{action}_{params.get('adset_id', params.get('ad_id', 'unknown'))}",
                "message": "This is a simulated response. No actual API call was made.",
            },
        }

    def get_adset_status(self, adset_id: str) -> Dict[str, Any]:
        """Fetch current adset status (for rollback validation)."""
        if self.dry_run:
            return {"status": "ACTIVE", "daily_budget": 10000, "dry_run": True}

        from facebook_business.adobjects.adset import AdSet

        adset = AdSet(adset_id)
        data = adset.api_get(fields=["status", "daily_budget"])
        return data.export_all_data()
