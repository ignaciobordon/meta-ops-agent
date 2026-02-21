"""Flywheel API — Create, monitor, and retry flywheel runs."""
import io
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from uuid import UUID

from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user
from backend.src.services.flywheel_service import FlywheelService
from backend.src.jobs.queue import enqueue
from src.utils.logging_config import logger

router = APIRouter(tags=["flywheel"])


# ── Request/Response Models ──────────────────────────────────────────────────


class CreateRunRequest(BaseModel):
    ad_account_id: Optional[str] = None
    trigger: str = "manual"
    brand_profile_id: Optional[str] = None
    goal: str = "awareness"
    language: str = "es-AR"
    n_variants: int = 3
    channels: Optional[List[Dict[str, str]]] = None


class AsyncRunResponse(BaseModel):
    run_id: str
    job_id: str
    status: str = "queued"


class RunSummaryResponse(BaseModel):
    id: str
    status: str
    trigger: str = "manual"
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    created_at: Optional[str] = None
    error_message: Optional[str] = None
    steps_total: int = 0
    steps_succeeded: int = 0


class StepResponse(BaseModel):
    id: str
    step_name: str
    step_order: int
    status: str
    job_run_id: Optional[str] = None
    artifacts_json: Dict[str, Any] = {}
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    job_status: Optional[str] = None
    job_error: Optional[str] = None


class RunDetailResponse(BaseModel):
    id: str
    org_id: str
    ad_account_id: Optional[str] = None
    status: str
    trigger: str = "manual"
    config_json: Dict[str, Any] = {}
    outputs_json: Dict[str, Any] = {}
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    steps: List[StepResponse] = []


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/run", status_code=202, response_model=AsyncRunResponse)
def create_run(
    request: CreateRunRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Create and enqueue a flywheel run."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization context")

    config = {
        "ad_account_id": request.ad_account_id,
        "trigger": request.trigger,
        "brand_profile_id": request.brand_profile_id,
        "goal": request.goal,
        "language": request.language,
        "n_variants": request.n_variants,
        "channels": request.channels,
    }

    svc = FlywheelService(db, org_id)
    run = svc.create_run(config)

    # Enqueue the flywheel execution as a background job
    job_id = enqueue(
        task_name="flywheel_run",
        payload={"flywheel_run_id": str(run.id)},
        org_id=org_id,
        db=db,
    )

    db.commit()

    logger.info(
        "FLYWHEEL_RUN_ENQUEUED | run={} | job={} | org={}",
        run.id, job_id, org_id,
    )

    return AsyncRunResponse(run_id=str(run.id), job_id=job_id, status="queued")


@router.get("/runs", response_model=List[RunSummaryResponse])
def list_runs(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List recent flywheel runs."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization context")

    svc = FlywheelService(db, org_id)
    runs = svc.list_runs(limit=limit)
    return [RunSummaryResponse(**r) for r in runs]


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get run detail with all steps."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization context")

    svc = FlywheelService(db, org_id)
    data = svc.get_run_with_steps(UUID(run_id))
    if not data:
        raise HTTPException(404, "Flywheel run not found")

    return RunDetailResponse(**data)


@router.post("/runs/{run_id}/cancel")
def cancel_run(
    run_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Cancel a running flywheel run."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization context")

    svc = FlywheelService(db, org_id)
    try:
        result = svc.cancel_run(UUID(run_id))
    except ValueError as e:
        raise HTTPException(400, str(e))

    return result


@router.post("/runs/{run_id}/retry/{step_id}")
def retry_step(
    run_id: str,
    step_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Retry a failed step in a flywheel run."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization context")

    svc = FlywheelService(db, org_id)
    try:
        result = svc.retry_step(UUID(run_id), UUID(step_id))
    except ValueError as e:
        raise HTTPException(404, str(e))

    return result


