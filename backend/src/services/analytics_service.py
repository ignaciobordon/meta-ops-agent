"""Analytics service: smart bucketing, SQL aggregation, trends, insights engine."""
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.src.database.models import (
    MetaCampaign,
    MetaInsightsDaily,
    MetaAdAccount,
    InsightLevel,
)
from backend.src.utils.meta_helpers import OBJECTIVE_LABELS, parse_date_range

# ── Objective labels (override shared labels for analytics categorisation) ───

_OBJECTIVE_LABELS = {**OBJECTIVE_LABELS, "LINK_CLICKS": "Traffic", "POST_ENGAGEMENT": "Engagement"}

# ── Helpers ───────────────────────────────────────────────────────────────────


def _apply_date_filter(query, since_dt, until_dt):
    """Apply date range filter to a query."""
    query = query.filter(MetaInsightsDaily.date_start >= since_dt)
    if until_dt:
        query = query.filter(MetaInsightsDaily.date_start < until_dt)
    return query


def _safe_pct_change(cur, prev):
    """Compute percentage change, safe for zero/None."""
    if prev is None or prev == 0:
        return None
    return round((cur - prev) / abs(prev) * 100, 1)


# ── get_metrics_over_time (smart bucketing) ──────────────────────────────────

def get_metrics_over_time(
    db: Session, org_id: UUID, days: int = 30,
    since: Optional[str] = None, until: Optional[str] = None,
    ad_account_id: Optional[UUID] = None,
) -> dict:
    """Aggregate metrics with smart bucketing based on date span."""
    since_dt, until_dt = parse_date_range(days, since, until)
    effective_until = until_dt or datetime.utcnow()
    span_days = (effective_until - since_dt).days

    # Determine bucket type
    if span_days <= 30:
        bucket_type = "daily"
    elif span_days <= 90:
        bucket_type = "weekly"
    else:
        bucket_type = "monthly"

    # Base query: aggregate all campaign-level rows per day
    base = db.query(
        MetaInsightsDaily.date_start,
        MetaInsightsDaily.spend,
        MetaInsightsDaily.clicks,
        MetaInsightsDaily.impressions,
        MetaInsightsDaily.conversions,
        MetaInsightsDaily.frequency,
    ).filter(
        MetaInsightsDaily.org_id == org_id,
        MetaInsightsDaily.level == InsightLevel.CAMPAIGN,
    )
    if ad_account_id:
        base = base.filter(MetaInsightsDaily.ad_account_id == ad_account_id)
    base = _apply_date_filter(base, since_dt, until_dt)
    rows = base.all()

    if not rows:
        return {"buckets": [], "bucket_type": bucket_type}

    # Group rows into buckets
    from collections import defaultdict
    bucket_map = defaultdict(lambda: {"spend": 0, "clicks": 0, "impressions": 0, "conversions": 0})

    for r in rows:
        dt = r.date_start if isinstance(r.date_start, datetime) else datetime.strptime(str(r.date_start), "%Y-%m-%d")

        if bucket_type == "daily":
            key = dt.strftime("%b %d")
            sort_key = dt.strftime("%Y-%m-%d")
        elif bucket_type == "weekly":
            # Week number within month
            week_num = (dt.day - 1) // 7 + 1
            key = f"W{week_num} {dt.strftime('%b')}"
            # Sort by start of week
            sort_key = dt.strftime("%Y-%W")
        else:  # monthly
            key = dt.strftime("%b %Y")
            sort_key = dt.strftime("%Y-%m")

        b = bucket_map[(sort_key, key)]
        b["spend"] += float(r.spend or 0)
        b["clicks"] += int(r.clicks or 0)
        b["impressions"] += int(r.impressions or 0)
        b["conversions"] += int(r.conversions or 0)

    # Build sorted output
    buckets = []
    for (sort_key, label), data in sorted(bucket_map.items(), key=lambda x: x[0][0]):
        impr = data["impressions"]
        clicks = data["clicks"]
        spend = data["spend"]
        ctr = (clicks / impr * 100) if impr > 0 else 0
        cpc = (spend / clicks) if clicks > 0 else 0
        cpm = (spend / impr * 1000) if impr > 0 else 0

        buckets.append({
            "label": label,
            "spend": round(spend, 2),
            "clicks": clicks,
            "impressions": impr,
            "ctr": round(ctr, 2),
            "cpc": round(cpc, 2),
            "cpm": round(cpm, 2),
            "conversions": data["conversions"],
        })

    return {"buckets": buckets, "bucket_type": bucket_type}


