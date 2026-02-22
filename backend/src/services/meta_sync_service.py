"""
Sprint 6 – BLOQUE D: Meta Sync Services
Syncs assets (campaigns/adsets/ads) and insights from Meta API to normalized DB tables.
All operations are idempotent upserts keyed by unique constraints.
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from backend.src.database.models import (
    MetaAdAccount,
    MetaAdset,
    MetaAd,
    MetaAlert,
    MetaCampaign,
    MetaConnection,
    MetaInsightsDaily,
    MetaSyncRun,
    InsightLevel,
    SyncRunStatus,
    AlertSeverity,
)
from backend.src.services.meta_api_client import (
    MetaApiClient,
    MetaRateLimitError,
    MetaTokenExpiredError,
)
from backend.src.services.meta_normalizer import (
    normalize_ad,
    normalize_ad_account,
    normalize_adset,
    normalize_campaign,
    normalize_insight,
)
from src.utils.logging_config import logger


class MetaSyncService:
    """Orchestrates asset and insight synchronization from Meta API to DB."""

    def __init__(self, db: Session):
        self.db = db

    def _get_client(self, connection: MetaConnection) -> MetaApiClient:
        return MetaApiClient(db=self.db, connection=connection)

    def _record_sync_run(
        self,
        org_id: UUID,
        ad_account_id: Optional[UUID],
        job_type: str,
        status: SyncRunStatus,
        started_at: datetime,
        items_upserted: int = 0,
        error_count: int = 0,
        errors: Optional[List[str]] = None,
    ) -> MetaSyncRun:
        finished_at = datetime.utcnow()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        run = MetaSyncRun(
            org_id=org_id,
            ad_account_id=ad_account_id,
            job_type=job_type,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            items_upserted=items_upserted,
            error_count=error_count,
            error_summary_json=errors[:10] if errors else None,
        )
        self.db.add(run)
        return run

    # ── Asset Sync ────────────────────────────────────────────────────────────

    def sync_assets(self, org_id: UUID, ad_account_id: UUID) -> Dict:
        """Sync campaigns → adsets → ads for an ad account."""
        started_at = datetime.utcnow()
        total_upserted = 0
        errors: List[str] = []

        # Get the meta_ad_account row
        meta_account = self.db.query(MetaAdAccount).filter(
            MetaAdAccount.id == ad_account_id,
            MetaAdAccount.org_id == org_id,
        ).first()

        if not meta_account:
            logger.warning("SYNC_ASSETS_NO_ACCOUNT | org={} | acc={}", org_id, ad_account_id)
            return {"status": "error", "message": "Meta ad account not found"}

        # Get active connection for org
        connection = self.db.query(MetaConnection).filter(
            MetaConnection.org_id == org_id,
            MetaConnection.status == "active",
        ).first()

        if not connection:
            logger.warning("SYNC_ASSETS_NO_CONNECTION | org={}", org_id)
            return {"status": "error", "message": "No active Meta connection"}

        client = self._get_client(connection)
        account_meta_id = meta_account.meta_account_id

        try:
            # 1. Campaigns
            campaigns_raw = client.get_campaigns(account_meta_id)
            campaign_map = {}  # meta_campaign_id → DB id
            for raw in campaigns_raw:
                norm = normalize_campaign(raw)
                campaign = self._upsert_campaign(org_id, ad_account_id, norm)
                campaign_map[norm["meta_campaign_id"]] = campaign.id
                total_upserted += 1

            # 2. Adsets
            adsets_raw = client.get_adsets(account_meta_id)
            adset_map = {}  # meta_adset_id → DB id
            for raw in adsets_raw:
                norm = normalize_adset(raw)
                campaign_db_id = campaign_map.get(norm["meta_campaign_id"])
                if not campaign_db_id:
                    errors.append(f"Adset {norm['meta_adset_id']} orphan campaign {norm['meta_campaign_id']}")
                    continue
                adset = self._upsert_adset(org_id, ad_account_id, campaign_db_id, norm)
                adset_map[norm["meta_adset_id"]] = adset.id
                total_upserted += 1

            # 3. Ads
            ads_raw = client.get_ads(account_meta_id)
            for raw in ads_raw:
                norm = normalize_ad(raw)
                adset_db_id = adset_map.get(norm["meta_adset_id"])
                if not adset_db_id:
                    errors.append(f"Ad {norm['meta_ad_id']} orphan adset {norm['meta_adset_id']}")
                    continue
                self._upsert_ad(org_id, ad_account_id, adset_db_id, norm)
                total_upserted += 1

            # Update last_synced_at
            meta_account.last_synced_at = datetime.utcnow()
            connection.last_synced_at = datetime.utcnow()

            status = SyncRunStatus.PARTIAL if errors else SyncRunStatus.SUCCESS
            self._record_sync_run(
                org_id, ad_account_id, "assets", status,
                started_at, total_upserted, len(errors), errors,
            )
            self.db.commit()

            logger.info(
                "SYNC_ASSETS_DONE | org={} | acc={} | upserted={} | errors={}",
                org_id, account_meta_id, total_upserted, len(errors),
            )
            return {"status": status.value, "items_upserted": total_upserted, "error_count": len(errors)}

        except MetaTokenExpiredError:
            self._record_sync_run(org_id, ad_account_id, "assets", SyncRunStatus.FAILED, started_at, error_count=1, errors=["Token expired"])
            self.db.commit()
            return {"status": "failed", "message": "Token expired — reauth required"}

        except MetaRateLimitError as e:
            self._record_sync_run(org_id, ad_account_id, "assets", SyncRunStatus.FAILED, started_at, total_upserted, 1, [str(e)])
            self.db.commit()
            return {"status": "rate_limited", "retry_after": e.retry_after}

        except Exception as e:
            logger.error("SYNC_ASSETS_FAILED | org={} | error={}", org_id, str(e))
            self._record_sync_run(org_id, ad_account_id, "assets", SyncRunStatus.FAILED, started_at, total_upserted, 1, [str(e)])
            self.db.commit()
            return {"status": "failed", "message": str(e)}

    def _upsert_campaign(self, org_id: UUID, ad_account_id: UUID, norm: Dict) -> MetaCampaign:
        existing = self.db.query(MetaCampaign).filter(
            MetaCampaign.org_id == org_id,
            MetaCampaign.meta_campaign_id == norm["meta_campaign_id"],
        ).first()

        if existing:
            for key, val in norm.items():
                if key != "meta_campaign_id" and val is not None:
                    setattr(existing, key, val)
            existing.updated_at = datetime.utcnow()
            return existing

        campaign = MetaCampaign(org_id=org_id, ad_account_id=ad_account_id, **norm)
        self.db.add(campaign)
        self.db.flush()
        return campaign

    def _upsert_adset(self, org_id: UUID, ad_account_id: UUID, campaign_id: UUID, norm: Dict) -> MetaAdset:
        # Remove the meta_campaign_id as it's not a column
        norm_copy = {k: v for k, v in norm.items() if k != "meta_campaign_id"}

        existing = self.db.query(MetaAdset).filter(
            MetaAdset.org_id == org_id,
            MetaAdset.meta_adset_id == norm_copy["meta_adset_id"],
        ).first()

        if existing:
            for key, val in norm_copy.items():
                if key != "meta_adset_id" and val is not None:
                    setattr(existing, key, val)
            existing.campaign_id = campaign_id
            existing.updated_at = datetime.utcnow()
            return existing

        adset = MetaAdset(
            org_id=org_id, ad_account_id=ad_account_id, campaign_id=campaign_id,
            **norm_copy,
        )
        self.db.add(adset)
        self.db.flush()
        return adset

    def _upsert_ad(self, org_id: UUID, ad_account_id: UUID, adset_id: UUID, norm: Dict) -> MetaAd:
        norm_copy = {k: v for k, v in norm.items() if k != "meta_adset_id"}

        existing = self.db.query(MetaAd).filter(
            MetaAd.org_id == org_id,
            MetaAd.meta_ad_id == norm_copy["meta_ad_id"],
        ).first()

        if existing:
            for key, val in norm_copy.items():
                if key != "meta_ad_id" and val is not None:
                    setattr(existing, key, val)
            existing.updated_at = datetime.utcnow()
            return existing

        ad = MetaAd(
            org_id=org_id, ad_account_id=ad_account_id, adset_id=adset_id,
            **norm_copy,
        )
        self.db.add(ad)
        self.db.flush()
        return ad

    # ── Insights Sync ─────────────────────────────────────────────────────────

    def sync_insights(
        self,
        org_id: UUID,
        ad_account_id: UUID,
        since: Optional[str] = None,
        until: Optional[str] = None,
        levels: Optional[List[str]] = None,
    ) -> Dict:
        """Sync daily insights for an ad account at specified levels."""
        started_at = datetime.utcnow()
        total_upserted = 0
        errors: List[str] = []

        if not levels:
            levels = ["campaign", "adset", "ad"]

        meta_account = self.db.query(MetaAdAccount).filter(
            MetaAdAccount.id == ad_account_id,
            MetaAdAccount.org_id == org_id,
        ).first()

        if not meta_account:
            return {"status": "error", "message": "Meta ad account not found"}

        connection = self.db.query(MetaConnection).filter(
            MetaConnection.org_id == org_id,
            MetaConnection.status == "active",
        ).first()

        if not connection:
            return {"status": "error", "message": "No active Meta connection"}

        client = self._get_client(connection)
        account_meta_id = meta_account.meta_account_id

        # Default: last 7 days
        if not since:
            since = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        if not until:
            until = datetime.utcnow().strftime("%Y-%m-%d")

        time_range = {"since": since, "until": until}

        try:
            for level in levels:
                try:
                    rows = client.get_insights(
                        ad_account_meta_id=account_meta_id,
                        level=level,
                        time_range=time_range,
                    )

                    for row in rows:
                        norm = normalize_insight(row)
                        # Determine entity_meta_id from the row based on level
                        entity_id = row.get(f"{level}_id") or row.get("id", "")
                        if not entity_id:
                            continue

                        self._upsert_insight(
                            org_id=org_id,
                            ad_account_id=ad_account_id,
                            level=InsightLevel(level),
                            entity_meta_id=entity_id,
                            norm=norm,
                        )
                        total_upserted += 1

                except Exception as e:
                    errors.append(f"Level {level}: {str(e)}")
                    logger.warning("SYNC_INSIGHTS_LEVEL_FAILED | level={} | error={}", level, str(e))

            status = SyncRunStatus.PARTIAL if errors else SyncRunStatus.SUCCESS
            self._record_sync_run(
                org_id, ad_account_id, "insights", status,
                started_at, total_upserted, len(errors), errors,
            )
            self.db.commit()

            logger.info(
                "SYNC_INSIGHTS_DONE | org={} | acc={} | upserted={} | errors={}",
                org_id, account_meta_id, total_upserted, len(errors),
            )
            return {"status": status.value, "items_upserted": total_upserted, "error_count": len(errors)}

        except MetaTokenExpiredError:
            self._record_sync_run(org_id, ad_account_id, "insights", SyncRunStatus.FAILED, started_at, error_count=1, errors=["Token expired"])
            self.db.commit()
            return {"status": "failed", "message": "Token expired — reauth required"}

        except MetaRateLimitError as e:
            self._record_sync_run(org_id, ad_account_id, "insights", SyncRunStatus.FAILED, started_at, total_upserted, 1, [str(e)])
            self.db.commit()
            return {"status": "rate_limited", "retry_after": e.retry_after}

        except Exception as e:
            logger.error("SYNC_INSIGHTS_FAILED | org={} | error={}", org_id, str(e))
            self._record_sync_run(org_id, ad_account_id, "insights", SyncRunStatus.FAILED, started_at, total_upserted, 1, [str(e)])
            self.db.commit()
            return {"status": "failed", "message": str(e)}

    def _upsert_insight(
        self,
        org_id: UUID,
        ad_account_id: UUID,
        level: InsightLevel,
        entity_meta_id: str,
        norm: Dict,
    ) -> MetaInsightsDaily:
        date_start = norm.get("date_start")
        if not date_start:
            return None

        existing = self.db.query(MetaInsightsDaily).filter(
            MetaInsightsDaily.org_id == org_id,
            MetaInsightsDaily.ad_account_id == ad_account_id,
            MetaInsightsDaily.level == level,
            MetaInsightsDaily.entity_meta_id == entity_meta_id,
            MetaInsightsDaily.date_start == date_start,
        ).first()

        if existing:
            for key, val in norm.items():
                if key not in ("date_start",) and val is not None:
                    setattr(existing, key, val)
            existing.updated_at = datetime.utcnow()
            return existing

        insight = MetaInsightsDaily(
            org_id=org_id,
            ad_account_id=ad_account_id,
            level=level,
            entity_meta_id=entity_meta_id,
            **norm,
        )
        self.db.add(insight)
        self.db.flush()
        return insight
