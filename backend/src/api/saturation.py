"""
Saturation API - Integrates CP4 (Saturation Engine)
Supports CSV upload for real data + demo CSV fallback.
"""
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import tempfile
import os
import io

from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user, require_operator_or_admin
from src.utils.logging_config import set_trace_id, logger
from uuid import uuid4

router = APIRouter(tags=["saturation"])

# Lazy-load engine when needed (CP4 not yet fully implemented)
def get_saturation_engine():
    try:
        from src.engines.saturation.engine import SaturationEngine
        return SaturationEngine()
    except ImportError:
        raise HTTPException(status_code=501, detail="SaturationEngine not yet implemented (CP4)")


# Helper functions
def _generate_recommendation(creative) -> str:
    """Generate human-readable recommendation from CreativeSaturation."""
    from src.schemas.saturation import CreativeSaturation

    ctr_decline_pct = ((creative.ctr_peak - creative.ctr_recent) / creative.ctr_peak * 100) if creative.ctr_peak > 0 else 0.0

    if creative.recommendation == "keep":
        return f"High potential - scale this creative. Low saturation ({creative.saturation_score:.0f}/100), CTR at {creative.ctr_recent:.2f}% (peak {creative.ctr_peak:.2f}%)"
    elif creative.recommendation == "monitor":
        return f"Monitor closely - moderate saturation ({creative.saturation_score:.0f}/100). CTR declined {ctr_decline_pct:.1f}% from peak. Consider refreshing creative variants"
    elif creative.recommendation == "refresh":
        return f"Refresh recommended - saturation at {creative.saturation_score:.0f}/100. CTR dropped {ctr_decline_pct:.1f}% from peak ({creative.ctr_peak:.2f}% → {creative.ctr_recent:.2f}%). Test new angles"
    else:  # kill
        return f"Rotate out immediately - highly saturated ({creative.saturation_score:.0f}/100). Audience fatigued, CTR declined {ctr_decline_pct:.1f}% ({creative.ctr_peak:.2f}% → {creative.ctr_recent:.2f}%)"


# Response Models
class SaturationMetricResponse(BaseModel):
    angle_id: str
    angle_name: str
    saturation_score: float
    status: str  # "fresh", "moderate", "saturated"
    ctr_trend: float
    frequency: float
    cpm_inflation: float
    recommendation: str
    analyzed_at: str
    # Detailed analysis fields
    frequency_score: float = 0.0       # 0-100 component score
    ctr_decay_score: float = 0.0       # 0-100 component score
    cpm_inflation_score: float = 0.0   # 0-100 component score
    ctr_recent: float = 0.0            # Current CTR %
    ctr_peak: float = 0.0              # Best CTR %
    cpm_recent: float = 0.0            # Current CPM $
    cpm_baseline: float = 0.0          # Baseline CPM $
    total_spend: float = 0.0           # Total USD spent
    total_impressions: int = 0         # Total impressions
    days_active: int = 0               # Days with data
    spend_share_pct: float = 0.0       # % of total spend


def _creative_to_response(creative) -> SaturationMetricResponse:
    """Convert a CreativeSaturation to API response with full analysis detail."""
    if creative.recommendation == "keep":
        status = "fresh"
    elif creative.recommendation == "monitor":
        status = "moderate"
    else:
        status = "saturated"

    ctr_trend = (creative.ctr_recent - creative.ctr_peak) / creative.ctr_peak if creative.ctr_peak > 0 else 0.0

    return SaturationMetricResponse(
        angle_id=creative.ad_name.lower().replace(" ", "_"),
        angle_name=creative.ad_name,
        saturation_score=creative.saturation_score / 100.0,
        status=status,
        ctr_trend=ctr_trend,
        frequency=creative.avg_frequency_recent,
        cpm_inflation=creative.cpm_inflation_score / 100.0,
        recommendation=_generate_recommendation(creative),
        analyzed_at=datetime.utcnow().isoformat(),
        # Detailed fields
        frequency_score=creative.frequency_score,
        ctr_decay_score=creative.ctr_decay_score,
        cpm_inflation_score=creative.cpm_inflation_score,
        ctr_recent=creative.ctr_recent,
        ctr_peak=creative.ctr_peak,
        cpm_recent=creative.cpm_recent,
        cpm_baseline=creative.cpm_baseline,
        total_spend=creative.total_spend,
        total_impressions=creative.total_impressions,
        days_active=creative.days_active,
        spend_share_pct=creative.spend_share_pct,
    )