# ── get_performance_summary (SQL aggregation + trends) ───────────────────────

def get_performance_summary(
    db: Session, org_id: UUID, days: int = 7,
    since: Optional[str] = None, until: Optional[str] = None,
    ad_account_id: Optional[UUID] = None,
) -> dict:
    """Aggregate performance summary with period-over-period trends."""
    since_dt, until_dt = parse_date_range(days, since, until)
    effective_until = until_dt or datetime.utcnow()
    span = effective_until - since_dt

    # Previous period of same length
    prev_since = since_dt - span
    prev_until = since_dt

    def _aggregate(s_dt, u_dt):
        q = db.query(
            func.coalesce(func.sum(MetaInsightsDaily.spend), 0).label("spend"),
            func.coalesce(func.sum(MetaInsightsDaily.impressions), 0).label("impressions"),
            func.coalesce(func.sum(MetaInsightsDaily.clicks), 0).label("clicks"),
            func.coalesce(func.sum(MetaInsightsDaily.conversions), 0).label("conversions"),
            func.avg(MetaInsightsDaily.purchase_roas).label("avg_roas"),
        ).filter(
            MetaInsightsDaily.org_id == org_id,
            MetaInsightsDaily.level == InsightLevel.CAMPAIGN,
            MetaInsightsDaily.date_start >= s_dt,
        )
        if ad_account_id:
            q = q.filter(MetaInsightsDaily.ad_account_id == ad_account_id)
        if u_dt:
            q = q.filter(MetaInsightsDaily.date_start < u_dt)
        row = q.one()
        spend = float(row.spend or 0)
        impressions = int(row.impressions or 0)
        clicks = int(row.clicks or 0)
        conversions = int(row.conversions or 0)
        avg_roas = float(row.avg_roas or 0)

        ctr = (clicks / impressions * 100) if impressions > 0 else 0
        cpc = (spend / clicks) if clicks > 0 else 0
        cpm = (spend / impressions * 1000) if impressions > 0 else 0

        return {
            "spend": round(spend, 2),
            "impressions": impressions,
            "clicks": clicks,
            "conversions": conversions,
            "ctr": round(ctr, 2),
            "cpc": round(cpc, 2),
            "cpm": round(cpm, 2),
            "roas": round(avg_roas, 2),
        }

    cur = _aggregate(since_dt, until_dt)
    prev = _aggregate(prev_since, prev_until)

    # Count active campaigns
    active_campaigns = db.query(
        func.count(func.distinct(MetaInsightsDaily.entity_meta_id))
    ).filter(
        MetaInsightsDaily.org_id == org_id,
        MetaInsightsDaily.level == InsightLevel.CAMPAIGN,
        MetaInsightsDaily.date_start >= since_dt,
    )
    if ad_account_id:
        active_campaigns = active_campaigns.filter(MetaInsightsDaily.ad_account_id == ad_account_id)
    if until_dt:
        active_campaigns = active_campaigns.filter(MetaInsightsDaily.date_start < until_dt)
    active_count = active_campaigns.scalar() or 0

    # Resolve currency
    if ad_account_id:
        acc = db.query(MetaAdAccount.currency).filter(MetaAdAccount.id == ad_account_id).first()
        currency = acc.currency if acc else "USD"
    else:
        currencies = db.query(func.distinct(MetaAdAccount.currency)).filter(
            MetaAdAccount.org_id == org_id
        ).all()
        if len(currencies) > 1:
            currency = "MIXED"
        elif currencies:
            currency = currencies[0][0]
        else:
            currency = "USD"

    return {
        "total_spend": cur["spend"],
        "total_impressions": cur["impressions"],
        "total_clicks": cur["clicks"],
        "total_conversions": cur["conversions"],
        "avg_ctr": cur["ctr"],
        "avg_cpc": cur["cpc"],
        "avg_cpm": cur["cpm"],
        "avg_roas": cur["roas"],
        "active_campaigns": active_count,
        "period_days": days,
        "currency": currency,
        # Trends (pct change vs previous period)
        "spend_trend": _safe_pct_change(cur["spend"], prev["spend"]),
        "impressions_trend": _safe_pct_change(cur["impressions"], prev["impressions"]),
        "clicks_trend": _safe_pct_change(cur["clicks"], prev["clicks"]),
        "conversions_trend": _safe_pct_change(cur["conversions"], prev["conversions"]),
        "ctr_trend": _safe_pct_change(cur["ctr"], prev["ctr"]),
        "cpc_trend": _safe_pct_change(cur["cpc"], prev["cpc"]),
        "roas_trend": _safe_pct_change(cur["roas"], prev["roas"]),
    }


