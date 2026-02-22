"""
BrandMap Profile API — CRUD, LLM analysis, and PDF export.
Multi-brand ready: each org can have multiple brand profiles.
"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from uuid import uuid4, UUID
import io

from sqlalchemy import func

from backend.src.database.session import get_db
from backend.src.database.models import (
    BrandMapProfile, MetaInsightsDaily, MetaCampaign,
    MetaAlert, InsightLevel,
)
from backend.src.middleware.auth import get_current_user
from src.utils.logging_config import logger

router = APIRouter(tags=["brandmap"])


# ── Pydantic schemas ────────────────────────────────────────────────────────


class BrandMapCreate(BaseModel):
    name: str
    raw_text: str


class BrandMapUpdate(BaseModel):
    name: Optional[str] = None
    raw_text: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────


def _to_response(profile: BrandMapProfile) -> dict:
    return {
        "id": str(profile.id),
        "org_id": str(profile.org_id),
        "name": profile.name,
        "raw_text": profile.raw_text,
        "structured_json": profile.structured_json,
        "status": profile.status,
        "last_analyzed_at": profile.last_analyzed_at.isoformat() if profile.last_analyzed_at else None,
        "last_error": profile.last_error,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def _build_meta_performance_context(db: Session, org_id: str, days: int = 90) -> dict:
    """
    Query real Meta campaign data and build a structured performance context.
    Returns both a text summary (for LLM consumption) and structured metrics (for UI).
    """
    from datetime import timedelta
    since_dt = datetime.utcnow() - timedelta(days=days)

    # ── Aggregate totals ────────────────────────────────────────────────────
    totals = db.query(
        func.coalesce(func.sum(MetaInsightsDaily.spend), 0).label("total_spend"),
        func.coalesce(func.sum(MetaInsightsDaily.impressions), 0).label("total_impressions"),
        func.coalesce(func.sum(MetaInsightsDaily.clicks), 0).label("total_clicks"),
        func.coalesce(func.sum(MetaInsightsDaily.conversions), 0).label("total_conversions"),
        func.count(func.distinct(MetaInsightsDaily.entity_meta_id)).label("campaign_count"),
        func.min(MetaInsightsDaily.date_start).label("earliest_date"),
        func.max(MetaInsightsDaily.date_start).label("latest_date"),
    ).filter(
        MetaInsightsDaily.org_id == org_id,
        MetaInsightsDaily.level == InsightLevel.CAMPAIGN,
        MetaInsightsDaily.date_start >= since_dt,
    ).one()

    total_spend = float(totals.total_spend or 0)
    total_impressions = int(totals.total_impressions or 0)
    total_clicks = int(totals.total_clicks or 0)
    total_conversions = int(totals.total_conversions or 0)
    campaign_count = int(totals.campaign_count or 0)

    if campaign_count == 0:
        return {"has_data": False, "text": "", "metrics": {}}

    avg_ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
    avg_cpc = (total_spend / total_clicks) if total_clicks > 0 else 0
    avg_cpm = (total_spend / total_impressions * 1000) if total_impressions > 0 else 0

    # ── Top campaigns by spend ──────────────────────────────────────────────
    top_campaigns_q = db.query(
        MetaInsightsDaily.entity_meta_id,
        func.sum(MetaInsightsDaily.spend).label("spend"),
        func.sum(MetaInsightsDaily.impressions).label("impressions"),
        func.sum(MetaInsightsDaily.clicks).label("clicks"),
        func.sum(MetaInsightsDaily.conversions).label("conversions"),
    ).filter(
        MetaInsightsDaily.org_id == org_id,
        MetaInsightsDaily.level == InsightLevel.CAMPAIGN,
        MetaInsightsDaily.date_start >= since_dt,
    ).group_by(
        MetaInsightsDaily.entity_meta_id,
    ).order_by(
        func.sum(MetaInsightsDaily.spend).desc(),
    ).limit(10).all()

    # Get campaign names
    campaign_ids = [r.entity_meta_id for r in top_campaigns_q]
    name_map = {}
    objective_map = {}
    if campaign_ids:
        campaigns = db.query(
            MetaCampaign.meta_campaign_id, MetaCampaign.name, MetaCampaign.objective
        ).filter(
            MetaCampaign.org_id == org_id,
            MetaCampaign.meta_campaign_id.in_(campaign_ids),
        ).all()
        for c in campaigns:
            name_map[c.meta_campaign_id] = c.name or c.meta_campaign_id
            objective_map[c.meta_campaign_id] = c.objective or "Unknown"

    top_campaigns = []
    for r in top_campaigns_q:
        c_spend = float(r.spend or 0)
        c_impressions = int(r.impressions or 0)
        c_clicks = int(r.clicks or 0)
        c_conversions = int(r.conversions or 0)
        c_ctr = (c_clicks / c_impressions * 100) if c_impressions > 0 else 0
        top_campaigns.append({
            "id": r.entity_meta_id,
            "name": name_map.get(r.entity_meta_id, r.entity_meta_id),
            "objective": objective_map.get(r.entity_meta_id, "Unknown"),
            "spend": round(c_spend, 2),
            "impressions": c_impressions,
            "clicks": c_clicks,
            "conversions": c_conversions,
            "ctr": round(c_ctr, 2),
        })

    # ── Objective distribution ──────────────────────────────────────────────
    objective_dist = {}
    for tc in top_campaigns:
        obj = tc["objective"]
        if obj not in objective_dist:
            objective_dist[obj] = {"count": 0, "spend": 0}
        objective_dist[obj]["count"] += 1
        objective_dist[obj]["spend"] += tc["spend"]

    # ── Recent alerts count ─────────────────────────────────────────────────
    alert_count = db.query(func.count(MetaAlert.id)).filter(
        MetaAlert.org_id == org_id,
        MetaAlert.detected_at >= since_dt,
    ).scalar() or 0

    # ── Build text context for LLM ──────────────────────────────────────────
    date_range_str = ""
    if totals.earliest_date and totals.latest_date:
        date_range_str = f" ({totals.earliest_date.strftime('%Y-%m-%d')} to {totals.latest_date.strftime('%Y-%m-%d')})"

    lines = [
        f"\n\n=== REAL CAMPAIGN PERFORMANCE DATA (Last {days} days{date_range_str}) ===",
        f"Total campaigns tracked: {campaign_count}",
        f"Total spend: ${total_spend:,.2f}",
        f"Total impressions: {total_impressions:,}",
        f"Total clicks: {total_clicks:,}",
        f"Total conversions: {total_conversions:,}",
        f"Average CTR: {avg_ctr:.2f}%",
        f"Average CPC: ${avg_cpc:.2f}",
        f"Average CPM: ${avg_cpm:.2f}",
        f"Active alerts in period: {alert_count}",
        "",
        "Top campaigns by spend:",
    ]
    for i, tc in enumerate(top_campaigns[:10], 1):
        lines.append(
            f"  {i}. {tc['name']} (Objective: {tc['objective']}) — "
            f"Spend: ${tc['spend']:,.2f}, CTR: {tc['ctr']:.2f}%, "
            f"Clicks: {tc['clicks']:,}, Conversions: {tc['conversions']:,}"
        )

    if objective_dist:
        lines.append("")
        lines.append("Budget distribution by objective:")
        for obj, data in sorted(objective_dist.items(), key=lambda x: x[1]["spend"], reverse=True):
            lines.append(f"  - {obj}: {data['count']} campaigns, ${data['spend']:,.2f} spend")

    lines.append("")
    lines.append(
        "Use this real performance data to inform the brand analysis: "
        "identify what campaign objectives and strategies the brand is actually investing in, "
        "which approaches are generating the best returns (high CTR, conversions), "
        "and where there may be underperforming areas that present opportunities for improvement."
    )
    lines.append("=== END CAMPAIGN DATA ===")

    text = "\n".join(lines)

    metrics = {
        "period_days": days,
        "campaign_count": campaign_count,
        "total_spend": round(total_spend, 2),
        "total_impressions": total_impressions,
        "total_clicks": total_clicks,
        "total_conversions": total_conversions,
        "avg_ctr": round(avg_ctr, 2),
        "avg_cpc": round(avg_cpc, 2),
        "avg_cpm": round(avg_cpm, 2),
        "alert_count": alert_count,
        "top_campaigns": top_campaigns,
        "objective_distribution": objective_dist,
        "date_range": date_range_str.strip(" ()"),
    }

    return {"has_data": True, "text": text, "metrics": metrics}


# ── Endpoints ────────────────────────────────────────────────────────────────
# IMPORTANT: Static paths (/export/pdf) MUST come before dynamic paths (/{profile_id})
# to prevent FastAPI from matching "export" as a profile_id.


@router.get("/")
def list_brand_profiles(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List all brand profiles for the current org."""
    org_id = UUID(user.get("org_id"))
    profiles = (
        db.query(BrandMapProfile)
        .filter(BrandMapProfile.org_id == org_id)
        .order_by(BrandMapProfile.created_at.desc())
        .all()
    )
    return [_to_response(p) for p in profiles]