@router.get("/runs/{run_id}/summary")
def get_run_summary(
    run_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Generate an LLM-powered strategic summary of a flywheel run."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization context")

    svc = FlywheelService(db, org_id)
    data = svc.get_run_with_steps(UUID(run_id))
    if not data:
        raise HTTPException(404, "Flywheel run not found")

    # Check cache in outputs_json
    outputs = data.get("outputs_json", {})
    if outputs.get("strategic_summary"):
        return {"summary": outputs["strategic_summary"]}

    # Gather opportunities
    from backend.src.database.models import JobRun, JobRunStatus, Creative, MetaAdAccount
    opp_job = (
        db.query(JobRun)
        .filter(
            JobRun.org_id == UUID(org_id),
            JobRun.job_type.in_(["opportunities_analyze", "unified_intelligence_analyze"]),
            JobRun.status == JobRunStatus.SUCCEEDED,
        )
        .order_by(JobRun.finished_at.desc())
        .first()
    )
    opportunities = []
    if opp_job and opp_job.payload_json:
        opportunities = opp_job.payload_json.get("result", []) or []

    # Gather creatives count + top scored
    ad_account = (
        db.query(MetaAdAccount)
        .filter(MetaAdAccount.org_id == UUID(org_id))
        .first()
    )
    creatives_summary = ""
    if ad_account:
        creatives = (
            db.query(Creative)
            .filter(Creative.ad_account_id == ad_account.id)
            .order_by(Creative.overall_score.desc().nulls_last())
            .limit(5)
            .all()
        )
        if creatives:
            lines = [f"- {c.name or 'Unnamed'} (score: {c.overall_score or 'N/A'}/10)" for c in creatives]
            creatives_summary = f"Top creatives:\n" + "\n".join(lines)

    # Build context for LLM
    steps_text = ""
    for s in data.get("steps", []):
        arts = s.get("artifacts_json", {})
        arts_brief = ", ".join(f"{k}={v}" for k, v in arts.items() if k not in ("summary", "top_opportunity")) if arts else "none"
        steps_text += f"  - {s['step_name']}: {s['status']} | artifacts: {arts_brief}\n"

    opps_text = ""
    for i, opp in enumerate(opportunities[:8], 1):
        title = opp.get("title") or opp.get("gap_id", f"Opportunity {i}")
        priority = opp.get("priority", "")
        desc = (opp.get("description") or opp.get("strategy") or "")[:200]
        opps_text += f"  {i}. [{priority}] {title}: {desc}\n"

    if not opps_text:
        opps_text = "  No opportunities data available yet.\n"

    context = f"""Flywheel run status: {data['status']}
Steps:
{steps_text}
Opportunities found ({len(opportunities)}):
{opps_text}
{creatives_summary}
"""

    # Check conversion model for offline sales context
    from backend.src.database.models import Organization
    org_obj = db.query(Organization).filter(Organization.id == UUID(org_id)).first()
    conversion_model = (org_obj.settings or {}).get("conversion_model", "online") if org_obj else "online"

    offline_note = ""
    if conversion_model == "offline":
        offline_note = (
            " IMPORTANT: This business closes sales offline (outside Meta). "
            "Do NOT flag zero conversions or low ROAS as problems — these metrics are NOT meaningful. "
            "Focus on top-of-funnel metrics: CTR, CPM, frequency, reach, engagement."
        )

    # Call LLM
    try:
        from backend.src.llm.router import LLMRouter
        from backend.src.llm.schema import LLMRequest

        request = LLMRequest(
            task_type="flywheel_summary",
            system_prompt=(
                "You are a senior digital marketing strategist analyzing the results of an "
                "automated optimization cycle (Flywheel) for a Meta Ads account. "
                "Based on the data below, write a concise strategic summary (3-5 sentences) "
                "explaining: (1) what the flywheel found, (2) the most important opportunity "
                "or insight, and (3) the recommended next action the team should take. "
                "Be specific, actionable, and direct. Write in a professional tone. "
                "Do NOT use markdown, bullet points, or headers — just plain text paragraphs."
                + offline_note
            ),
            user_content=context,
            max_tokens=500,
            temperature=0.4,
        )

        router = LLMRouter()
        response = router.generate(request)
        summary_text = (response.raw_text or "").strip()

        if not summary_text:
            summary_text = "Flywheel cycle completed. Review the opportunities and creatives for next steps."

    except Exception as exc:
        logger.error("FLYWHEEL_SUMMARY_LLM_ERROR | run={} | error={}", run_id, str(exc)[:200])
        # Fallback: generate a simple summary without LLM
        opp_count = len(opportunities)
        top_opp = opportunities[0] if opportunities else None
        top_title = (top_opp.get("title") or top_opp.get("gap_id", "")) if top_opp else ""
        summary_text = (
            f"The flywheel cycle completed successfully with all {len(data.get('steps', []))} steps. "
            f"{opp_count} market opportunities were identified. "
        )
        if top_title:
            summary_text += f"The highest priority opportunity is \"{top_title}\". "
        summary_text += "Review the Opportunities page for detailed strategies and generate creatives for the top gaps."

    # Cache in outputs_json
    from backend.src.database.models import FlywheelRun
    from sqlalchemy.orm.attributes import flag_modified
    run_obj = db.query(FlywheelRun).filter(FlywheelRun.id == UUID(run_id)).first()
    if run_obj:
        updated = dict(run_obj.outputs_json or {})
        updated["strategic_summary"] = summary_text
        run_obj.outputs_json = updated
        flag_modified(run_obj, "outputs_json")
        db.commit()

    return {"summary": summary_text}