# ── get_spend_over_time (kept for backwards compat) ─────────────────────────

def get_spend_over_time(
    db: Session, org_id: UUID, days: int = 30,
    since: Optional[str] = None, until: Optional[str] = None,
    ad_account_id: Optional[UUID] = None,
) -> List[dict]:
    """Get daily spend aggregation."""
    since_dt, until_dt = parse_date_range(days, since, until)

    query = db.query(
        MetaInsightsDaily.date_start,
        func.sum(MetaInsightsDaily.spend).label("total_spend"),
    ).filter(
        MetaInsightsDaily.org_id == org_id,
        MetaInsightsDaily.level == InsightLevel.CAMPAIGN,
    )
    if ad_account_id:
        query = query.filter(MetaInsightsDaily.ad_account_id == ad_account_id)
    query = _apply_date_filter(query, since_dt, until_dt)

    rows = query.group_by(
        MetaInsightsDaily.date_start,
    ).order_by(
        MetaInsightsDaily.date_start,
    ).all()

    return [
        {
            "date": r.date_start.strftime("%Y-%m-%d") if hasattr(r.date_start, 'strftime') else str(r.date_start),
            "spend": round(float(r.total_spend or 0), 2),
        }
        for r in rows
    ]


# ── get_top_campaigns (JOIN fix + enriched data) ────────────────────────────

def get_top_campaigns(
    db: Session, org_id: UUID, days: int = 7, limit: int = 20,
    since: Optional[str] = None, until: Optional[str] = None,
    ad_account_id: Optional[UUID] = None,
) -> List[dict]:
    """Get top campaigns by spend with objective, status, and enriched metrics."""
    since_dt, until_dt = parse_date_range(days, since, until)

    # Single query with JOIN — eliminates N+1
    query = db.query(
        MetaInsightsDaily.entity_meta_id,
        func.sum(MetaInsightsDaily.spend).label("total_spend"),
        func.sum(MetaInsightsDaily.clicks).label("total_clicks"),
        func.sum(MetaInsightsDaily.impressions).label("total_impressions"),
        func.sum(MetaInsightsDaily.conversions).label("total_conversions"),
        func.avg(MetaInsightsDaily.purchase_roas).label("avg_roas"),
        func.avg(MetaInsightsDaily.frequency).label("avg_frequency"),
        MetaCampaign.name,
        MetaCampaign.objective,
        MetaCampaign.status,
    ).outerjoin(
        MetaCampaign,
        (MetaCampaign.meta_campaign_id == MetaInsightsDaily.entity_meta_id) &
        (MetaCampaign.org_id == MetaInsightsDaily.org_id),
    ).filter(
        MetaInsightsDaily.org_id == org_id,
        MetaInsightsDaily.level == InsightLevel.CAMPAIGN,
    )
    if ad_account_id:
        query = query.filter(MetaInsightsDaily.ad_account_id == ad_account_id)
    query = _apply_date_filter(query, since_dt, until_dt)

    rows = query.group_by(
        MetaInsightsDaily.entity_meta_id,
        MetaCampaign.name,
        MetaCampaign.objective,
        MetaCampaign.status,
    ).order_by(
        func.sum(MetaInsightsDaily.spend).desc(),
    ).limit(limit).all()

    results = []
    for r in rows:
        impressions = int(r.total_impressions or 0)
        clicks = int(r.total_clicks or 0)
        spend = float(r.total_spend or 0)
        conversions = int(r.total_conversions or 0)

        ctr = (clicks / impressions * 100) if impressions > 0 else 0
        cpc = (spend / clicks) if clicks > 0 else 0
        cpm = (spend / impressions * 1000) if impressions > 0 else 0
        roas = float(r.avg_roas or 0)
        frequency = float(r.avg_frequency or 0)

        raw_obj = r.objective or ""
        objective_label = _OBJECTIVE_LABELS.get(raw_obj, raw_obj.replace("_", " ").title() if raw_obj else "—")

        results.append({
            "campaign_id": r.entity_meta_id,
            "name": r.name or r.entity_meta_id,
            "objective": objective_label,
            "status": (r.status or "UNKNOWN").upper(),
            "spend": round(spend, 2),
            "clicks": clicks,
            "impressions": impressions,
            "conversions": conversions,
            "ctr": round(ctr, 2),
            "cpc": round(cpc, 2),
            "cpm": round(cpm, 2),
            "roas": round(roas, 2),
            "frequency": round(frequency, 2),
        })

    return results