@router.post("/", status_code=201)
def create_brand_profile(
    body: BrandMapCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Create a new brand profile. Starts in pending_analysis status."""
    org_id = UUID(user.get("org_id"))
    profile = BrandMapProfile(
        id=uuid4(),
        org_id=org_id,
        name=body.name,
        raw_text=body.raw_text,
        status="pending_analysis",
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    logger.info(f"BRANDMAP_CREATED | org_id={org_id} | profile_id={profile.id} | name={body.name}")
    return _to_response(profile)


@router.get("/export/pdf")
def export_brand_profile_pdf(
    profile_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Export a brand profile as PDF. If profile_id is not given, exports the most recent
    'ready' profile for the org.
    """
    org_id = UUID(user.get("org_id"))

    if profile_id:
        profile = (
            db.query(BrandMapProfile)
            .filter(BrandMapProfile.id == UUID(profile_id), BrandMapProfile.org_id == org_id)
            .first()
        )
    else:
        profile = (
            db.query(BrandMapProfile)
            .filter(BrandMapProfile.org_id == org_id, BrandMapProfile.status == "ready")
            .order_by(BrandMapProfile.last_analyzed_at.desc())
            .first()
        )

    if not profile:
        raise HTTPException(status_code=404, detail="No analyzed brand profile found")

    if not profile.structured_json:
        raise HTTPException(status_code=400, detail="Brand profile has not been analyzed yet")

    pdf_bytes = _build_brand_pdf(profile)
    buf = io.BytesIO(pdf_bytes)
    filename = f"brand_profile_{profile.name.replace(' ', '_')}.pdf"

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# Dynamic path routes AFTER static paths
@router.get("/{profile_id}")
def get_brand_profile(
    profile_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get a single brand profile by ID."""
    org_id = UUID(user.get("org_id"))
    profile = (
        db.query(BrandMapProfile)
        .filter(BrandMapProfile.id == UUID(profile_id), BrandMapProfile.org_id == org_id)
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Brand profile not found")
    return _to_response(profile)


@router.put("/{profile_id}")
def update_brand_profile(
    profile_id: str,
    body: BrandMapUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Update brand profile name and/or raw_text. If raw_text changes, resets status to pending_analysis."""
    org_id = UUID(user.get("org_id"))
    profile = (
        db.query(BrandMapProfile)
        .filter(BrandMapProfile.id == UUID(profile_id), BrandMapProfile.org_id == org_id)
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Brand profile not found")

    if body.name is not None:
        profile.name = body.name
    if body.raw_text is not None:
        profile.raw_text = body.raw_text
        profile.status = "pending_analysis"
        profile.structured_json = None

    profile.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(profile)
    logger.info(f"BRANDMAP_UPDATED | profile_id={profile_id}")
    return _to_response(profile)


@router.delete("/{profile_id}", status_code=204)
def delete_brand_profile(
    profile_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Delete a brand profile."""
    org_id = UUID(user.get("org_id"))
    profile = (
        db.query(BrandMapProfile)
        .filter(BrandMapProfile.id == UUID(profile_id), BrandMapProfile.org_id == org_id)
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Brand profile not found")
    db.delete(profile)
    db.commit()
    logger.info(f"BRANDMAP_DELETED | profile_id={profile_id}")


@router.post("/{profile_id}/analyze")
def analyze_brand_profile(
    profile_id: str,
    days: int = 90,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Trigger LLM analysis on the brand profile's raw_text + real Meta campaign data.
    1. Queries MetaInsightsDaily + MetaCampaign for actual performance context
    2. Appends campaign data to brand text for richer LLM analysis
    3. Stores both the 9-layer brand map AND the performance context in structured_json
    Runs synchronously (typically 10-20s depending on LLM provider).
    """
    org_id = UUID(user.get("org_id"))
    profile = (
        db.query(BrandMapProfile)
        .filter(BrandMapProfile.id == UUID(profile_id), BrandMapProfile.org_id == org_id)
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Brand profile not found")

    profile.status = "analyzing"
    profile.last_error = None
    db.commit()

    try:
        # Step 1: Build Meta performance context from real campaign data
        meta_context = _build_meta_performance_context(db, org_id, days=days)
        logger.info(
            f"BRANDMAP_META_CONTEXT | profile_id={profile_id} | "
            f"has_data={meta_context['has_data']} | "
            f"campaigns={meta_context.get('metrics', {}).get('campaign_count', 0)}"
        )

        # Step 2: Combine brand text + campaign data for enriched analysis
        enriched_text = profile.raw_text
        if meta_context["has_data"]:
            enriched_text = profile.raw_text + meta_context["text"]

        # Step 3: Run LLM analysis on the enriched text
        from src.engines.brand_map.builder import BrandMapBuilder
        builder = BrandMapBuilder()
        brand_map = builder.build(enriched_text)

        # Step 4: Store both brand map and performance context
        structured = brand_map.model_dump(exclude={"metadata"})
        structured["_meta_performance"] = meta_context.get("metrics", {}) if meta_context["has_data"] else None
        profile.structured_json = structured
        profile.status = "ready"
        profile.last_analyzed_at = datetime.utcnow()
        profile.last_error = None
        db.commit()
        db.refresh(profile)
        logger.info(f"BRANDMAP_ANALYZED | profile_id={profile_id} | status=ready | meta_enriched={meta_context['has_data']}")
        return _to_response(profile)

    except Exception as e:
        profile.status = "error"
        profile.last_error = str(e)[:500]
        db.commit()
        db.refresh(profile)
        logger.error(f"BRANDMAP_ANALYSIS_FAILED | profile_id={profile_id} | error={e}")
        return _to_response(profile)


# ── PDF Builder ──────────────────────────────────────────────────────────────


def _build_brand_pdf(profile: BrandMapProfile) -> bytes:
    """Build a comprehensive PDF from a brand profile's structured_json."""
    from fpdf import FPDF

    data = profile.structured_json or {}
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, f"Brand Profile: {profile.name}", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    date_label = profile.last_analyzed_at.strftime("%Y-%m-%d %H:%M") if profile.last_analyzed_at else "N/A"
    pdf.cell(0, 6, f"Analyzed: {date_label}", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(6)

    def section_title(title: str):
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_fill_color(245, 245, 240)
        pdf.cell(0, 10, f"  {title}", ln=True, fill=True)
        pdf.ln(2)

    def field(label: str, value: str):
        if not value:
            return
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(40, 6, f"{label}:", ln=False)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, str(value)[:500])
        pdf.ln(1)

    def list_field(label: str, items: list):
        if not items:
            return
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, f"{label}:", ln=True)
        pdf.set_font("Helvetica", "", 10)
        for item in items[:20]:
            text = str(item)[:200]
            pdf.cell(8)
            pdf.multi_cell(0, 5, f"- {text}")

    # 0. Campaign Performance Context (if available)
    meta_perf = data.get("_meta_performance")
    if meta_perf and meta_perf.get("campaign_count", 0) > 0:
        section_title("Campaign Performance Intelligence")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, f"Data period: {meta_perf.get('date_range', 'N/A')} ({meta_perf.get('period_days', 0)} days)", ln=True)
        pdf.ln(3)

        # KPI summary row
        kpis = [
            ("Campaigns", str(meta_perf.get("campaign_count", 0))),
            ("Total Spend", f"${meta_perf.get('total_spend', 0):,.2f}"),
            ("Impressions", f"{meta_perf.get('total_impressions', 0):,}"),
            ("Clicks", f"{meta_perf.get('total_clicks', 0):,}"),
            ("Conversions", f"{meta_perf.get('total_conversions', 0):,}"),
            ("Avg CTR", f"{meta_perf.get('avg_ctr', 0):.2f}%"),
            ("Avg CPC", f"${meta_perf.get('avg_cpc', 0):.2f}"),
            ("Avg CPM", f"${meta_perf.get('avg_cpm', 0):.2f}"),
        ]
        for label, value in kpis:
            field(label, value)

        # Top campaigns table
        top_camps = meta_perf.get("top_campaigns", [])
        if top_camps:
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 6, "Top Campaigns by Spend:", ln=True)
            pdf.set_font("Helvetica", "", 9)
            for tc in top_camps[:8]:
                pdf.cell(8)
                pdf.multi_cell(
                    0, 5,
                    f"- {tc['name']} ({tc['objective']}) — "
                    f"${tc['spend']:,.2f} spend, {tc['ctr']:.2f}% CTR, "
                    f"{tc['conversions']:,} conversions"
                )

        pdf.ln(6)

    # 1. Core Identity
    ci = data.get("core_identity", {})
    section_title("1. Core Identity")
    field("Mission", ci.get("mission", ""))
    list_field("Values", ci.get("values", []))
    field("Tone & Voice", ci.get("tone_voice", ""))
    list_field("Personality Traits", ci.get("personality_traits", []))
    pdf.ln(4)

    # 2. Offer Layer
    ol = data.get("offer_layer", {})
    section_title("2. Offer Layer")
    field("Main Product", ol.get("main_product", ""))
    list_field("Upsells", ol.get("upsells", []))
    field("Pricing Psychology", ol.get("pricing_psychology", ""))
    field("Risk Reversal", ol.get("risk_reversal", ""))
    pdf.ln(4)

    # 3. Audience Model
    avatars = data.get("audience_model", [])
    section_title("3. Audience Model")
    for i, av in enumerate(avatars[:5]):
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, f"Avatar {i+1}: {av.get('avatar_name', 'Unknown')}", ln=True)
        field("Demographics", av.get("demographics", ""))
        field("Psychographics", av.get("psychographics", ""))
        list_field("Pains", av.get("pains", []))
        list_field("Desires", av.get("desires", []))
        list_field("Triggers", av.get("triggers", []))
        pdf.ln(2)
    pdf.ln(2)

    # 4. Differentiation
    dl = data.get("differentiation_layer", {})
    section_title("4. Differentiation")
    field("USP", dl.get("usp", ""))
    field("Competitive Moat", dl.get("competitive_moat", ""))
    list_field("Proof Points", dl.get("proof_points", []))
    pdf.ln(4)

    # 5. Narrative Assets
    na = data.get("narrative_assets", {})
    section_title("5. Narrative Assets")
    field("Brand Lore", na.get("lore", ""))
    list_field("Story Hooks", na.get("story_hooks", []))
    list_field("Core Myths", na.get("core_myths", []))
    pdf.ln(4)

    # 6. Creative DNA
    cd = data.get("creative_dna", {})
    section_title("6. Creative DNA")
    list_field("Color Palette", cd.get("color_palette", []))
    field("Typography Intent", cd.get("typography_intent", ""))
    list_field("Visual Constraints", cd.get("visual_constraints", []))
    pdf.ln(4)

    # 7. Market Context
    mc = data.get("market_context", {})
    section_title("7. Market Context")
    list_field("Seasonal Factors", mc.get("seasonal_factors", []))
    list_field("Current Trends", mc.get("current_trends", []))
    pdf.ln(4)

    # 8. Competitor Map
    comps = data.get("competitor_map", [])
    section_title("8. Competitor Map")
    for comp in comps[:10]:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, comp.get("name", "Unknown"), ln=True)
        field("Strategy", comp.get("strategy_type", ""))
        list_field("Weak Points", comp.get("weak_points", []))
        pdf.ln(2)
    pdf.ln(2)

    # 9. Opportunity Map
    opps = data.get("opportunity_map", [])
    section_title("9. Opportunity Map")
    for opp in opps[:10]:
        pdf.set_font("Helvetica", "B", 11)
        gap_id = opp.get("gap_id", "")
        impact = opp.get("estimated_impact", 0)
        pdf.cell(0, 7, f"{gap_id} (Impact: {impact}%)", ln=True)
        field("Strategy", opp.get("strategy_recommendation", ""))
        field("Reasoning", opp.get("impact_reasoning", ""))
        pdf.ln(2)

    return pdf.output()
