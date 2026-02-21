"""
Creatives API - Integrates CP2 (AngleTagger) and CP6 (CreativeFactory)
"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from datetime import datetime, timezone
from uuid import uuid4
import io

from backend.src.database.session import get_db
from backend.src.database.models import Creative, AdAccount, MetaConnection, MetaAdAccount
from backend.src.middleware.auth import get_current_user
from backend.src.services.usage_service import UsageService
from backend.src.utils.tenant import get_org_ad_account_ids
from src.utils.logging_config import set_trace_id, logger

router = APIRouter(tags=["creatives"])

# Lazy-load engines when needed (CP2/CP6 not yet implemented)
def get_tagger():
    try:
        from src.engines.tagger.tagger import Tagger
        return Tagger()
    except ImportError:
        raise HTTPException(status_code=501, detail="Tagger engine not yet implemented (CP2)")

def get_factory():
    try:
        from src.engines.factory.factory import Factory
        return Factory()
    except ImportError:
        raise HTTPException(status_code=501, detail="Factory engine not yet implemented (CP6)")

def get_scorer():
    try:
        from src.engines.scoring.scorer import Scorer
        return Scorer()
    except ImportError:
        raise HTTPException(status_code=501, detail="Scorer engine not yet implemented (CP4)")


def _get_org_ad_account(db: Session, org_id: str) -> str | None:
    """Get first ad account for org. Returns None if no account connected."""
    from uuid import UUID as _UUID

    first = db.query(AdAccount).join(MetaConnection).filter(
        MetaConnection.org_id == _UUID(org_id)
    ).first()
    return str(first.id) if first else None


# Request/Response Models
class TagAnglesRequest(BaseModel):
    ad_creative: Dict[str, Any]
    brand_map_id: str


class GenerateCreativeRequest(BaseModel):
    angle_id: str
    brand_map_id: str
    n_variants: int = 1
    ad_account_id: Optional[str] = None
    brand_profile_id: Optional[str] = None
    framework: Optional[str] = None
    hook_style: Optional[str] = None
    audience: Optional[str] = None
    objective: Optional[str] = None
    tone: Optional[str] = None
    format: Optional[str] = None


class AngleResponse(BaseModel):
    angle_id: str
    angle_name: str
    confidence: float
    reasoning: str


class DimensionScoreResponse(BaseModel):
    score: float
    reasoning: str = ""


class CreativeResponse(BaseModel):
    id: str
    angle_id: str
    angle_name: str
    script: str
    score: float
    overall_reasoning: str = ""
    dimensions: Optional[Dict[str, DimensionScoreResponse]] = None
    is_best: bool = False
    generated_at: str
    source: str = "manual"
    flywheel_metadata: Optional[Dict[str, Any]] = None


class AsyncJobResponse(BaseModel):
    job_id: str
    status: str = "queued"


# Endpoints

@router.post("/tag-angles", response_model=List[AngleResponse])
def tag_angles(request: TagAnglesRequest, db: Session = Depends(get_db)):
    """
    Tag an ad creative with relevant angles using CP2 AngleTagger.
    """
    trace_id = f"tag-{uuid4().hex[:12]}"
    set_trace_id(trace_id)

    try:
        # Load BrandMap using BrandMapBuilder from demo brand text
        # TODO: In production, load from database using brand_map_id
        from pathlib import Path
        from src.engines.brand_map.builder import BrandMapBuilder

        demo_brand_path = Path(__file__).parent.parent.parent.parent / "data" / "demo_brand.txt"

        if not demo_brand_path.exists():
            raise HTTPException(500, "Brand data not available")

        builder = BrandMapBuilder()
        brand_text = demo_brand_path.read_text(encoding='utf-8')
        brand_map = builder.build(brand_text)

        tagger = get_tagger()
        result = tagger.tag_creative(
            ad_creative=request.ad_creative,
            brand_map=brand_map
        )

        return [
            AngleResponse(
                angle_id=angle.angle_id,
                angle_name=angle.angle_name,
                confidence=angle.confidence,
                reasoning=angle.reasoning
            )
            for angle in result.angles[:5]  # Top 5 angles
        ]

    except Exception as e:
        raise HTTPException(500, f"Failed to tag angles: {str(e)}")


@router.post("/generate", status_code=202, response_model=AsyncJobResponse)
def generate_creatives(
    request: GenerateCreativeRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Enqueue creative generation as a background job.
    Returns 202 with job_id for polling via GET /api/ops/jobs/{job_id}.
    """
    org_id = user.get("org_id", "")
    usage_service = UsageService(db)
    usage_service.check_limit(org_id, "creative_generate")

    # Resolve ad_account_id — require a real connected account
    ad_account_id = request.ad_account_id
    if not ad_account_id:
        ad_account_id = _get_org_ad_account(db, org_id)
    if not ad_account_id:
        raise HTTPException(400, "No ad account connected. Connect your Meta account first.")

    from backend.src.jobs.queue import enqueue

    payload = {
            "angle_id": request.angle_id,
            "brand_map_id": request.brand_map_id,
            "n_variants": request.n_variants,
            "ad_account_id": str(ad_account_id),
            "framework": request.framework,
            "hook_style": request.hook_style,
            "audience": request.audience,
            "objective": request.objective,
            "tone": request.tone,
            "format": request.format,
        }
    if request.brand_profile_id:
        payload["brand_profile_id"] = request.brand_profile_id

    job_id = enqueue(
        task_name="creatives_generate",
        payload=payload,
        org_id=org_id,
        db=db,
    )
    usage_service.record_usage(org_id, "creative_generate")
    db.commit()

    return AsyncJobResponse(job_id=job_id, status="queued")