@router.get("/runs/{run_id}/export")
def export_run_pdf(
    run_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Export flywheel run results as a PDF."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization context")

    svc = FlywheelService(db, org_id)
    data = svc.get_run_with_steps(UUID(run_id))
    if not data:
        raise HTTPException(404, "Flywheel run not found")

    # Gather opportunities from the latest succeeded job
    from backend.src.database.models import JobRun, JobRunStatus
    opp_job = (
        db.query(JobRun)
        .filter(
            JobRun.org_id == UUID(org_id),
            JobRun.job_type.in_(["opportunities_analyze", "unified_intelligence_analyze"]),
            JobRun.status == JobRunStatus.SUCCEEDED,
        )
        .order_by(JobRun.finished_at.desc())
        .first()
    )
    opportunities = []
    if opp_job and opp_job.payload_json:
        opportunities = opp_job.payload_json.get("result", []) or []

    # Gather creatives
    from backend.src.database.models import Creative, MetaAdAccount
    ad_account = (
        db.query(MetaAdAccount)
        .filter(MetaAdAccount.org_id == UUID(org_id))
        .first()
    )
    creatives = []
    if ad_account:
        creatives = (
            db.query(Creative)
            .filter(Creative.ad_account_id == ad_account.id)
            .order_by(Creative.created_at.desc())
            .limit(20)
            .all()
        )

    # Gather content packs
    from backend.src.database.models import ContentPack, ContentVariant
    packs = (
        db.query(ContentPack)
        .filter(ContentPack.org_id == UUID(org_id))
        .order_by(ContentPack.created_at.desc())
        .limit(10)
        .all()
    )

    # Build PDF
    try:
        pdf_bytes = _build_flywheel_pdf(data, opportunities, creatives, packs, db)
    except Exception as exc:
        logger.error("FLYWHEEL_PDF_ERROR | run={} | error={}", run_id, str(exc)[:300])
        raise HTTPException(500, f"Failed to generate PDF: {str(exc)[:200]}")

    run_short = run_id[:8]
    filename = f"flywheel-report-{run_short}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── PDF Generation ────────────────────────────────────────────────────────────


