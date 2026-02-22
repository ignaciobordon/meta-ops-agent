"""
Opportunities API - Extracts from CP1 (BrandMap)
Reads results from completed async jobs (no LLM call on GET).
"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from datetime import datetime
import io

from backend.src.database.session import get_db
from backend.src.database.models import JobRun, JobRunStatus
from backend.src.middleware.auth import get_current_user
from src.utils.logging_config import logger, set_trace_id
from uuid import UUID, uuid4

router = APIRouter(tags=["opportunities"])


class AsyncJobResponse(BaseModel):
    job_id: str
    status: str


@router.post("/analyze", status_code=202, response_model=AsyncJobResponse)
def analyze_opportunities(
    brand_profile_id: str = None,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Enqueue a BrandMap analysis job. Returns 202 with job_id for polling.
    Optional brand_profile_id uses a stored BrandMapProfile instead of demo_brand.txt.
    """
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "Missing org_id in token")

    from backend.src.jobs.queue import enqueue

    payload = {}
    if brand_profile_id:
        payload["brand_profile_id"] = brand_profile_id

    job_id = enqueue(
        task_name="opportunities_analyze",
        payload=payload,
        org_id=org_id,
        db=db,
    )
    db.commit()
    return AsyncJobResponse(job_id=job_id, status="queued")


# Response Models
class OpportunityResponse(BaseModel):
    id: str
    gap_id: str
    title: str
    description: str
    strategy: str
    priority: str  # "high", "medium", "low"
    estimated_impact: float
    impact_reasoning: str = ""
    identified_at: str


def _get_latest_results(db: Session, org_id: str) -> list | None:
    """Read opportunities from the latest successful analysis job."""
    job_run = (
        db.query(JobRun)
        .filter(
            JobRun.job_type.in_(["opportunities_analyze", "unified_intelligence_analyze"]),
            JobRun.org_id == UUID(org_id),
            JobRun.status == JobRunStatus.SUCCEEDED,
        )
        .order_by(JobRun.finished_at.desc())
        .first()
    )
    if not job_run:
        return None
    payload = job_run.payload_json or {}
    return payload.get("result")