@router.get("/", response_model=List[CreativeResponse])
def list_creatives(
    limit: int = 20,
    source: Optional[str] = None,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    List recently generated/stored creatives from REAL database.
    Scoped to user's organization. Queries the Creative table — no hardcoded demo data.
    Optional source filter: 'manual', 'flywheel', or None for all.
    """
    try:
        org_id = user.get("org_id", "")
        org_accounts = get_org_ad_account_ids(org_id, db)

        # Also include MetaAdAccount IDs for backward compatibility
        # (flywheel-generated creatives may have been saved with MetaAdAccount.id)
        from uuid import UUID as _UUID
        meta_accounts = db.query(MetaAdAccount.id).filter(
            MetaAdAccount.org_id == _UUID(org_id)
        ).all()
        all_account_ids = list(set(org_accounts + [a.id for a in meta_accounts]))

        if not all_account_ids:
            return []

        query = db.query(Creative).filter(
            Creative.ad_account_id.in_(all_account_ids)
        )

        if source:
            query = query.filter(Creative.source == source)

        creatives = query.order_by(
            Creative.created_at.desc()
        ).limit(limit).all()

        results = []
        for c in creatives:
            # Extract angle info from tags JSON
            tags = c.tags or []
            angle_id = tags[0].get("l2", "unknown") if tags else "unknown"
            angle_name = angle_id.replace("_", " ").title()

            # Normalize score from 0-10 to 0-1
            raw_score = c.overall_score or 0.0
            normalized_score = raw_score / 10.0 if raw_score > 1.0 else raw_score

            # Extract dimension scores and reasoning from evaluation_score JSON
            eval_data = c.evaluation_score or {}
            dimensions = None
            overall_reasoning = ""
            dim_names = ["hook_strength", "brand_alignment", "clarity", "audience_fit", "cta_quality"]
            if eval_data and any(d in eval_data for d in dim_names):
                dimensions = {}
                for d in dim_names:
                    if d in eval_data:
                        dim = eval_data[d]
                        dimensions[d] = DimensionScoreResponse(
                            score=dim.get("score", 0.0),
                            reasoning=dim.get("reasoning", ""),
                        )
                overall_reasoning = eval_data.get("overall_reasoning", "")

            results.append(CreativeResponse(
                id=str(c.id),
                angle_id=angle_id,
                angle_name=c.name or angle_name,
                script=c.ad_copy or "",
                score=normalized_score,
                overall_reasoning=overall_reasoning,
                dimensions=dimensions,
                generated_at=c.created_at.isoformat() if c.created_at else datetime.now(timezone.utc).isoformat(),
                source=getattr(c, "source", None) or "manual",
                flywheel_metadata=getattr(c, "flywheel_metadata", None) or None,
            ))

        # Mark the best creative
        if results:
            best_idx = max(range(len(results)), key=lambda i: results[i].score)
            results[best_idx].is_best = True

        return results

    except Exception as e:
        raise HTTPException(500, f"Failed to list creatives: {str(e)}")


# ── Creatives Export (PDF) ────────────────────────────────────────────────────


def _build_creatives_pdf(creatives_data: list) -> bytes:
    """Build PDF with all generated creatives."""
    from fpdf import FPDF
    from backend.src.utils.pdf_fonts import setup_pdf_fonts

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)

    _font = setup_pdf_fonts(pdf)

    pdf.add_page()

    # Title
    pdf.set_font(_font, "B", 18)
    pdf.cell(0, 12, "Creatives Report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(_font, "", 10)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6, f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | {len(creatives_data)} creatives", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    for c in creatives_data:
        if pdf.get_y() > 220:
            pdf.add_page()

        score = c.get("score", 0)
        score_pct = score * 100 if score <= 1 else score

        # Header: angle + score
        pdf.set_font(_font, "B", 12)
        pdf.set_text_color(40, 40, 40)
        pdf.cell(140, 8, c.get("angle_name", "Unknown"))
        pdf.set_font(_font, "B", 11)
        r, g, b = (139, 152, 87) if score_pct >= 70 else (196, 164, 52) if score_pct >= 40 else (186, 96, 68)
        pdf.set_text_color(r, g, b)
        pdf.cell(0, 8, f"Score: {score_pct:.0f}/100", new_x="LMARGIN", new_y="NEXT")

        # Best badge
        if c.get("is_best"):
            pdf.set_font(_font, "B", 8)
            pdf.set_text_color(139, 152, 87)
            pdf.cell(0, 5, "* BEST PICK *", new_x="LMARGIN", new_y="NEXT")

        pdf.set_font(_font, "", 7)
        pdf.set_text_color(150, 150, 150)
        pdf.cell(0, 4, f"Angle: {c.get('angle_id', '')} | Generated: {c.get('generated_at', '')[:10]}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        # Script
        pdf.set_font(_font, "B", 9)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 5, "Script:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(_font, "", 9)
        pdf.set_text_color(70, 70, 70)
        script_text = c.get("script", "")[:500]
        pdf.multi_cell(0, 5, script_text, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        # Dimensions breakdown
        dims = c.get("dimensions")
        if dims:
            pdf.set_font(_font, "B", 9)
            pdf.set_text_color(60, 60, 60)
            pdf.cell(0, 5, "Score Breakdown:", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(_font, "", 8)
            pdf.set_text_color(80, 80, 80)
            for dname, dval in dims.items():
                dscore = dval.get("score", 0) if isinstance(dval, dict) else 0
                label = dname.replace("_", " ").title()
                pdf.cell(50, 5, f"  {label}: {dscore:.1f}/10")
            pdf.ln(6)

        # Overall reasoning
        reasoning = c.get("overall_reasoning", "")
        if reasoning:
            pdf.set_font(_font, "I", 8)
            pdf.set_text_color(100, 100, 100)
            pdf.multi_cell(0, 4, reasoning[:300], new_x="LMARGIN", new_y="NEXT")

        # Separator
        pdf.ln(3)
        pdf.set_draw_color(220, 220, 210)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(5)

    # Footer
    pdf.ln(4)
    pdf.set_font(_font, "I", 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 5, "Generated by Meta Ops Agent - Creative Engine", new_x="LMARGIN", new_y="NEXT")

    return pdf.output()


@router.get("/export/pdf")
def export_creatives_pdf(
    limit: int = 20,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Export all creatives as a PDF report."""
    try:
        # Reuse the same logic as list_creatives to get data
        org_id = user.get("org_id", "")
        org_accounts = get_org_ad_account_ids(org_id, db)

        # Also include MetaAdAccount IDs for backward compatibility
        from uuid import UUID as _UUID
        meta_accounts = db.query(MetaAdAccount.id).filter(
            MetaAdAccount.org_id == _UUID(org_id)
        ).all()
        all_account_ids = list(set(org_accounts + [a.id for a in meta_accounts]))

        if not all_account_ids:
            raise HTTPException(404, "No creatives found")

        creatives = db.query(Creative).filter(
            Creative.ad_account_id.in_(all_account_ids)
        ).order_by(Creative.created_at.desc()).limit(limit).all()

        if not creatives:
            raise HTTPException(404, "No creatives found")

        # Build data dicts
        results = []
        for c in creatives:
            tags = c.tags or []
            angle_id = tags[0].get("l2", "unknown") if tags else "unknown"
            angle_name = angle_id.replace("_", " ").title()
            raw_score = c.overall_score or 0.0
            normalized_score = raw_score / 10.0 if raw_score > 1.0 else raw_score

            eval_data = c.evaluation_score or {}
            dimensions = None
            overall_reasoning = ""
            dim_names = ["hook_strength", "brand_alignment", "clarity", "audience_fit", "cta_quality"]
            if eval_data and any(d in eval_data for d in dim_names):
                dimensions = {}
                for d in dim_names:
                    if d in eval_data:
                        dimensions[d] = eval_data[d]
                overall_reasoning = eval_data.get("overall_reasoning", "")

            results.append({
                "id": str(c.id),
                "angle_id": angle_id,
                "angle_name": c.name or angle_name,
                "script": c.ad_copy or "",
                "score": normalized_score,
                "overall_reasoning": overall_reasoning,
                "dimensions": dimensions,
                "is_best": False,
                "generated_at": c.created_at.isoformat() if c.created_at else "",
            })

        # Mark best
        if results:
            best_idx = max(range(len(results)), key=lambda i: results[i]["score"])
            results[best_idx]["is_best"] = True

        pdf_bytes = _build_creatives_pdf(results)

        filename = f"creatives_report_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to generate creatives PDF: {str(e)}")
