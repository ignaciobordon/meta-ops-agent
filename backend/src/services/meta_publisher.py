"""
Meta Pages Publisher — publishes Content Studio variants to Facebook/Instagram pages.
Requires `pages_manage_posts` OAuth scope (pending App Review).
Until approved, all publish operations run in DRY_RUN mode.
"""
from datetime import datetime
from typing import Dict, Optional
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from backend.src.config import settings
from backend.src.database.models import (
    ContentVariant,
    ContentExport,
    MetaConnection,
)
from backend.src.utils.token_crypto import decrypt_token
from src.utils.logging_config import logger

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


class MetaPublisher:
    """Publishes content to Meta Pages (Facebook/Instagram)."""

    def __init__(self, db: Session, org_id: UUID):
        self.db = db
        self.org_id = org_id

    def _get_access_token(self) -> Optional[str]:
        """Get decrypted access token for the org's Meta connection."""
        conn = self.db.query(MetaConnection).filter(
            MetaConnection.org_id == self.org_id,
        ).first()
        if not conn or not conn.access_token_encrypted:
            return None
        try:
            return decrypt_token(conn.access_token_encrypted)
        except Exception as e:
            logger.error("META_PUBLISHER_TOKEN_ERROR | org={} | error={}", self.org_id, str(e)[:100])
            return None

    def _has_publish_scope(self) -> bool:
        """Check if the connection has pages_manage_posts scope."""
        conn = self.db.query(MetaConnection).filter(
            MetaConnection.org_id == self.org_id,
        ).first()
        if not conn:
            return False
        scopes = conn.scopes or []
        return "pages_manage_posts" in scopes or "pages_manage_engagement" in scopes

    async def publish_variant(
        self,
        variant_id: UUID,
        page_id: str,
        dry_run: bool = True,
    ) -> Dict:
        """
        Publish a content variant to a Facebook Page.
        Returns publish result with post_id if successful.

        NOTE: dry_run=True by default until App Review approves pages_manage_posts scope.
        """
        variant = self.db.query(ContentVariant).filter(
            ContentVariant.id == variant_id,
        ).first()

        if not variant:
            return {"status": "error", "message": "Variant not found"}

        output = variant.output_json or {}
        message = output.get("body", output.get("text", output.get("content", "")))

        if not message:
            return {"status": "error", "message": "Variant has no publishable content"}

        # Check scope
        if not dry_run and not self._has_publish_scope():
            return {
                "status": "error",
                "message": "Publishing requires pages_manage_posts scope. Apply for App Review at developers.facebook.com",
            }

        # Get token
        token = self._get_access_token()
        if not token:
            return {"status": "error", "message": "No Meta connection found. Connect via Control Panel first."}

        if dry_run:
            logger.info(
                "META_PUBLISH_DRY_RUN | org={} | variant={} | page={} | message_len={}",
                self.org_id, variant_id, page_id, len(message),
            )

            # Record the export
            export = ContentExport(
                variant_id=variant_id,
                format="meta_page_post",
                export_json={
                    "dry_run": True,
                    "page_id": page_id,
                    "message_preview": message[:200],
                    "channel": variant.channel,
                    "simulated_at": datetime.utcnow().isoformat(),
                },
            )
            self.db.add(export)
            self.db.commit()

            return {
                "status": "dry_run",
                "message": "Publishing simulated (pages_manage_posts scope not yet approved)",
                "preview": {
                    "page_id": page_id,
                    "message": message[:500],
                    "channel": variant.channel,
                },
            }

        # LIVE PUBLISH
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{GRAPH_API_BASE}/{page_id}/feed",
                    params={"access_token": token},
                    json={"message": message},
                )

                if resp.status_code == 200:
                    data = resp.json()
                    post_id = data.get("id", "")

                    # Record successful export
                    export = ContentExport(
                        variant_id=variant_id,
                        format="meta_page_post",
                        export_json={
                            "post_id": post_id,
                            "page_id": page_id,
                            "published_at": datetime.utcnow().isoformat(),
                            "channel": variant.channel,
                        },
                    )
                    self.db.add(export)
                    self.db.commit()

                    logger.info(
                        "META_PUBLISH_OK | org={} | variant={} | post_id={}",
                        self.org_id, variant_id, post_id,
                    )
                    return {"status": "published", "post_id": post_id}

                else:
                    error_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"message": resp.text[:300]}
                    logger.error(
                        "META_PUBLISH_FAILED | org={} | status={} | error={}",
                        self.org_id, resp.status_code, str(error_data)[:200],
                    )
                    return {
                        "status": "error",
                        "message": f"Meta API error: {error_data.get('error', {}).get('message', resp.text[:200])}",
                    }

        except Exception as e:
            logger.error("META_PUBLISH_EXCEPTION | org={} | error={}", self.org_id, str(e)[:200])
            return {"status": "error", "message": f"Publishing failed: {str(e)[:200]}"}