# ── generate_insights (rule-based engine) ────────────────────────────────────

def generate_insights(
    db: Session, org_id: UUID, days: int = 30,
    since: Optional[str] = None, until: Optional[str] = None,
    ad_account_id: Optional[UUID] = None,
    conversion_model: Optional[str] = None,
) -> List[dict]:
    """Generate rule-based insights from analytics data.

    Args:
        conversion_model: "online" (default), "offline", or "hybrid".
            If "offline", rules about zero conversions and ROAS are skipped
            because sales happen outside Meta.
    """
    since_dt, until_dt = parse_date_range(days, since, until)
    effective_until = until_dt or datetime.utcnow()
    span = effective_until - since_dt

    # Get current summary
    cur_summary = get_performance_summary(db, org_id, days, since, until, ad_account_id)

    # Get campaign-level data for detailed rules
    campaigns = get_top_campaigns(db, org_id, days, 50, since, until, ad_account_id)

    insights = []

    # ── Rule 1: Spend spike/drop (>30% change vs prior period) ──
    spend_trend = cur_summary.get("spend_trend")
    if spend_trend is not None:
        if spend_trend > 30:
            insights.append({
                "type": "warning",
                "title": "Spend spike detected",
                "description": f"Spend increased {spend_trend}% compared to the previous period. Review budget allocations to ensure this is intentional.",
                "metric_value": f"+{spend_trend}%",
            })
        elif spend_trend < -30:
            insights.append({
                "type": "info",
                "title": "Spend drop detected",
                "description": f"Spend decreased {abs(spend_trend)}% compared to the previous period. Check if campaigns were paused or budgets reduced.",
                "metric_value": f"{spend_trend}%",
            })

    # ── Rule 2: CTR outlier campaigns ──
    if campaigns:
        avg_ctr = cur_summary.get("avg_ctr", 0)
        if avg_ctr > 0:
            high_ctr = [c for c in campaigns if c["ctr"] > avg_ctr * 2 and c["impressions"] > 100]
            low_ctr = [c for c in campaigns if 0 < c["ctr"] < avg_ctr * 0.5 and c["impressions"] > 100]

            if high_ctr:
                names = ", ".join(c["name"][:30] for c in high_ctr[:3])
                insights.append({
                    "type": "positive",
                    "title": "High CTR campaigns",
                    "description": f"{len(high_ctr)} campaign(s) have CTR >2x the average ({avg_ctr}%): {names}. Consider increasing their budgets.",
                    "metric_value": f"{high_ctr[0]['ctr']}% CTR",
                })

            if low_ctr:
                names = ", ".join(c["name"][:30] for c in low_ctr[:3])
                insights.append({
                    "type": "warning",
                    "title": "Low CTR campaigns",
                    "description": f"{len(low_ctr)} campaign(s) have CTR <0.5x the average: {names}. Review creatives and audience targeting.",
                    "metric_value": f"{low_ctr[0]['ctr']}% CTR",
                })

    # ── Rule 3: CPC efficiency alerts ──
    if campaigns:
        avg_cpc = cur_summary.get("avg_cpc", 0)
        if avg_cpc > 0:
            expensive = [c for c in campaigns if c["cpc"] > avg_cpc * 2 and c["clicks"] > 10]
            if expensive:
                names = ", ".join(c["name"][:30] for c in expensive[:3])
                insights.append({
                    "type": "warning",
                    "title": "High CPC campaigns",
                    "description": f"{len(expensive)} campaign(s) have CPC >2x the average (${avg_cpc:.2f}): {names}. Consider adjusting bids or targeting.",
                    "metric_value": f"${expensive[0]['cpc']:.2f} CPC",
                })

    # ── Rule 4: Top ROAS performers ──
    # Skip when conversion_model is "offline" — ROAS not tracked via Meta
    if campaigns and conversion_model != "offline":
        high_roas = [c for c in campaigns if c["roas"] > 2.0 and c["spend"] > 10]
        if high_roas:
            names = ", ".join(c["name"][:30] for c in high_roas[:3])
            insights.append({
                "type": "positive",
                "title": "Top ROAS performers",
                "description": f"{len(high_roas)} campaign(s) delivering strong ROAS (>2x): {names}. These are your best revenue drivers.",
                "metric_value": f"{high_roas[0]['roas']}x ROAS",
            })

    # ── Rule 5: Frequency fatigue ──
    if campaigns:
        fatigued = [c for c in campaigns if c["frequency"] > 3.0 and c["impressions"] > 100]
        if fatigued:
            names = ", ".join(c["name"][:30] for c in fatigued[:3])
            insights.append({
                "type": "warning",
                "title": "Frequency fatigue risk",
                "description": f"{len(fatigued)} campaign(s) have frequency >3.0: {names}. Audiences may be seeing ads too often — consider refreshing creatives.",
                "metric_value": f"{fatigued[0]['frequency']:.1f}x freq",
            })

    # ── Rule 6: Budget concentration risk ──
    if campaigns:
        total_spend = sum(c["spend"] for c in campaigns)
        if total_spend > 0:
            top = campaigns[0]
            concentration = top["spend"] / total_spend * 100
            if concentration > 50:
                insights.append({
                    "type": "warning",
                    "title": "Budget concentration risk",
                    "description": f'"{top["name"][:40]}" accounts for {concentration:.0f}% of total spend. Diversifying budget can reduce risk.',
                    "metric_value": f"{concentration:.0f}%",
                })

    # ── Rule 7: Zero-conversion campaigns with significant spend ──
    # Skip this rule when conversion_model is "offline" — sales happen outside Meta
    if campaigns and conversion_model != "offline":
        total_spend = sum(c["spend"] for c in campaigns) or 1
        zero_conv = [c for c in campaigns if c["conversions"] == 0 and c["spend"] > total_spend * 0.05]
        if zero_conv:
            wasted = sum(c["spend"] for c in zero_conv)
            names = ", ".join(c["name"][:30] for c in zero_conv[:3])
            insights.append({
                "type": "warning",
                "title": "Zero conversions with spend",
                "description": f"{len(zero_conv)} campaign(s) spent ${wasted:.0f} with zero conversions: {names}. Consider pausing or restructuring.",
                "metric_value": f"${wasted:.0f} wasted",
            })

    # ── Rule 8: Trend momentum ──
    ctr_trend = cur_summary.get("ctr_trend")
    roas_trend = cur_summary.get("roas_trend")
    if ctr_trend is not None and ctr_trend > 15:
        insights.append({
            "type": "positive",
            "title": "CTR trending up",
            "description": f"CTR improved {ctr_trend}% versus the prior period. Your creative and targeting optimizations are paying off.",
            "metric_value": f"+{ctr_trend}%",
        })
    elif ctr_trend is not None and ctr_trend < -15:
        insights.append({
            "type": "warning",
            "title": "CTR declining",
            "description": f"CTR dropped {abs(ctr_trend)}% versus the prior period. Review ad fatigue, audience overlap, or seasonal effects.",
            "metric_value": f"{ctr_trend}%",
        })

    if roas_trend is not None and roas_trend > 20 and conversion_model != "offline":
        insights.append({
            "type": "positive",
            "title": "ROAS improving",
            "description": f"ROAS increased {roas_trend}% versus the prior period. Revenue efficiency is trending positively.",
            "metric_value": f"+{roas_trend}%",
        })

    return insights[:8]  # Max 8 insights