@router.get("/", response_model=List[OpportunityResponse])
def list_opportunities(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    List market opportunities from the latest completed BrandMap analysis.
    Reads stored results from a succeeded opportunities_analyze job — no LLM call.
    If no analysis has been run yet, returns an empty list.
    """
    trace_id = f"opp-{uuid4().hex[:12]}"
    set_trace_id(trace_id)

    try:
        org_id = user.get("org_id", "")
        if not org_id:
            raise HTTPException(400, "Missing org_id in token")

        results = _get_latest_results(db, org_id)

        if results is None:
            logger.info("OPPORTUNITIES_NO_RESULTS | org={} | Run POST /analyze first", org_id)
            return []

        opportunities = [OpportunityResponse(**item) for item in results]
        logger.info("OPPORTUNITIES_LOADED | org={} | count={} | source=job_result", org_id, len(opportunities))
        return opportunities

    except HTTPException:
        raise
    except Exception as e:
        logger.error("OPPORTUNITIES_ERROR | error={}", str(e))
        raise HTTPException(500, f"Failed to load opportunities: {str(e)}")


@router.post("/analyze-unified", status_code=202, response_model=AsyncJobResponse)
def analyze_unified(
    brand_profile_id: str = None,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Unified Intelligence Analysis: aggregates CI + BrandMap + Saturation + Brain data,
    sends to LLM, returns cross-referenced opportunities. More comprehensive than /analyze."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "Missing org_id in token")

    from backend.src.jobs.queue import enqueue

    payload = {"unified": True}
    if brand_profile_id:
        payload["brand_profile_id"] = brand_profile_id

    job_id = enqueue(
        task_name="unified_intelligence_analyze",
        payload=payload,
        org_id=org_id,
        db=db,
    )
    db.commit()
    return AsyncJobResponse(job_id=job_id, status="queued")


@router.get("/{opportunity_id}", response_model=OpportunityResponse)
def get_opportunity(
    opportunity_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get details for a specific opportunity from stored results."""
    trace_id = f"opp-{uuid4().hex[:12]}"
    set_trace_id(trace_id)

    try:
        org_id = user.get("org_id", "")
        if not org_id:
            raise HTTPException(400, "Missing org_id in token")

        results = _get_latest_results(db, org_id)
        if not results:
            raise HTTPException(404, "No analysis results available. Run POST /analyze first.")

        for item in results:
            if item.get("id") == opportunity_id or item.get("gap_id") == opportunity_id:
                return OpportunityResponse(**item)

        raise HTTPException(404, f"Opportunity '{opportunity_id}' not found")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to get opportunity: {str(e)}")


# ── Opportunities Export (PDF) ────────────────────────────────────────────────


def _build_opportunities_pdf(opportunities: list) -> bytes:
    """Build PDF brief for all opportunities."""
    from fpdf import FPDF
    from backend.src.utils.pdf_fonts import setup_pdf_fonts

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)

    _font = setup_pdf_fonts(pdf)

    pdf.add_page()

    # Title
    pdf.set_font(_font, "B", 18)
    pdf.cell(0, 12, "Market Opportunities Report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(_font, "", 10)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6, f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | {len(opportunities)} opportunities", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    priority_colors = {
        "high": (186, 96, 68),
        "medium": (196, 164, 52),
        "low": (139, 152, 87),
    }

    for i, opp in enumerate(opportunities):
        if pdf.get_y() > 240:
            pdf.add_page()

        # Priority badge
        priority = opp.get("priority", "medium")
        r, g, b = priority_colors.get(priority, (120, 120, 120))
        pdf.set_text_color(r, g, b)
        pdf.set_font(_font, "B", 8)
        pdf.cell(0, 5, f"{priority.upper()} PRIORITY | Est. Impact: {(opp.get('estimated_impact', 0) * 100):.0f}%", new_x="LMARGIN", new_y="NEXT")

        # Title
        pdf.set_font(_font, "B", 12)
        pdf.set_text_color(40, 40, 40)
        pdf.cell(0, 8, opp.get("title", "Untitled"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

        # Description
        pdf.set_font(_font, "", 9)
        pdf.set_text_color(70, 70, 70)
        pdf.multi_cell(0, 5, opp.get("description", ""), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        # Strategy
        strategy = opp.get("strategy", "")
        if strategy:
            pdf.set_font(_font, "B", 9)
            pdf.set_text_color(60, 60, 60)
            pdf.cell(0, 5, "Recommended Strategy:", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(_font, "", 9)
            pdf.set_text_color(80, 80, 80)
            pdf.multi_cell(0, 5, strategy, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

        # Impact reasoning
        impact = opp.get("impact_reasoning", "")
        if impact:
            pdf.set_font(_font, "B", 9)
            pdf.set_text_color(60, 60, 60)
            pdf.cell(0, 5, "Impact Analysis:", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(_font, "", 9)
            pdf.set_text_color(80, 80, 80)
            pdf.multi_cell(0, 5, impact, new_x="LMARGIN", new_y="NEXT")

        # Gap ID
        pdf.set_font(_font, "", 7)
        pdf.set_text_color(150, 150, 150)
        pdf.cell(0, 5, f"Gap ID: {opp.get('gap_id', '')}", new_x="LMARGIN", new_y="NEXT")

        # Separator
        pdf.ln(3)
        pdf.set_draw_color(220, 220, 210)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(5)

    # Footer
    pdf.ln(4)
    pdf.set_font(_font, "I", 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 5, "Generated by Meta Ops Agent - Opportunities Engine", new_x="LMARGIN", new_y="NEXT")

    return pdf.output()


@router.get("/export/pdf")
def export_opportunities_pdf(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Export opportunities as a PDF brief."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "Missing org_id in token")

    try:
        results = _get_latest_results(db, org_id)
        if not results:
            raise HTTPException(404, "No analysis results available. Run POST /analyze first.")

        pdf_bytes = _build_opportunities_pdf(results)

        filename = f"opportunities_report_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to generate opportunities PDF: {str(e)}")
