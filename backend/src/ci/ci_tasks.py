"""
CI AutoLoop task execution logic.

These functions are called by the generic task_runner dispatch.
They run inside a JobRun lifecycle (lock, status transitions, error classification).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from backend.src.ci.models import (
    CICanonicalItem, CICompetitor, CICompetitorDomain, CICompetitorStatus,
    CIDomainType, CIItemType, CIRun, CIRunStatus, CIRunType,
)
from backend.src.config import settings
from backend.src.database.models import MetaAlert, AlertSeverity
from backend.src.observability.metrics import (
    track_ci_run, track_ci_items_collected, track_ci_opportunities_detected,
    track_ci_alerts_created,
)
from src.utils.logging_config import logger


# ── Ingest Task ─────────────────────────────────────────────────────────────


def run_ci_ingest(org_id: UUID, payload: dict, db: Session, job_run_id: str | None = None):
    """
    Collect competitive intelligence items from external sources.

    Steps:
        1. Check provider health (circuit breaker, degraded mode)
        2. Load competitors for this org
        3. Run collectors (web / ads) — stubbed for external APIs
        4. Normalize → persist canonical_items
        5. Update ci_run with items_collected
    """
    source = payload.get("source", "web")
    max_competitors = payload.get("max_competitors", 50)
    max_items = payload.get("max_items", 200)

    # Find or create the ci_run row
    ci_run = _get_or_create_ci_run(db, org_id, CIRunType.INGEST, source, job_run_id)
    ci_run.status = CIRunStatus.RUNNING
    ci_run.started_at = datetime.utcnow()
    db.flush()

    t0 = time.monotonic()

    try:
        # Check source feature flag
        if not _is_source_enabled(source):
            ci_run.status = CIRunStatus.SKIPPED
            ci_run.finished_at = datetime.utcnow()
            ci_run.metadata_json = {"skip_reason": f"source_{source}_disabled"}
            db.commit()
            logger.info(
                "event=ci_run_skipped | org_id={} | run_type=ingest | source={} | reason=source_disabled",
                org_id, source,
            )
            return

        # Check degraded mode for this source
        if _is_provider_degraded(source, org_id):
            ci_run.status = CIRunStatus.SKIPPED
            ci_run.finished_at = datetime.utcnow()
            ci_run.metadata_json = {"skip_reason": f"provider_{source}_degraded"}
            db.commit()
            logger.info(
                "event=ci_run_skipped | org_id={} | run_type=ingest | source={} | reason=provider_degraded",
                org_id, source,
            )
            return

        # Load competitors
        competitors = (
            db.query(CICompetitor)
            .filter(CICompetitor.org_id == org_id, CICompetitor.status == CICompetitorStatus.ACTIVE)
            .limit(max_competitors)
            .all()
        )

        items_collected = 0

        for competitor in competitors:
            # Collect items — this calls the appropriate collector engine
            new_items = _collect_from_source(
                source=source,
                competitor=competitor,
                org_id=org_id,
                max_items=max_items - items_collected,
                db=db,
            )
            items_collected += len(new_items)

            if items_collected >= max_items:
                break

        duration_ms = int((time.monotonic() - t0) * 1000)

        ci_run.status = CIRunStatus.SUCCEEDED
        ci_run.finished_at = datetime.utcnow()
        ci_run.items_collected = items_collected
        ci_run.metadata_json = {
            "duration_ms": duration_ms,
            "competitors_scanned": len(competitors),
            "max_items": max_items,
        }
        db.commit()

        track_ci_run("ingest", "succeeded", duration_ms / 1000.0)
        track_ci_items_collected(source, items_collected)

        logger.info(
            "event=ci_run_succeeded | org_id={} | run_type=ingest | source={} "
            "| items_collected={} | duration_ms={} | ci_run_id={} | job_run_id={}",
            org_id, source, items_collected, duration_ms, ci_run.id, job_run_id,
        )

    except Exception as e:
        duration_ms = int((time.monotonic() - t0) * 1000)
        ci_run.status = CIRunStatus.FAILED
        ci_run.finished_at = datetime.utcnow()
        ci_run.error_class = type(e).__name__
        ci_run.error_message = str(e)[:2000]
        ci_run.metadata_json = {"duration_ms": duration_ms}
        db.commit()

        track_ci_run("ingest", "failed", duration_ms / 1000.0)

        logger.error(
            "event=ci_run_failed | org_id={} | run_type=ingest | source={} "
            "| error_class={} | error={} | ci_run_id={} | job_run_id={}",
            org_id, source, type(e).__name__, str(e)[:300], ci_run.id, job_run_id,
        )
        raise


# ── Detect Task ─────────────────────────────────────────────────────────────


def run_ci_detect(org_id: UUID, payload: dict, db: Session, job_run_id: str | None = None):
    """
    Run opportunity detectors over recently collected canonical items.

    Steps:
        1. Load recent canonical_items for this org
        2. Convert to engine CanonicalItem format
        3. Run OpportunityEngine.run_all()
        4. Persist detected opportunities
        5. Create alerts for significant findings
    """
    max_items = payload.get("max_items", 200)

    ci_run = _get_or_create_ci_run(db, org_id, CIRunType.DETECT, None, job_run_id)
    ci_run.status = CIRunStatus.RUNNING
    ci_run.started_at = datetime.utcnow()
    db.flush()

    t0 = time.monotonic()

    try:
        # Load recent canonical items (last 30 days as current, 30-60 days as previous)
        now = datetime.utcnow()
        recent_cutoff = now - timedelta(days=30)
        baseline_cutoff = now - timedelta(days=60)

        current_db_items = (
            db.query(CICanonicalItem)
            .filter(
                CICanonicalItem.org_id == org_id,
                CICanonicalItem.last_seen_at >= recent_cutoff,
            )
            .limit(max_items)
            .all()
        )

        previous_db_items = (
            db.query(CICanonicalItem)
            .filter(
                CICanonicalItem.org_id == org_id,
                CICanonicalItem.last_seen_at >= baseline_cutoff,
                CICanonicalItem.last_seen_at < recent_cutoff,
            )
            .limit(max_items)
            .all()
        )

        if not current_db_items:
            ci_run.status = CIRunStatus.SUCCEEDED
            ci_run.finished_at = datetime.utcnow()
            ci_run.metadata_json = {"skip_reason": "no_items", "duration_ms": 0}
            db.commit()
            logger.info(
                "event=ci_run_succeeded | org_id={} | run_type=detect | items=0 | skipped=no_data",
                org_id,
            )
            return

        # Convert DB items to engine CanonicalItem format
        from src.engines.opportunity_engine.models import CanonicalItem

        current_items = [_db_item_to_canonical(item) for item in current_db_items]
        previous_items = [_db_item_to_canonical(item) for item in previous_db_items]

        # Run Opportunity Detection Engine
        from src.engines.opportunity_engine.engine import OpportunityEngine
        from src.engines.opportunity_engine.storage import InMemoryOpportunityStore

        store = InMemoryOpportunityStore()
        engine = OpportunityEngine(storage=store)
        report = engine.run_all(current_items, previous_items if previous_items else None)

        opportunities = store.list_opportunities(limit=200)

        # Create alerts for detected opportunities
        alerts_created = 0
        for opp in opportunities:
            alert_type = _opp_type_to_alert_type(opp.type)
            if alert_type and opp.priority_score >= 0.3:
                _create_ci_alert(
                    db=db,
                    org_id=org_id,
                    alert_type=alert_type,
                    severity=_score_to_severity(opp.priority_score),
                    title=opp.title,
                    description=opp.description,
                    evidence_ids=opp.evidence_ids,
                    rationale=opp.rationale,
                    suggested_actions=opp.suggested_actions,
                )
                alerts_created += 1

        duration_ms = int((time.monotonic() - t0) * 1000)

        ci_run.status = CIRunStatus.SUCCEEDED
        ci_run.finished_at = datetime.utcnow()
        ci_run.items_collected = len(current_db_items)
        ci_run.opportunities_created = report.opportunities_found
        ci_run.alerts_created = alerts_created
        ci_run.metadata_json = {
            "duration_ms": duration_ms,
            "detectors_executed": report.detectors_executed,
            "deduped": report.opportunities_deduped,
            "errors": report.errors,
            "current_items": len(current_items),
            "previous_items": len(previous_items),
        }
        db.commit()

        track_ci_run("detect", "succeeded", duration_ms / 1000.0)
        track_ci_opportunities_detected(report.opportunities_found)
        for opp in opportunities:
            at = _opp_type_to_alert_type(opp.type)
            if at and opp.priority_score >= 0.3:
                track_ci_alerts_created(at)

        logger.info(
            "event=ci_run_succeeded | org_id={} | run_type=detect "
            "| opportunities={} | alerts={} | duration_ms={} | ci_run_id={} | job_run_id={}",
            org_id, report.opportunities_found, alerts_created, duration_ms,
            ci_run.id, job_run_id,
        )

    except Exception as e:
        duration_ms = int((time.monotonic() - t0) * 1000)
        ci_run.status = CIRunStatus.FAILED
        ci_run.finished_at = datetime.utcnow()
        ci_run.error_class = type(e).__name__
        ci_run.error_message = str(e)[:2000]
        ci_run.metadata_json = {"duration_ms": duration_ms}
        db.commit()

        track_ci_run("detect", "failed", duration_ms / 1000.0)

        logger.error(
            "event=ci_run_failed | org_id={} | run_type=detect "
            "| error_class={} | error={} | ci_run_id={} | job_run_id={}",
            org_id, type(e).__name__, str(e)[:300], ci_run.id, job_run_id,
        )
        raise


# ── Internal Helpers ────────────────────────────────────────────────────────


def _get_or_create_ci_run(
    db: Session,
    org_id: UUID,
    run_type: CIRunType,
    source: str | None,
    job_run_id: str | None,
) -> CIRun:
    """Find existing ci_run for this job_run, or create one."""
    if job_run_id:
        existing = db.query(CIRun).filter(
            CIRun.job_run_id == UUID(job_run_id),
        ).first()
        if existing:
            return existing

    ci_run = CIRun(
        org_id=org_id,
        run_type=run_type,
        source=source,
        status=CIRunStatus.QUEUED,
        job_run_id=UUID(job_run_id) if job_run_id else None,
    )
    db.add(ci_run)
    db.flush()
    return ci_run


def _is_source_enabled(source: str) -> bool:
    """Check if a CI source is enabled by feature flag."""
    flag_map = {
        "web": settings.CI_SOURCE_WEB_ENABLED,
        "meta_ads": settings.CI_SOURCE_META_ADS_ENABLED,
        "google_ads": settings.CI_SOURCE_GOOGLE_ADS_ENABLED,
        "tiktok": settings.CI_SOURCE_TIKTOK_ENABLED,
        "instagram": getattr(settings, "CI_SOURCE_INSTAGRAM_ENABLED", False),
        "social": getattr(settings, "CI_SOURCE_SOCIAL_SCRAPING_ENABLED", False),
    }
    return flag_map.get(source, False)


def _is_provider_degraded(source: str, org_id: UUID) -> bool:
    """Check if the provider for this source is degraded (circuit breaker OPEN)."""
    provider_map = {
        "web": "web_crawler",
        "meta_ads": "meta",
        "google_ads": "google",
        "tiktok": "tiktok",
    }
    provider = provider_map.get(source)
    if not provider:
        return False

    try:
        from backend.src.providers.circuit_breaker import PersistentCircuitBreaker
        cb = PersistentCircuitBreaker(provider=provider, org_id=org_id)
        return not cb.allow_request()
    except Exception:
        return False


def _collect_from_source(
    source: str,
    competitor: CICompetitor,
    org_id: UUID,
    max_items: int,
    db: Session,
) -> list[CICanonicalItem]:
    """
    Run the appropriate collector for the source.
    Returns list of newly persisted CICanonicalItem rows.
    """
    if source == "web":
        return _collect_web(competitor, org_id, max_items, db)
    elif source == "meta_ads":
        return _collect_meta_ads(competitor, org_id, max_items, db)
    else:
        logger.warning("event=ci_collect_unknown_source | source=%s", source)
        return []


def _collect_web(
    competitor: CICompetitor,
    org_id: UUID,
    max_items: int,
    db: Session,
) -> list[CICanonicalItem]:
    """Crawl competitor website domains and convert pages to CICanonicalItems."""
    import asyncio

    from src.engines.web_intelligence.config import CrawlerConfig
    from src.engines.web_intelligence.crawler_service import crawl_domain
    from backend.src.ci.engine import CompetitiveIntelligenceEngine

    ci_engine = CompetitiveIntelligenceEngine(db)

    # Load explicit website domains for this competitor
    domains = (
        db.query(CICompetitorDomain)
        .filter(
            CICompetitorDomain.competitor_id == competitor.id,
            CICompetitorDomain.domain_type == CIDomainType.WEBSITE,
        )
        .all()
    )

    # Fallback: use competitor.website_url if no explicit domains registered
    if not domains and competitor.website_url:
        domain_urls = [competitor.website_url]
    else:
        domain_urls = [d.domain for d in domains]

    if not domain_urls:
        logger.info(
            "event=ci_web_no_domains | competitor=%s | org_id=%s",
            competitor.name, org_id,
        )
        return []

    new_items: list[CICanonicalItem] = []
    config = CrawlerConfig(max_pages_per_domain=min(max_items, 20), max_depth=2)

    for domain_url in domain_urls:
        if len(new_items) >= max_items:
            break
        try:
            _results, extracted, _html, report = asyncio.run(
                crawl_domain(domain=domain_url, depth=2, config=config)
            )

            for url, page_data in extracted.items():
                if len(new_items) >= max_items:
                    break

                # Build title: prefer page title > first headline > first product name
                title = (
                    page_data.title
                    or (page_data.headlines[0] if page_data.headlines else "")
                    or (page_data.product_names[0] if page_data.product_names else "")
                    or None
                )

                # Build body: combine all available text signals
                body_parts = []
                if page_data.headlines:
                    body_parts.extend(page_data.headlines[:5])
                if page_data.offers:
                    body_parts.extend(page_data.offers[:5])
                if page_data.cta_phrases:
                    body_parts.extend(page_data.cta_phrases[:3])
                if page_data.hero_sections:
                    body_parts.extend(page_data.hero_sections[:3])
                body_text = "; ".join(body_parts)[:2000] or None

                canonical = {
                    "platform": "web",
                    "competitor": competitor.name,
                    "headlines": page_data.headlines,
                    "offers": page_data.offers,
                    "pricing_blocks": page_data.pricing_blocks,
                    "cta": "; ".join(page_data.cta_phrases[:5]) if page_data.cta_phrases else "",
                    "guarantees": page_data.guarantees,
                    "product_names": page_data.product_names,
                    "hero_sections": page_data.hero_sections[:3] if page_data.hero_sections else [],
                    "keywords": page_data.semantic_keywords[:20],
                    "format": "landing_page",
                }

                raw = _pydantic_to_dict(page_data)

                item = ci_engine.upsert_canonical_item(
                    org_id=org_id,
                    competitor_id=competitor.id,
                    item_type="landing_page",
                    external_id=url[:255],
                    title=title,
                    body_text=body_text,
                    url=url,
                    canonical_json=canonical,
                    raw_json=raw,
                )
                new_items.append(item)

            logger.info(
                "event=ci_web_crawl_done | competitor=%s | domain=%s "
                "| pages_crawled=%d | items_upserted=%d",
                competitor.name, domain_url, report.pages_crawled, len(new_items),
            )
        except Exception as e:
            logger.warning(
                "event=ci_web_crawl_error | competitor=%s | domain=%s | error=%s",
                competitor.name, domain_url, str(e)[:200],
            )

    return new_items


def _collect_meta_ads(
    competitor: CICompetitor,
    org_id: UUID,
    max_items: int,
    db: Session,
) -> list[CICanonicalItem]:
    """Collect ads from Meta Ad Library for a competitor."""
    import asyncio

    from src.engines.ads_intelligence.core.ads_engine import AdsIntelligenceEngine
    from src.engines.ads_intelligence.core.config import AdsConfig, PlatformConfig
    from backend.src.ci.engine import CompetitiveIntelligenceEngine

    ci_engine = CompetitiveIntelligenceEngine(db)

    # Resolve Meta Ad Library token: settings first, then org's OAuth connection
    from backend.src.config import settings as _settings
    meta_token = _settings.META_AD_LIBRARY_ACCESS_TOKEN
    if not meta_token:
        try:
            from backend.src.database.models import MetaConnection
            from backend.src.utils.token_crypto import decrypt_token
            conn = db.query(MetaConnection).filter(MetaConnection.org_id == org_id).first()
            if conn and conn.access_token_encrypted:
                meta_token = decrypt_token(conn.access_token_encrypted)
        except Exception:
            meta_token = ""

    config = AdsConfig(
        meta=PlatformConfig(
            enabled=True,
            api_key=meta_token,
            max_ads_per_query=min(max_items, 50),
        ),
        google=PlatformConfig(enabled=False),
        tiktok=PlatformConfig(enabled=False),
    )

    ads_engine = AdsIntelligenceEngine(config=config)

    query = competitor.name
    country = (competitor.meta_json or {}).get("country", "US")

    try:
        report = asyncio.run(ads_engine.run_source("meta", query=query, country=country))
    except Exception as e:
        logger.warning(
            "event=ci_ads_collect_error | competitor=%s | error=%s",
            competitor.name, str(e)[:200],
        )
        return []

    collected_ads = ads_engine.get_ads(platform="meta")

    new_items: list[CICanonicalItem] = []
    for ad in collected_ads[:max_items]:
        canonical = {
            "platform": ad.platform.value if hasattr(ad.platform, "value") else str(ad.platform),
            "competitor": competitor.name,
            "cta": ad.cta,
            "format": ad.format.value if hasattr(ad.format, "value") else str(ad.format),
            "country": ad.country,
            "landing_url": ad.landing_url,
            "media_url": ad.media_url,
            "fingerprint": ad.fingerprint,
            "keywords": [],
        }

        raw = _pydantic_to_dict(ad)

        item = ci_engine.upsert_canonical_item(
            org_id=org_id,
            competitor_id=competitor.id,
            item_type="ad",
            external_id=(ad.fingerprint or ad.id)[:255],
            title=ad.headline,
            body_text=ad.copy,
            url=ad.landing_url,
            image_urls=[ad.media_url] if ad.media_url else [],
            canonical_json=canonical,
            raw_json=raw,
        )
        new_items.append(item)

    logger.info(
        "event=ci_ads_collect_done | competitor=%s | ads_collected=%d "
        "| ads_new=%d | items_upserted=%d",
        competitor.name, report.ads_collected, report.ads_new, len(new_items),
    )

    return new_items


def _pydantic_to_dict(model) -> dict:
    """Safely convert a Pydantic model to a JSON-serializable dict."""
    try:
        return model.model_dump(mode="json")
    except (AttributeError, TypeError):
        return model.dict()


def _db_item_to_canonical(item: CICanonicalItem):
    """Convert a DB CICanonicalItem row to an engine CanonicalItem model."""
    from src.engines.opportunity_engine.models import CanonicalItem

    item_type_str = item.item_type.value if hasattr(item.item_type, "value") else str(item.item_type)
    canonical = item.canonical_json or {}

    return CanonicalItem(
        id=str(item.id),
        source="ci_module",
        platform=canonical.get("platform", ""),
        competitor=canonical.get("competitor", ""),
        item_type=item_type_str,
        headline=item.title or "",
        body=item.body_text or "",
        cta=canonical.get("cta", ""),
        format=canonical.get("format", ""),
        country=canonical.get("country", ""),
        price=canonical.get("price"),
        discount=canonical.get("discount", ""),
        guarantee=canonical.get("guarantee", ""),
        keywords=canonical.get("keywords", []),
        fingerprint=canonical.get("fingerprint", ""),
        first_seen=item.first_seen_at,
        last_seen=item.last_seen_at,
        metadata=canonical,
    )


def _opp_type_to_alert_type(opp_type) -> str | None:
    """Map opportunity type to alert_type string.

    Uses the raw opportunity type directly so the frontend can filter by it
    (e.g. 'angle_trend_rise', 'competitor_offer_change').
    """
    opp_val = opp_type.value if hasattr(opp_type, "value") else str(opp_type)
    valid = {
        "new_ads_spike", "angle_trend_rise", "competitor_offer_change",
        "format_dominance_shift", "keyword_emergence",
    }
    return opp_val if opp_val in valid else None


def _score_to_severity(priority_score: float) -> str:
    """Map opportunity priority score to alert severity."""
    if priority_score >= 0.7:
        return "high"
    if priority_score >= 0.4:
        return "medium"
    return "low"


def _create_ci_alert(
    db: Session,
    org_id: UUID,
    alert_type: str,
    severity: str,
    title: str,
    description: str,
    evidence_ids: list[str] | None = None,
    rationale: str = "",
    suggested_actions: list[str] | None = None,
):
    """Create a CI alert in the MetaAlert table (reuses Alert Center)."""
    severity_map = {
        "critical": AlertSeverity.CRITICAL,
        "high": AlertSeverity.HIGH,
        "medium": AlertSeverity.MEDIUM,
        "low": AlertSeverity.LOW,
        "info": AlertSeverity.INFO,
    }

    alert = MetaAlert(
        id=uuid4(),
        org_id=org_id,
        ad_account_id=None,  # CI alerts are not tied to an ad account
        alert_type=alert_type,
        severity=severity_map.get(severity, AlertSeverity.MEDIUM),
        message=f"{title}: {description}"[:2000],
        entity_type="ci_opportunity",
        entity_meta_id=None,
        detected_at=datetime.utcnow(),
        status="active",
        payload_json={
            "evidence_ids": evidence_ids or [],
            "rationale": rationale,
            "suggested_actions": suggested_actions or [],
            "recommended_next_step": "Open Radar",
        },
    )
    db.add(alert)
    db.flush()
