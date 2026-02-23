"""
Sprint 6 – BLOQUE H: Meta Sync API Endpoints
/api/meta/sync/* — sync control + data + intelligence endpoints.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.src.database.models import (
    AlertSeverity,
    InsightLevel,
    MetaAdAccount,
    MetaAdset,
    MetaAd,
    MetaAlert,
    MetaCampaign,
    MetaConnection,
    MetaInsightsDaily,
    MetaSyncRun,
    ScheduledJob,
    Subscription,
    PlanEnum,
)
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user, require_admin
from src.utils.logging_config import logger

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────


class SyncStatusResponse(BaseModel):
    ad_account_id: Optional[str] = None
    meta_account_id: Optional[str] = None
    last_assets_sync: Optional[str] = None
    last_insights_sync: Optional[str] = None
    last_monitor_sync: Optional[str] = None
    assets_lag_minutes: Optional[int] = None
    insights_lag_minutes: Optional[int] = None
    recent_error_count: int = 0
    pending_jobs: int = 0


class CampaignResponse(BaseModel):
    id: str
    meta_campaign_id: str
    name: Optional[str] = None
    objective: Optional[str] = None
    status: Optional[str] = None
    effective_status: Optional[str] = None
    daily_budget: Optional[float] = None
    lifetime_budget: Optional[float] = None
    bid_strategy: Optional[str] = None

    class Config:
        from_attributes = True


class AdsetResponse(BaseModel):
    id: str
    meta_adset_id: str
    campaign_id: str
    name: Optional[str] = None
    status: Optional[str] = None
    effective_status: Optional[str] = None
    daily_budget: Optional[float] = None
    optimization_goal: Optional[str] = None

    class Config:
        from_attributes = True


class AdResponse(BaseModel):
    id: str
    meta_ad_id: str
    adset_id: str
    name: Optional[str] = None
    status: Optional[str] = None
    effective_status: Optional[str] = None
    creative_id: Optional[str] = None

    class Config:
        from_attributes = True


class InsightResponse(BaseModel):
    entity_meta_id: str
    level: str
    date_start: str
    spend: Optional[float] = None
    impressions: Optional[int] = None
    clicks: Optional[int] = None
    ctr: Optional[float] = None
    cpm: Optional[float] = None
    cpc: Optional[float] = None
    frequency: Optional[float] = None
    conversions: Optional[int] = None
    purchase_roas: Optional[float] = None


class AlertResponse(BaseModel):
    id: str
    alert_type: str
    severity: str
    message: str
    entity_type: Optional[str] = None
    entity_meta_id: Optional[str] = None
    detected_at: str
    resolved_at: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_org_meta_accounts(org_id: str, db: Session) -> List[MetaAdAccount]:
    return db.query(MetaAdAccount).filter(MetaAdAccount.org_id == UUID(org_id)).all()


def _check_trial_limit(org_id: str, db: Session) -> Optional[MetaAdAccount]:
    """For TRIAL plans, only allow sync on the first ad account."""
    sub = db.query(Subscription).filter(Subscription.org_id == UUID(org_id)).first()
    if sub and sub.plan == PlanEnum.TRIAL:
        accounts = _get_org_meta_accounts(org_id, db)
        if accounts:
            return accounts[0]  # Only first account for TRIAL
    return None


# ── Status + Control ─────────────────────────────────────────────────────────


@router.get("/sync/status", response_model=List[SyncStatusResponse])
def get_sync_status(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get sync status per ad account for the org."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    accounts = _get_org_meta_accounts(org_id, db)
    results = []

    for acc in accounts:
        now = datetime.utcnow()

        # Get last sync runs
        last_assets = db.query(MetaSyncRun).filter(
            MetaSyncRun.org_id == UUID(org_id),
            MetaSyncRun.ad_account_id == acc.id,
            MetaSyncRun.job_type == "assets",
        ).order_by(MetaSyncRun.finished_at.desc()).first()

        last_insights = db.query(MetaSyncRun).filter(
            MetaSyncRun.org_id == UUID(org_id),
            MetaSyncRun.ad_account_id == acc.id,
            MetaSyncRun.job_type == "insights",
        ).order_by(MetaSyncRun.finished_at.desc()).first()

        last_monitor = db.query(MetaSyncRun).filter(
            MetaSyncRun.org_id == UUID(org_id),
            MetaSyncRun.ad_account_id == acc.id,
            MetaSyncRun.job_type == "monitor",
        ).order_by(MetaSyncRun.finished_at.desc()).first()

        # Count recent errors
        error_count = db.query(MetaSyncRun).filter(
            MetaSyncRun.org_id == UUID(org_id),
            MetaSyncRun.ad_account_id == acc.id,
            MetaSyncRun.status == "failed",
        ).count()

        # Count pending jobs
        pending = db.query(ScheduledJob).filter(
            ScheduledJob.org_id == UUID(org_id),
            ScheduledJob.reference_id == acc.id,
            ScheduledJob.completed_at.is_(None),
        ).count()

        assets_lag = int((now - last_assets.finished_at).total_seconds() / 60) if last_assets and last_assets.finished_at else None
        insights_lag = int((now - last_insights.finished_at).total_seconds() / 60) if last_insights and last_insights.finished_at else None

        results.append(SyncStatusResponse(
            ad_account_id=str(acc.id),
            meta_account_id=acc.meta_account_id,
            last_assets_sync=last_assets.finished_at.isoformat() if last_assets and last_assets.finished_at else None,
            last_insights_sync=last_insights.finished_at.isoformat() if last_insights and last_insights.finished_at else None,
            last_monitor_sync=last_monitor.finished_at.isoformat() if last_monitor and last_monitor.finished_at else None,
            assets_lag_minutes=assets_lag,
            insights_lag_minutes=insights_lag,
            recent_error_count=error_count,
            pending_jobs=pending,
        ))

    return results


@router.post("/sync/now")
def trigger_sync_now(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Enqueue immediate sync jobs for all org ad accounts (plan-gated)."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    # Check subscription status
    sub = db.query(Subscription).filter(Subscription.org_id == UUID(org_id)).first()
    if sub and sub.status in ("past_due", "canceled"):
        raise HTTPException(403, "Subscription inactive — sync disabled")

    from backend.src.services.meta_job_scheduler import MetaJobScheduler
    scheduler = MetaJobScheduler(db)

    accounts = _get_org_meta_accounts(org_id, db)

    # TRIAL limit: only first account
    if sub and sub.plan == PlanEnum.TRIAL and len(accounts) > 1:
        accounts = accounts[:1]

    total_enqueued = 0
    for acc in accounts:
        created = scheduler.enqueue_if_missing(UUID(org_id), acc.id)
        total_enqueued += len(created)

    db.commit()
    return {"message": f"Enqueued {total_enqueued} sync jobs", "accounts": len(accounts)}


@router.post("/sync/active")
def sync_active_account(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sync assets + insights for the active ad account directly (no Celery)."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    from backend.src.database.models import Organization, AdAccount
    org = db.query(Organization).filter(Organization.id == UUID(org_id)).first()
    if not org or not org.active_ad_account_id:
        raise HTTPException(400, "No active ad account selected")

    # Find the matching MetaAdAccount
    ad_account = db.query(AdAccount).filter(AdAccount.id == org.active_ad_account_id).first()
    if not ad_account:
        raise HTTPException(404, "Active ad account not found")

    meta_account = db.query(MetaAdAccount).filter(
        MetaAdAccount.org_id == UUID(org_id),
        MetaAdAccount.meta_account_id == ad_account.meta_ad_account_id,
    ).first()
    if not meta_account:
        raise HTTPException(404, "Meta ad account not found in sync tables")

    from backend.src.services.meta_sync_service import MetaSyncService
    sync = MetaSyncService(db=db)

    # Sync assets
    assets_result = sync.sync_assets(org_id=meta_account.org_id, ad_account_id=meta_account.id)

    # Sync insights (last 90 days)
    since = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
    until = datetime.utcnow().strftime("%Y-%m-%d")
    insights_result = sync.sync_insights(
        org_id=meta_account.org_id,
        ad_account_id=meta_account.id,
        since=since,
        until=until,
        levels=["campaign", "adset", "ad"],
    )

    return {
        "account": ad_account.name,
        "meta_account_id": ad_account.meta_ad_account_id,
        "assets": assets_result,
        "insights": insights_result,
    }


@router.post("/backfill")
def backfill_historical_insights(
    since: str = Query(..., description="Start date YYYY-MM-DD (e.g. 2022-01-01)"),
    until: Optional[str] = Query(None, description="End date YYYY-MM-DD (default: today)"),
    ad_account_id: Optional[str] = Query(None, description="Specific ad account UUID (default: all)"),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Backfill historical Meta insights in monthly chunks.

    The Meta Graph API supports up to 37 months of historical data.
    This endpoint syncs month by month to avoid API timeouts.
    """
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    import time
    from dateutil.relativedelta import relativedelta
    from backend.src.services.meta_sync_service import MetaSyncService
    from backend.src.services.meta_api_client import _meta_cb

    try:
        since_dt = datetime.strptime(since, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Invalid since date format. Use YYYY-MM-DD")

    until_dt = datetime.strptime(until, "%Y-%m-%d") if until else datetime.utcnow()

    if since_dt >= until_dt:
        raise HTTPException(400, "since must be before until")

    # Find target ad accounts
    account_filter = MetaAdAccount.org_id == UUID(org_id)
    if ad_account_id:
        accounts = db.query(MetaAdAccount).filter(
            account_filter, MetaAdAccount.id == UUID(ad_account_id)
        ).all()
    else:
        accounts = db.query(MetaAdAccount).filter(account_filter).all()

    if not accounts:
        raise HTTPException(404, "No ad accounts found")

    # Reset circuit breaker before bulk backfill
    _meta_cb.record_success()

    sync = MetaSyncService(db=db)
    results = []

    for account in accounts:
        account_result = {
            "account": account.name,
            "meta_account_id": account.meta_account_id,
            "currency": account.currency,
            "months_synced": 0,
            "total_upserted": 0,
            "errors": [],
        }

        # Chunk by month to avoid API timeouts
        chunk_start = since_dt
        while chunk_start < until_dt:
            chunk_end = min(chunk_start + relativedelta(months=1), until_dt)
            chunk_since = chunk_start.strftime("%Y-%m-%d")
            chunk_until = chunk_end.strftime("%Y-%m-%d")

            try:
                r = sync.sync_insights(
                    org_id=UUID(org_id),
                    ad_account_id=account.id,
                    since=chunk_since,
                    until=chunk_until,
                    levels=["campaign"],
                )
                account_result["months_synced"] += 1
                account_result["total_upserted"] += r.get("items_upserted", 0)
            except Exception as e:
                account_result["errors"].append(f"{chunk_since}: {str(e)}")

            chunk_start = chunk_end
            # Throttle to avoid tripping circuit breaker / Meta rate limits
            time.sleep(2)

        results.append(account_result)

    return {
        "status": "completed",
        "range": f"{since} to {until_dt.strftime('%Y-%m-%d')}",
        "accounts": results,
    }


# ── Data Endpoints ────────────────────────────────────────────────────────────


@router.get("/campaigns", response_model=List[CampaignResponse])
def list_campaigns(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List synced Meta campaigns for the org."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    query = db.query(MetaCampaign).filter(MetaCampaign.org_id == UUID(org_id))

    if status:
        query = query.filter(MetaCampaign.effective_status == status)
    if search:
        query = query.filter(MetaCampaign.name.ilike(f"%{search}%"))

    campaigns = query.order_by(MetaCampaign.updated_at.desc()).limit(200).all()

    return [
        CampaignResponse(
            id=str(c.id), meta_campaign_id=c.meta_campaign_id,
            name=c.name, objective=c.objective, status=c.status,
            effective_status=c.effective_status, daily_budget=c.daily_budget,
            lifetime_budget=c.lifetime_budget, bid_strategy=c.bid_strategy,
        )
        for c in campaigns
    ]


@router.get("/adsets", response_model=List[AdsetResponse])
def list_adsets(
    campaign_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List synced Meta adsets for the org."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    query = db.query(MetaAdset).filter(MetaAdset.org_id == UUID(org_id))

    if campaign_id:
        query = query.filter(MetaAdset.campaign_id == UUID(campaign_id))

    adsets = query.order_by(MetaAdset.updated_at.desc()).limit(200).all()

    return [
        AdsetResponse(
            id=str(a.id), meta_adset_id=a.meta_adset_id,
            campaign_id=str(a.campaign_id), name=a.name,
            status=a.status, effective_status=a.effective_status,
            daily_budget=a.daily_budget, optimization_goal=a.optimization_goal,
        )
        for a in adsets
    ]


@router.get("/ads", response_model=List[AdResponse])
def list_ads(
    adset_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List synced Meta ads for the org."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    query = db.query(MetaAd).filter(MetaAd.org_id == UUID(org_id))

    if adset_id:
        query = query.filter(MetaAd.adset_id == UUID(adset_id))

    ads = query.order_by(MetaAd.updated_at.desc()).limit(200).all()

    return [
        AdResponse(
            id=str(a.id), meta_ad_id=a.meta_ad_id,
            adset_id=str(a.adset_id), name=a.name,
            status=a.status, effective_status=a.effective_status,
            creative_id=a.creative_id,
        )
        for a in ads
    ]


@router.get("/insights", response_model=List[InsightResponse])
def list_insights(
    level: str = Query("campaign"),
    entity_id: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get daily insights data."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    query = db.query(MetaInsightsDaily).filter(
        MetaInsightsDaily.org_id == UUID(org_id),
        MetaInsightsDaily.level == level,
    )

    if entity_id:
        query = query.filter(MetaInsightsDaily.entity_meta_id == entity_id)
    if since:
        query = query.filter(MetaInsightsDaily.date_start >= since)
    if until:
        query = query.filter(MetaInsightsDaily.date_stop <= until)

    rows = query.order_by(MetaInsightsDaily.date_start.desc()).limit(500).all()

    return [
        InsightResponse(
            entity_meta_id=r.entity_meta_id, level=r.level.value,
            date_start=r.date_start.strftime("%Y-%m-%d"),
            spend=r.spend, impressions=r.impressions, clicks=r.clicks,
            ctr=r.ctr, cpm=r.cpm, cpc=r.cpc, frequency=r.frequency,
            conversions=r.conversions, purchase_roas=r.purchase_roas,
        )
        for r in rows
    ]


# ── Intelligence Endpoints ────────────────────────────────────────────────────


@router.get("/alerts", response_model=List[AlertResponse])
def list_alerts(
    severity: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get active alerts for the org."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    query = db.query(MetaAlert).filter(
        MetaAlert.org_id == UUID(org_id),
        MetaAlert.resolved_at.is_(None),
    )

    if severity:
        query = query.filter(MetaAlert.severity == severity)

    alerts = query.order_by(MetaAlert.detected_at.desc()).limit(limit).all()

    return [
        AlertResponse(
            id=str(a.id), alert_type=a.alert_type,
            severity=a.severity.value if hasattr(a.severity, 'value') else str(a.severity),
            message=a.message, entity_type=a.entity_type,
            entity_meta_id=a.entity_meta_id,
            detected_at=a.detected_at.isoformat(),
            resolved_at=a.resolved_at.isoformat() if a.resolved_at else None,
            payload=a.payload_json,
        )
        for a in alerts
    ]


@router.get("/insights/signals", response_model=List[AlertResponse])
def list_insight_signals(
    limit: int = Query(20, le=100),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get insight engine-generated signals (subset of alerts)."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    insight_types = ["ctr_low", "cpa_high", "roas_low", "frequency_decay", "spend_spike_no_conv"]

    alerts = db.query(MetaAlert).filter(
        MetaAlert.org_id == UUID(org_id),
        MetaAlert.alert_type.in_(insight_types),
        MetaAlert.resolved_at.is_(None),
    ).order_by(MetaAlert.detected_at.desc()).limit(limit).all()

    return [
        AlertResponse(
            id=str(a.id), alert_type=a.alert_type,
            severity=a.severity.value if hasattr(a.severity, 'value') else str(a.severity),
            message=a.message, entity_type=a.entity_type,
            entity_meta_id=a.entity_meta_id,
            detected_at=a.detected_at.isoformat(),
            resolved_at=None,
            payload=a.payload_json,
        )
        for a in alerts
    ]


@router.get("/anomalies", response_model=List[AlertResponse])
def list_anomalies(
    limit: int = Query(20, le=100),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get anomaly detector-generated alerts."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    alerts = db.query(MetaAlert).filter(
        MetaAlert.org_id == UUID(org_id),
        MetaAlert.alert_type.like("anomaly_%"),
        MetaAlert.resolved_at.is_(None),
    ).order_by(MetaAlert.detected_at.desc()).limit(limit).all()

    return [
        AlertResponse(
            id=str(a.id), alert_type=a.alert_type,
            severity=a.severity.value if hasattr(a.severity, 'value') else str(a.severity),
            message=a.message, entity_type=a.entity_type,
            entity_meta_id=a.entity_meta_id,
            detected_at=a.detected_at.isoformat(),
            resolved_at=None,
            payload=a.payload_json,
        )
        for a in alerts
    ]


# ── Internal Runner ───────────────────────────────────────────────────────────


@router.post("/internal/run-meta-jobs")
def run_meta_jobs(
    limit: int = Query(20, le=100),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Process pending meta sync jobs. Admin only."""
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin only")

    from backend.src.services.meta_job_scheduler import MetaJobScheduler
    scheduler = MetaJobScheduler(db)
    results = scheduler.process_meta_jobs(limit=limit)

    return {"processed": len(results), "results": results}


@router.post("/meta/refresh-tokens")
def refresh_meta_tokens(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Refresh Meta long-lived tokens for the org's connections.
    Long-lived tokens expire after ~60 days. This endpoint extends them.
    Should be called periodically (weekly recommended).
    """
    from backend.src.database.models import MetaConnection
    from backend.src.utils.token_crypto import encrypt_token, decrypt_token
    from backend.src.config import settings
    import httpx
    from uuid import UUID

    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "Missing org_id")

    connections = db.query(MetaConnection).filter(
        MetaConnection.org_id == UUID(org_id),
    ).all()

    if not connections:
        return {"status": "no_connections", "refreshed": 0}

    results = []
    for conn in connections:
        try:
            # Decrypt current token
            current_token = decrypt_token(conn.access_token_encrypted)

            # Exchange for new long-lived token
            resp = httpx.get(
                "https://graph.facebook.com/v21.0/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": settings.META_APP_ID,
                    "client_secret": settings.META_APP_SECRET,
                    "fb_exchange_token": current_token,
                },
                timeout=30,
            )

            if resp.status_code == 200:
                data = resp.json()
                new_token = data.get("access_token", "")
                expires_in = data.get("expires_in", 0)

                if new_token:
                    conn.access_token_encrypted = encrypt_token(new_token)
                    conn.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in) if expires_in else None
                    results.append({
                        "connection_id": str(conn.id),
                        "status": "refreshed",
                        "expires_in_days": round(expires_in / 86400, 1) if expires_in else None,
                    })
                else:
                    results.append({"connection_id": str(conn.id), "status": "no_token_in_response"})
            else:
                error = resp.json().get("error", {}).get("message", resp.text[:200]) if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:200]
                results.append({
                    "connection_id": str(conn.id),
                    "status": "failed",
                    "error": error,
                })

        except Exception as e:
            results.append({
                "connection_id": str(conn.id),
                "status": "error",
                "error": str(e)[:200],
            })

    db.commit()

    refreshed = sum(1 for r in results if r["status"] == "refreshed")
    logger.info("TOKEN_REFRESH | org={} | total={} | refreshed={}", org_id, len(connections), refreshed)

    return {"status": "done", "refreshed": refreshed, "total": len(connections), "details": results}