@router.get("/analyze", response_model=List[SaturationMetricResponse])
def analyze_saturation(ad_account_id: str = None, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    """
    Analyze saturation levels using REAL SaturationEngine (CP4).

    NOTE: Currently requires CSV data. In production, this would:
    1. Query ad performance from database (populated by Meta API sync)
    2. Or accept uploaded CSV from Meta Ads Manager export

    For MVP: Returns demo data if no CSV available, but engine is production-ready.
    """
    trace_id = f"sat-{uuid4().hex[:12]}"
    set_trace_id(trace_id)

    try:
        # TODO: Load ad performance data from database when Meta API sync is implemented
        # For now: Check if demo CSV exists, use engine if available
        import os
        from pathlib import Path

        demo_csv_path = Path(__file__).parent.parent.parent.parent / "data" / "demo_ads_performance.csv"

        if demo_csv_path.exists():
            # Use REAL SaturationEngine
            engine = get_saturation_engine()
            df = engine.load_csv(str(demo_csv_path))
            report = engine.analyze(df)

            results = [_creative_to_response(c) for c in report.creatives]
            return results

        else:
            # Fallback: Return empty list with warning in logs
            from src.utils.logging_config import logger
            logger.warning(
                f"SATURATION_NO_DATA | ad_account_id={ad_account_id} | "
                "No CSV data available. Engine is ready but needs data source."
            )
            return []

    except Exception as e:
        raise HTTPException(500, f"Failed to analyze saturation: {str(e)}")


@router.get("/angle/{angle_id}", response_model=SaturationMetricResponse)
def get_angle_saturation(angle_id: str, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    """
    Get saturation metrics for a specific angle using REAL SaturationEngine.
    """
    trace_id = f"sat-{uuid4().hex[:12]}"
    set_trace_id(trace_id)

    try:
        # Get all saturation data
        all_metrics = analyze_saturation(db=db)

        # Find the specific angle
        for metric in all_metrics:
            if metric.angle_id == angle_id or metric.angle_name.lower().replace(" ", "_") == angle_id:
                return metric

        raise HTTPException(404, f"Angle '{angle_id}' not found in saturation analysis")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to get angle saturation: {str(e)}")


def _analyze_csv(csv_path: str) -> List[SaturationMetricResponse]:
    """Shared analysis logic for both demo and uploaded CSV files."""
    engine = get_saturation_engine()
    df = engine.load_csv(csv_path)
    report = engine.analyze(df)

    return [_creative_to_response(c) for c in report.creatives]


@router.post("/upload-csv", response_model=List[SaturationMetricResponse], dependencies=[Depends(require_operator_or_admin)])
async def upload_and_analyze(file: UploadFile = File(...)):
    """
    Upload a Meta Ads Manager CSV export and analyze saturation with REAL engine.
    Accepts CSV exports from Meta Ads Manager (Spanish or English column headers).
    No demo data — this analyzes YOUR real ad performance data.
    """
    trace_id = f"sat-upload-{uuid4().hex[:12]}"
    set_trace_id(trace_id)

    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "File must be a CSV file")

    try:
        # Save uploaded file to temp location
        content = await file.read()
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.csv', delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            results = _analyze_csv(tmp_path)
            from src.utils.logging_config import logger
            logger.info(f"SATURATION_CSV_UPLOADED | filename={file.filename} | creatives={len(results)}")
            return results
        finally:
            os.unlink(tmp_path)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to analyze uploaded CSV: {str(e)}")


# ── Deep Analysis Report (LLM + PDF) ──────────────────────────────────────────

class ReportRequest(BaseModel):
    angle_id: str
    angle_name: str
    saturation_score: float
    status: str
    ctr_trend: float
    frequency: float
    cpm_inflation: float
    recommendation: str
    frequency_score: float = 0.0
    ctr_decay_score: float = 0.0
    cpm_inflation_score: float = 0.0
    ctr_recent: float = 0.0
    ctr_peak: float = 0.0
    cpm_recent: float = 0.0
    cpm_baseline: float = 0.0
    total_spend: float = 0.0
    total_impressions: int = 0
    days_active: int = 0
    spend_share_pct: float = 0.0


REPORT_SYSTEM_PROMPT = """You are a senior performance marketing analyst writing a detailed saturation analysis report.
Your reports are data-driven, specific, and actionable. Write in professional Spanish.

Rules:
- Reference the EXACT numbers provided — never invent data.
- Compare metrics against standard industry benchmarks for paid social (Meta Ads).
- Be specific: instead of "CTR is low" say "CTR at 1.04% is below the Meta Ads benchmark of 1.5-2.0% for this vertical."
- Provide 4-6 concrete, prioritized action items with expected impact.
- Structure the report with clear sections using markdown headers.
- Do NOT use emojis or special Unicode symbols. Use plain text only.
"""

REPORT_USER_TEMPLATE = """Generate a comprehensive saturation analysis report for this ad creative:

CREATIVE: {angle_name}
STATUS: {status}

METRICS:
- Saturation Score: {saturation_score}/100
- CTR Current: {ctr_recent}%
- CTR Peak: {ctr_peak}%
- CTR Trend (decline from peak): {ctr_trend_pct}%
- CPM Current: ${cpm_recent}
- CPM Baseline: ${cpm_baseline}
- Frequency: {frequency}x
- Total Spend: ${total_spend}
- Total Impressions: {total_impressions}
- Days Active: {days_active}
- Spend Share: {spend_share_pct}%

SCORE BREAKDOWN (weighted components):
- Frequency Score: {frequency_score}/100 (weight: 35%)
- CTR Decay Score: {ctr_decay_score}/100 (weight: 35%)
- CPM Inflation Score: {cpm_inflation_score}/100 (weight: 30%)

Write the report with these sections:
1. **Resumen Ejecutivo** — 2-3 sentence overview of the creative's health
2. **Análisis de Métricas** — Explain each metric, what it means, and compare vs benchmarks
3. **Diagnóstico** — Root cause analysis of why this creative is in its current state
4. **Proyección** — What will happen if no action is taken (based on trends)
5. **Plan de Acción** — 4-6 numbered, specific, actionable steps with expected impact
6. **Prioridad y Timeline** — Which actions to take first, with timeframes
"""


def _generate_llm_analysis(metrics: ReportRequest) -> str:
    """Call LLM to generate deep analysis from saturation metrics."""
    from backend.src.llm.router import get_llm_router
    from backend.src.llm.schema import LLMRequest

    ctr_trend_pct = abs(metrics.ctr_trend * 100)

    user_content = REPORT_USER_TEMPLATE.format(
        angle_name=metrics.angle_name,
        status=metrics.status.upper(),
        saturation_score=f"{metrics.saturation_score * 100:.0f}",
        ctr_recent=f"{metrics.ctr_recent:.2f}",
        ctr_peak=f"{metrics.ctr_peak:.2f}",
        ctr_trend_pct=f"{ctr_trend_pct:.1f}",
        cpm_recent=f"{metrics.cpm_recent:.2f}",
        cpm_baseline=f"{metrics.cpm_baseline:.2f}",
        frequency=f"{metrics.frequency:.2f}",
        total_spend=f"{metrics.total_spend:.2f}",
        total_impressions=f"{metrics.total_impressions:,}",
        days_active=metrics.days_active,
        spend_share_pct=f"{metrics.spend_share_pct:.1f}",
        frequency_score=f"{metrics.frequency_score:.0f}",
        ctr_decay_score=f"{metrics.ctr_decay_score:.0f}",
        cpm_inflation_score=f"{metrics.cpm_inflation_score:.0f}",
    )

    request = LLMRequest(
        task_type="saturation_report",
        system_prompt=REPORT_SYSTEM_PROMPT,
        user_content=user_content,
        max_tokens=2048,
    )
    response = get_llm_router().generate(request)
    # .content is parsed JSON (dict), .raw_text is the actual text string
    return response.raw_text or ""


def _build_pdf(metrics: ReportRequest, analysis_text: str) -> bytes:
    """Build a formatted PDF from metrics + LLM analysis text."""
    from fpdf import FPDF
    from backend.src.utils.pdf_fonts import setup_pdf_fonts

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)

    _font = setup_pdf_fonts(pdf)

    pdf.add_page()

    # Title
    pdf.set_font(_font, "B", 18)
    pdf.cell(0, 12, f"Saturation Report: {metrics.angle_name}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(_font, "", 10)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6, f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | Status: {metrics.status.upper()}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Metrics summary box
    pdf.set_draw_color(212, 175, 55)
    pdf.set_fill_color(252, 249, 240)
    pdf.rect(10, pdf.get_y(), 190, 42, style="DF")

    y_start = pdf.get_y() + 3
    pdf.set_text_color(60, 60, 60)
    pdf.set_font(_font, "B", 9)

    col_w = 63
    metrics_grid = [
        [
            f"Saturation: {metrics.saturation_score * 100:.0f}/100",
            f"CTR: {metrics.ctr_recent:.2f}% (peak {metrics.ctr_peak:.2f}%)",
            f"CPM: ${metrics.cpm_recent:.2f} (base ${metrics.cpm_baseline:.2f})",
        ],
        [
            f"Frequency: {metrics.frequency:.2f}x",
            f"Spend: ${metrics.total_spend:,.2f}",
            f"Impressions: {metrics.total_impressions:,}",
        ],
        [
            f"Days Active: {metrics.days_active}",
            f"Spend Share: {metrics.spend_share_pct:.1f}%",
            f"CTR Trend: {metrics.ctr_trend * 100:+.1f}%",
        ],
    ]

    for row_idx, row in enumerate(metrics_grid):
        pdf.set_xy(14, y_start + row_idx * 12)
        for col_idx, cell_text in enumerate(row):
            pdf.set_x(14 + col_idx * col_w)
            pdf.cell(col_w, 10, cell_text, new_x="RIGHT")

    pdf.set_y(y_start + 40)
    pdf.ln(4)

    # Score breakdown
    pdf.set_font(_font, "B", 11)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 8, "Score Breakdown", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(_font, "", 9)
    pdf.set_text_color(80, 80, 80)

    components = [
        ("Frequency (35%)", metrics.frequency_score),
        ("CTR Decay (35%)", metrics.ctr_decay_score),
        ("CPM Inflation (30%)", metrics.cpm_inflation_score),
    ]
    for label, score in components:
        pdf.cell(50, 6, label)
        # Draw bar
        bar_x = pdf.get_x()
        bar_y = pdf.get_y() + 1
        pdf.set_fill_color(230, 230, 220)
        pdf.rect(bar_x, bar_y, 100, 4, style="F")
        # Fill
        r, g, b = (139, 152, 87) if score < 30 else (196, 164, 52) if score < 60 else (186, 96, 68)
        pdf.set_fill_color(r, g, b)
        pdf.rect(bar_x, bar_y, max(1, score), 4, style="F")
        pdf.set_x(bar_x + 104)
        pdf.cell(20, 6, f"{score:.0f}", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)

    # LLM Analysis
    pdf.set_font(_font, "B", 13)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 10, "Deep Analysis", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # Parse markdown-like text into PDF
    for line in analysis_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            pdf.ln(3)
            continue

        if stripped.startswith("## ") or stripped.startswith("**") and stripped.endswith("**"):
            # Section header
            clean = stripped.replace("## ", "").replace("**", "").replace("#", "").strip()
            pdf.set_font(_font, "B", 11)
            pdf.set_text_color(60, 60, 60)
            pdf.ln(3)
            pdf.cell(0, 7, clean, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
        elif stripped.startswith("# "):
            clean = stripped.replace("# ", "").strip()
            pdf.set_font(_font, "B", 13)
            pdf.set_text_color(40, 40, 40)
            pdf.ln(3)
            pdf.cell(0, 8, clean, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif stripped.startswith(("- ", "* ", "  - ")):
            clean = stripped.lstrip("-* ").strip()
            # Handle bold within bullet
            if "**" in clean:
                parts = clean.split("**")
                pdf.set_x(18)
                pdf.set_font(_font, "", 9)
                pdf.set_text_color(80, 80, 80)
                pdf.cell(4, 5, chr(8226))  # bullet
                for i, part in enumerate(parts):
                    if i % 2 == 1:
                        pdf.set_font(_font, "B", 9)
                    else:
                        pdf.set_font(_font, "", 9)
                    pdf.write(5, part)
                pdf.ln(5)
            else:
                pdf.set_font(_font, "", 9)
                pdf.set_text_color(80, 80, 80)
                pdf.set_x(18)
                pdf.cell(4, 5, chr(8226))
                pdf.multi_cell(165, 5, clean, new_x="LMARGIN", new_y="NEXT")
        else:
            # Regular paragraph (handle inline bold)
            pdf.set_font(_font, "", 9)
            pdf.set_text_color(70, 70, 70)
            clean = stripped.replace("**", "")
            pdf.multi_cell(0, 5, clean, new_x="LMARGIN", new_y="NEXT")

    # Footer
    pdf.ln(10)
    pdf.set_font(_font, "I", 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 5, "Generated by Meta Ops Agent - Saturation Analysis Engine", new_x="LMARGIN", new_y="NEXT")

    return pdf.output()


@router.get("/analyze-meta", response_model=List[SaturationMetricResponse])
def analyze_saturation_from_meta(
    days: int = 30,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Analyze saturation using real Meta data from MetaInsightsDaily.
    Queries synced campaign insights, builds a DataFrame matching the engine schema,
    then passes it to SaturationEngine.analyze().
    Existing demo CSV and CSV upload flows are NOT affected.
    """
    trace_id = f"sat-meta-{uuid4().hex[:12]}"
    set_trace_id(trace_id)

    try:
        from uuid import UUID
        from datetime import timedelta
        import pandas as pd
        from backend.src.database.models import MetaInsightsDaily, MetaCampaign, InsightLevel
        from sqlalchemy import func

        org_id = user.get("org_id", "")
        if not org_id:
            raise HTTPException(400, "Missing org_id in token")

        org_uuid = UUID(org_id)
        since_dt = datetime.utcnow() - timedelta(days=days)

        # Query daily insights grouped by campaign
        rows = db.query(
            MetaInsightsDaily.entity_meta_id,
            MetaInsightsDaily.date_start,
            MetaInsightsDaily.spend,
            MetaInsightsDaily.impressions,
            MetaInsightsDaily.clicks,
            MetaInsightsDaily.ctr,
            MetaInsightsDaily.cpm,
            MetaInsightsDaily.frequency,
        ).filter(
            MetaInsightsDaily.org_id == org_uuid,
            MetaInsightsDaily.level == InsightLevel.CAMPAIGN,
            MetaInsightsDaily.date_start >= since_dt,
            MetaInsightsDaily.spend > 0,
        ).order_by(MetaInsightsDaily.date_start).all()

        if not rows:
            logger.warning("SATURATION_META_NO_DATA | org={} | days={}", org_id, days)
            return []

        # Build campaign name map
        campaign_ids = list({r.entity_meta_id for r in rows})
        campaigns = db.query(MetaCampaign).filter(
            MetaCampaign.org_id == org_uuid,
            MetaCampaign.meta_campaign_id.in_(campaign_ids),
        ).all()
        name_map = {c.meta_campaign_id: c.name or c.meta_campaign_id for c in campaigns}

        # Build DataFrame matching SaturationEngine schema
        records = []
        for r in rows:
            spend = float(r.spend or 0)
            impressions = int(r.impressions or 0)
            clicks = int(r.clicks or 0)
            ctr = float(r.ctr or 0)
            cpm = float(r.cpm or 0)
            freq = float(r.frequency or 0)
            ad_name = name_map.get(r.entity_meta_id, r.entity_meta_id)

            records.append({
                "ad_name": ad_name,
                "date": r.date_start.strftime("%Y-%m-%d") if hasattr(r.date_start, 'strftime') else str(r.date_start),
                "spend": spend,
                "impressions": impressions,
                "clicks": clicks,
                "ctr": ctr,
                "cpm": cpm,
                "frequency": freq,
            })

        df = pd.DataFrame(records)

        engine = get_saturation_engine()
        report = engine.analyze(df)

        results = [_creative_to_response(c) for c in report.creatives]
        logger.info("SATURATION_META_OK | org={} | days={} | creatives={}", org_id, days, len(results))
        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error("SATURATION_META_FAILED | error={}", str(e))
        raise HTTPException(500, f"Failed to analyze Meta data: {str(e)}")


@router.post("/report")
def generate_saturation_report(
    request: ReportRequest,
    user: dict = Depends(get_current_user),
):
    """
    Generate a detailed PDF saturation analysis report for a specific creative.
    Uses LLM to analyze metrics, compare vs benchmarks, and provide actionable recommendations.
    """
    trace_id = f"sat-report-{uuid4().hex[:12]}"
    set_trace_id(trace_id)

    logger.info(
        "SATURATION_REPORT_START | creative={} | status={} | score={}",
        request.angle_name, request.status, request.saturation_score,
    )

    try:
        analysis_text = _generate_llm_analysis(request)

        # Strip emojis/symbols that PDF fonts can't render
        import re
        analysis_text = re.sub(
            r'[\U00002600-\U000027BF\U0001F300-\U0001F9FF\U00002702-\U000027B0'
            r'\U0000FE00-\U0000FE0F\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF'
            r'\U00002B50\U000026A0-\U000026FF]',
            '', analysis_text
        )

        logger.info(
            "SATURATION_REPORT_LLM_DONE | creative={} | analysis_len={}",
            request.angle_name, len(analysis_text),
        )

        pdf_bytes = _build_pdf(request, analysis_text)

        safe_name = request.angle_name.replace(" ", "_").replace("/", "-")[:40]
        filename = f"saturation_report_{safe_name}_{datetime.utcnow().strftime('%Y%m%d')}.pdf"

        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except Exception as e:
        logger.error("SATURATION_REPORT_FAILED | creative={} | error={}", request.angle_name, str(e))
        raise HTTPException(500, f"Failed to generate report: {str(e)}")