# ── get_daily_breakdown (kept for backwards compat) ─────────────────────────

def get_daily_breakdown(
    db: Session, org_id: UUID, days: int = 30,
    since: Optional[str] = None, until: Optional[str] = None,
    ad_account_id: Optional[UUID] = None,
) -> List[dict]:
    """Get daily breakdown of all key metrics."""
    since_dt, until_dt = parse_date_range(days, since, until)

    query = db.query(
        MetaInsightsDaily.date_start,
        func.sum(MetaInsightsDaily.spend).label("spend"),
        func.sum(MetaInsightsDaily.impressions).label("impressions"),
        func.sum(MetaInsightsDaily.clicks).label("clicks"),
        func.sum(MetaInsightsDaily.conversions).label("conversions"),
    ).filter(
        MetaInsightsDaily.org_id == org_id,
        MetaInsightsDaily.level == InsightLevel.CAMPAIGN,
    )
    if ad_account_id:
        query = query.filter(MetaInsightsDaily.ad_account_id == ad_account_id)
    query = _apply_date_filter(query, since_dt, until_dt)

    rows = query.group_by(
        MetaInsightsDaily.date_start,
    ).order_by(
        MetaInsightsDaily.date_start,
    ).all()

    return [
        {
            "date": r.date_start.strftime("%Y-%m-%d") if hasattr(r.date_start, 'strftime') else str(r.date_start),
            "spend": round(float(r.spend or 0), 2),
            "impressions": int(r.impressions or 0),
            "clicks": int(r.clicks or 0),
            "conversions": int(r.conversions or 0),
        }
        for r in rows
    ]