def _safe(text: str, max_len: int = 500) -> str:
    """Sanitize text for PDF: replace unsupported chars, truncate."""
    if not text:
        return ""
    # Replace common unicode chars that latin-1 can't handle
    replacements = {
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u2013": "-", "\u2014": "--", "\u2026": "...", "\u2022": "*",
        "\u00a0": " ", "\u200b": "", "\u2003": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # Encode to latin-1, replacing anything else
    text = text.encode("latin-1", errors="replace").decode("latin-1")
    if len(text) > max_len:
        text = text[:max_len] + "..."
    return text


def _build_flywheel_pdf(
    run_data: dict,
    opportunities: list,
    creatives: list,
    packs: list,
    db: Session,
) -> bytes:
    """Generate a PDF report for a flywheel run."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # ── Title ──
    pdf.set_font("Helvetica", "B", 22)
    pdf.cell(0, 12, "Flywheel Report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    run_id_short = run_data["id"][:8]
    started = run_data.get("started_at", "N/A") or "N/A"
    finished = run_data.get("finished_at", "N/A") or "N/A"
    pdf.cell(0, 6, f"Run: {run_id_short}   |   Status: {run_data['status']}   |   Trigger: {run_data.get('trigger', 'manual')}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Started: {started}   |   Finished: {finished}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(6)

    # ── Steps Summary ──
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Pipeline Steps", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    step_labels = {
        "meta_sync": "Meta Sync",
        "brain_analysis": "Brain Analysis",
        "saturation_check": "Saturation Check",
        "unified_intelligence": "Unified Intelligence",
        "opportunities": "Opportunities",
        "creatives": "Creatives",
        "content_studio": "Content Studio",
        "export": "Export",
    }

    step_descriptions = {
        "meta_sync": "Synchronizes campaigns, adsets, ads, and daily performance insights from Meta Ads API.",
        "brain_analysis": "Analyzes trust scores, winning creative features, and entity performance patterns.",
        "saturation_check": "Detects ad fatigue by analyzing frequency, CTR decay, and CPM inflation trends.",
        "unified_intelligence": "Runs LLM-powered market gap analysis combining brand, competitive, and performance data.",
        "opportunities": "Compiles actionable opportunities ranked by priority and estimated impact.",
        "creatives": "Generates new ad scripts using Factory engine with full flywheel intelligence context.",
        "content_studio": "Transforms the best-scored creative into multi-channel content variants.",
        "export": "Summarizes all step outputs into the final flywheel report.",
    }

    for step in run_data.get("steps", []):
        if pdf.get_y() > 240:
            pdf.add_page()

        name = step_labels.get(step["step_name"], step["step_name"])
        status = step["status"]
        icon = {"succeeded": "[OK]", "failed": "[FAIL]", "skipped": "[SKIP]", "running": "[...]"}.get(status, "[--]")

        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(18, 7, icon)
        pdf.cell(55, 7, _safe(name, 50))
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 7, _safe(status), new_x="LMARGIN", new_y="NEXT")

        # Step description
        desc = step_descriptions.get(step["step_name"], "")
        if desc:
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(18, 4, "")
            pdf.cell(0, 4, _safe(desc, 200), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)

        # Show detailed artifacts based on step type
        artifacts = step.get("artifacts_json", {})
        step_name = step["step_name"]

        if artifacts and step_name == "brain_analysis":
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(60, 60, 60)
            pdf.cell(18, 5, "")
            pdf.cell(0, 5, _safe(f"Entities tracked: {artifacts.get('entity_memory_count', 0)} | Features: {artifacts.get('feature_memory_count', 0)} | Avg trust: {artifacts.get('avg_trust_score', 0)}", 200), new_x="LMARGIN", new_y="NEXT")
            for ent in artifacts.get("top_entities", [])[:3]:
                pdf.cell(18, 5, "")
                pdf.cell(0, 5, _safe(f"  Top entity: {ent.get('entity_id', '')} ({ent.get('type', '')}) - trust: {ent.get('trust_score', 0)}", 200), new_x="LMARGIN", new_y="NEXT")
            for feat in artifacts.get("winning_features", [])[:3]:
                pdf.cell(18, 5, "")
                pdf.cell(0, 5, _safe(f"  Winning: {feat.get('key', '')} (win rate: {feat.get('win_rate', 0)}, samples: {feat.get('samples', 0)})", 200), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)

        elif artifacts and step_name == "saturation_check":
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(60, 60, 60)
            pdf.cell(18, 5, "")
            spend_14d = float(artifacts.get('total_spend_14d', 0) or 0)
            pdf.cell(0, 5, _safe(f"Ads analyzed: {artifacts.get('ads_analyzed', 0)} | Saturated: {artifacts.get('saturated_count', 0)} | Fresh: {artifacts.get('fresh_count', 0)} | Avg freq: {artifacts.get('avg_frequency', 0)} | 14d spend: ${spend_14d:,.0f}", 300), new_x="LMARGIN", new_y="NEXT")
            for sat in artifacts.get("saturated_ads", [])[:3]:
                pdf.cell(18, 5, "")
                pdf.set_text_color(180, 80, 60)
                pdf.cell(0, 5, _safe(f"  Fatigued: {sat.get('name', '')} (freq: {sat.get('frequency', 0)}, CTR drop: {sat.get('ctr_decline', 0)})", 200), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)

        elif artifacts and step_name == "opportunities":
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(60, 60, 60)
            pb = artifacts.get("priority_breakdown", {})
            pdf.cell(18, 5, "")
            pdf.cell(0, 5, _safe(f"Total: {artifacts.get('opportunities_count', 0)} | High: {pb.get('high', 0)} | Medium: {pb.get('medium', 0)} | Low: {pb.get('low', 0)} | Impact: {artifacts.get('total_estimated_impact', 0):.2f}", 300), new_x="LMARGIN", new_y="NEXT")
            for opp_s in artifacts.get("opportunities", [])[:3]:
                pdf.cell(18, 5, "")
                pdf.cell(0, 5, _safe(f"  [{opp_s.get('priority', '').upper()}] {opp_s.get('title', '')} (impact: {opp_s.get('estimated_impact', 0)})", 200), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)

        elif artifacts and step_name == "creatives":
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(60, 60, 60)
            pdf.cell(18, 5, "")
            pdf.cell(0, 5, _safe(f"Angle: {artifacts.get('angle_id', '')} | Opportunities used: {artifacts.get('opportunities_used', 0)} | Brain features: {artifacts.get('brain_features_used', 0)} | Saturated avoided: {artifacts.get('saturated_ads_avoided', 0)}", 300), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)

        elif artifacts and step_name == "content_studio":
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(60, 60, 60)
            pdf.cell(18, 5, "")
            note = artifacts.get("note", "")
            pack_id = artifacts.get("content_pack_id", "N/A")
            creative_id = artifacts.get("creative_id", "N/A")
            pdf.cell(0, 5, _safe(f"Pack: {pack_id[:8]}... | Creative: {creative_id[:8]}... {('| ' + note) if note else ''}", 200), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)

        elif artifacts:
            # Generic artifact display for other steps
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(80, 80, 80)
            for key, val in artifacts.items():
                if key in ("summary", "top_opportunity"):
                    continue
                pdf.cell(18, 5, "")
                pdf.cell(0, 5, _safe(f"{key}: {val}", 120), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)

        if step.get("error_message"):
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(180, 0, 0)
            pdf.cell(18, 5, "")
            pdf.cell(0, 5, _safe(f"Error: {step['error_message']}", 200), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)

        pdf.ln(2)

    pdf.ln(4)

    # ── Opportunities & Actionables ──
    if opportunities:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, f"Opportunities & Actionables ({len(opportunities)})", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        for i, opp in enumerate(opportunities[:15], 1):
            if pdf.get_y() > 240:
                pdf.add_page()

            title = opp.get("title") or opp.get("gap_title") or opp.get("gap_id", f"Opportunity {i}")
            priority = opp.get("priority") or opp.get("impact", "")
            category = opp.get("category") or opp.get("gap_type", "")
            impact = opp.get("estimated_impact", 0)
            impact_reasoning = opp.get("impact_reasoning", "")

            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 7, _safe(f"{i}. {title}", 120), new_x="LMARGIN", new_y="NEXT")

            pdf.set_font("Helvetica", "", 9)
            meta_line = []
            if priority:
                meta_line.append(f"Priority: {priority}")
            if category:
                meta_line.append(f"Category: {category}")
            if impact:
                try:
                    impact_f = float(impact)
                    meta_line.append(f"Impact: {impact_f:.0%}" if impact_f <= 1 else f"Impact: {impact_f}")
                except (ValueError, TypeError):
                    meta_line.append(f"Impact: {impact}")
            if meta_line:
                pdf.set_text_color(60, 60, 60)
                pdf.cell(0, 5, _safe(" | ".join(meta_line), 150), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)

            # Strategy/description
            strategy = opp.get("strategy") or opp.get("description") or opp.get("insight", "")
            if strategy:
                pdf.set_font("Helvetica", "", 9)
                pdf.multi_cell(0, 5, _safe(strategy, 500), new_x="LMARGIN", new_y="NEXT")

            # Impact reasoning
            if impact_reasoning:
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_text_color(80, 80, 120)
                pdf.multi_cell(0, 4, _safe(f"Impact reasoning: {impact_reasoning}", 300), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)

            # Actionable items
            actions = opp.get("actions") or opp.get("actionable_items") or opp.get("recommendations", [])
            if isinstance(actions, list) and actions:
                pdf.set_font("Helvetica", "I", 9)
                pdf.set_text_color(0, 80, 0)
                for action in actions[:5]:
                    if isinstance(action, dict):
                        action_text = action.get("action") or action.get("text") or str(action)
                    else:
                        action_text = str(action)
                    pdf.cell(0, 5, _safe(f"  -> {action_text}", 200), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
            elif isinstance(actions, str) and actions:
                pdf.set_font("Helvetica", "I", 9)
                pdf.set_text_color(0, 80, 0)
                pdf.cell(0, 5, _safe(f"  -> {actions}", 200), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)

            pdf.ln(3)

    # ── Creatives ──
    if creatives:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, f"Creatives ({len(creatives)})", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        # Sort by score for the report
        sorted_creatives = sorted(creatives, key=lambda c: c.overall_score or 0, reverse=True)

        for i, cr in enumerate(sorted_creatives[:10], 1):
            if pdf.get_y() > 230:
                pdf.add_page()

            pdf.set_font("Helvetica", "B", 11)
            name = cr.name or f"Creative {i}"
            source_label = f" [FLYWHEEL]" if getattr(cr, "source", None) == "flywheel" else ""
            best_label = " ** BEST **" if i == 1 else ""
            pdf.cell(0, 7, _safe(f"{i}. {name}{source_label}{best_label}", 120), new_x="LMARGIN", new_y="NEXT")

            # Score with color
            if cr.overall_score:
                score_val = cr.overall_score
                pdf.set_font("Helvetica", "B", 10)
                r, g, b = (139, 152, 87) if score_val >= 7 else (196, 164, 52) if score_val >= 4 else (186, 96, 68)
                pdf.set_text_color(r, g, b)
                pdf.cell(0, 5, _safe(f"Score: {score_val:.1f}/10"), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)

            pdf.set_font("Helvetica", "", 9)
            if cr.headline:
                pdf.cell(0, 5, _safe(f"Headline: {cr.headline}", 150), new_x="LMARGIN", new_y="NEXT")

            # Full ad copy with script sections
            if cr.ad_copy:
                pdf.set_font("Helvetica", "", 9)
                pdf.set_text_color(50, 50, 50)
                pdf.multi_cell(0, 5, _safe(cr.ad_copy, 500), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)

            # Dimension breakdown
            eval_data = cr.evaluation_score or {}
            dim_names = ["hook_strength", "brand_alignment", "clarity", "audience_fit", "cta_quality"]
            if eval_data and any(d in eval_data for d in dim_names):
                pdf.set_font("Helvetica", "", 8)
                pdf.set_text_color(80, 80, 80)
                dim_parts = []
                for d in dim_names:
                    if d in eval_data:
                        val = eval_data[d]
                        s = val.get("score", 0) if isinstance(val, dict) else 0
                        dim_parts.append(f"{d.replace('_', ' ').title()}: {s:.1f}")
                if dim_parts:
                    pdf.cell(0, 4, _safe(" | ".join(dim_parts), 300), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)

            # Flywheel metadata
            fw_meta = getattr(cr, "flywheel_metadata", None) or {}
            if fw_meta:
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_text_color(100, 80, 140)
                meta_parts = []
                if fw_meta.get("opportunities_used"):
                    meta_parts.append(f"Opps used: {fw_meta['opportunities_used']}")
                if fw_meta.get("winning_features_used"):
                    meta_parts.append(f"Features: {fw_meta['winning_features_used']}")
                if fw_meta.get("saturated_ads_avoided"):
                    meta_parts.append(f"Saturated avoided: {fw_meta['saturated_ads_avoided']}")
                if meta_parts:
                    pdf.cell(0, 4, _safe("Flywheel: " + " | ".join(meta_parts), 200), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)

            # Performance metrics (safe int/float casts for ALTER TABLE columns)
            metrics = []
            impressions = getattr(cr, "impressions", None)
            clicks = getattr(cr, "clicks", None)
            spend = getattr(cr, "spend", None)
            if impressions:
                metrics.append(f"Impressions: {int(impressions):,}")
            if clicks:
                metrics.append(f"Clicks: {int(clicks):,}")
            if spend:
                metrics.append(f"Spend: ${float(spend):,.2f}")
            if metrics:
                pdf.set_font("Helvetica", "", 8)
                pdf.cell(0, 5, _safe(" | ".join(metrics), 200), new_x="LMARGIN", new_y="NEXT")

            pdf.ln(4)

    # ── Content Packs ──
    if packs:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, f"Content Packs ({len(packs)})", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        from backend.src.database.models import ContentVariant

        for i, pack in enumerate(packs[:5], 1):
            if pdf.get_y() > 250:
                pdf.add_page()

            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 7, _safe(f"Pack {i} - {pack.goal or 'general'} ({pack.language or 'es-AR'})", 100), new_x="LMARGIN", new_y="NEXT")

            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(80, 80, 80)
            pdf.cell(0, 5, _safe(f"Status: {pack.status.value if hasattr(pack.status, 'value') else pack.status}", 60), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)

            variants = (
                db.query(ContentVariant)
                .filter(ContentVariant.content_pack_id == pack.id)
                .order_by(ContentVariant.variant_index)
                .all()
            )

            for v in variants[:6]:
                if pdf.get_y() > 270:
                    pdf.add_page()
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(0, 5, _safe(f"  Variant {v.variant_index} - {v.channel} ({v.format or 'default'})", 100), new_x="LMARGIN", new_y="NEXT")

                output = v.output_json or {}
                pdf.set_font("Helvetica", "", 8)
                # Show key output fields
                for field in ("hook", "headline", "caption", "script", "cta", "visual_direction"):
                    val = output.get(field)
                    if val:
                        label = field.replace("_", " ").title()
                        pdf.multi_cell(0, 4, _safe(f"    {label}: {val}", 300), new_x="LMARGIN", new_y="NEXT")

                if v.score:
                    pdf.cell(0, 4, _safe(f"    Score: {v.score}/100"), new_x="LMARGIN", new_y="NEXT")
                pdf.ln(2)

            pdf.ln(3)

    # ── Footer ──
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    pdf.cell(0, 10, f"Generated by Meta Ops Agent on {now}", new_x="LMARGIN", new_y="NEXT")

    return pdf.output()
