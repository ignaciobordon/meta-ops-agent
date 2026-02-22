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

    config = {k: v for k, v in {
        "ad_account_id": request.ad_account_id,
        "trigger": request.trigger,
        "brand_profile_id": request.brand_profile_id,
        "goal": request.goal,
        "language": request.language,
        "n_variants": request.n_variants,
        "channels": request.channels,
    }.items() if v is not None}

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

        # Channel-aware field display mapping
        CHANNEL_DISPLAY_FIELDS = {
            "ig_reel": ["hook", "script", "cta", "music_suggestion"],
            "ig_post": ["caption", "cta", "visual_description"],
            "ig_carousel": ["caption", "cta"],
            "ig_story": ["cta"],
            "tiktok_short": ["hook", "script", "cta", "sound_suggestion"],
            "yt_short": ["hook", "script", "cta", "title"],
            "yt_long": ["title", "hook", "cta"],
            "fb_feed": ["copy", "headline", "cta", "visual_description"],
            "fb_ad_copy": ["primary_text", "headline", "cta_button", "description"],
            "x_post": ["text", "cta"],
            "x_thread": ["hook_tweet", "cta_tweet"],
            "linkedin_post": ["text", "hook", "cta"],
            "email_newsletter": ["subject_line", "preview_text", "cta_text"],
        }
        # Fields that contain arrays needing special rendering
        ARRAY_FIELDS = {"slides", "frames", "shot_list", "hashtags", "tweets"}

        for i, pack in enumerate(packs[:5], 1):
            if pdf.get_y() > 250:
                pdf.add_page()

            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 7, _safe(f"Pack {i} - {pack.goal or 'general'} ({pack.language or 'es-AR'})", 100), new_x="LMARGIN", new_y="NEXT")

            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(80, 80, 80)
            status_str = pack.status.value if hasattr(pack.status, 'value') else pack.status
            channels_list = pack.channels_json or []
            channel_names = ", ".join(ch.get("channel", "?") for ch in channels_list) if channels_list else "N/A"
            pdf.cell(0, 5, _safe(f"Status: {status_str} | Channels: {channel_names}", 200), new_x="LMARGIN", new_y="NEXT")

            # Show opportunity context if available
            pack_input = pack.input_json or {}
            opp_info = pack_input.get("opportunity", {})
            if opp_info and opp_info.get("title"):
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_text_color(80, 80, 120)
                pdf.cell(0, 5, _safe(f"Strategy: {opp_info.get('title', '')} - {opp_info.get('strategy', '')}", 250), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)

            variants = (
                db.query(ContentVariant)
                .filter(ContentVariant.content_pack_id == pack.id)
                .order_by(ContentVariant.channel, ContentVariant.variant_index)
                .all()
            )

            if not variants:
                pdf.set_font("Helvetica", "I", 9)
                pdf.set_text_color(150, 80, 80)
                pdf.cell(0, 5, "  No variants generated", new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
                pdf.ln(3)
                continue

            current_channel = None
            for v in variants[:18]:
                if pdf.get_y() > 255:
                    pdf.add_page()

                # Channel subheader
                if v.channel != current_channel:
                    current_channel = v.channel
                    pdf.set_font("Helvetica", "B", 10)
                    pdf.set_text_color(30, 80, 130)
                    pdf.cell(0, 6, _safe(f"  {v.channel.replace('_', ' ').upper()} ({v.format or 'default'})", 100), new_x="LMARGIN", new_y="NEXT")
                    pdf.set_text_color(0, 0, 0)

                pdf.set_font("Helvetica", "B", 9)
                score_str = f" | Score: {v.score:.0f}/100" if v.score else ""
                pdf.cell(0, 5, _safe(f"    Variant {v.variant_index}{score_str}", 100), new_x="LMARGIN", new_y="NEXT")

                output = v.output_json or {}
                pdf.set_font("Helvetica", "", 8)

                # Use channel-aware fields, falling back to all fields
                display_fields = CHANNEL_DISPLAY_FIELDS.get(v.channel, [])
                rendered_keys = set()

                # Render priority fields first
                for field in display_fields:
                    val = output.get(field)
                    if val:
                        rendered_keys.add(field)
                        label = field.replace("_", " ").title()
                        pdf.set_font("Helvetica", "B", 8)
                        pdf.cell(0, 4, _safe(f"      {label}:", 80), new_x="LMARGIN", new_y="NEXT")
                        pdf.set_font("Helvetica", "", 8)
                        pdf.multi_cell(0, 4, _safe(f"      {val}", 400), new_x="LMARGIN", new_y="NEXT")

                # Render array fields (slides, frames, shot_list, hashtags)
                for arr_field in ARRAY_FIELDS:
                    arr_val = output.get(arr_field)
                    if arr_val and isinstance(arr_val, list):
                        rendered_keys.add(arr_field)
                        label = arr_field.replace("_", " ").title()
                        pdf.set_font("Helvetica", "B", 8)
                        pdf.cell(0, 4, _safe(f"      {label} ({len(arr_val)} items):", 100), new_x="LMARGIN", new_y="NEXT")
                        pdf.set_font("Helvetica", "", 7)
                        for idx, item in enumerate(arr_val[:8], 1):
                            if isinstance(item, dict):
                                item_text = " | ".join(f"{k}: {v}" for k, v in item.items())
                            else:
                                item_text = str(item)
                            pdf.multi_cell(0, 3, _safe(f"        {idx}. {item_text}", 300), new_x="LMARGIN", new_y="NEXT")

                # Render remaining non-rendered fields
                for field_key, field_val in output.items():
                    if field_key in rendered_keys or field_key in ARRAY_FIELDS:
                        continue
                    if field_val and not isinstance(field_val, (list, dict)):
                        label = field_key.replace("_", " ").title()
                        pdf.set_font("Helvetica", "", 8)
                        pdf.multi_cell(0, 4, _safe(f"      {label}: {field_val}", 300), new_x="LMARGIN", new_y="NEXT")

                # Rationale
                if v.rationale_text:
                    pdf.set_font("Helvetica", "I", 7)
                    pdf.set_text_color(100, 100, 100)
                    pdf.multi_cell(0, 3, _safe(f"      Rationale: {v.rationale_text}", 300), new_x="LMARGIN", new_y="NEXT")
                    pdf.set_text_color(0, 0, 0)

                pdf.ln(2)

            pdf.ln(3)

    # ── Strategic Analysis (WHY) ──
    if opportunities:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 18)
        pdf.cell(0, 12, "Strategic Analysis: Why These Strategies", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(80, 80, 80)
        pdf.multi_cell(0, 5, _safe(
            "This section explains the data-driven reasoning behind each selected strategy. "
            "Every opportunity was identified by combining brand positioning, competitive intelligence, "
            "ad performance data, and market gap analysis through our AI-powered Unified Intelligence engine.", 500
        ), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(4)

        # Performance context from saturation step
        sat_step = next((s for s in run_data.get("steps", []) if s["step_name"] == "saturation_check"), None)
        sat_arts = (sat_step or {}).get("artifacts_json", {})
        if sat_arts:
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 7, "Current Performance Snapshot", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(50, 50, 50)
            spend_14d = float(sat_arts.get("total_spend_14d", 0) or 0)
            pdf.multi_cell(0, 5, _safe(
                f"Active ads: {sat_arts.get('ads_analyzed', 0)} | "
                f"Saturated: {sat_arts.get('saturated_count', 0)} | "
                f"Fresh: {sat_arts.get('fresh_count', 0)} | "
                f"Avg frequency: {sat_arts.get('avg_frequency', 0)} | "
                f"14-day spend: ${spend_14d:,.0f}", 400
            ), new_x="LMARGIN", new_y="NEXT")
            # Fresh ads detail
            for ad in sat_arts.get("fresh_ads", [])[:3]:
                pdf.cell(0, 4, _safe(f"  Fresh: {ad.get('name', '')} (CTR: {ad.get('ctr', 0)}%)", 150), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(4)

        # Source breakdown
        opp_step = next((s for s in run_data.get("steps", []) if s["step_name"] == "opportunities"), None)
        opp_arts = (opp_step or {}).get("artifacts_json", {})
        src_breakdown = opp_arts.get("source_breakdown", {})
        pb = opp_arts.get("priority_breakdown", {})
        if src_breakdown or pb:
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 7, "Opportunity Sources & Priority Distribution", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(50, 50, 50)
            if pb:
                pdf.cell(0, 5, _safe(f"Priority: {pb.get('high', 0)} high | {pb.get('medium', 0)} medium | {pb.get('low', 0)} low", 200), new_x="LMARGIN", new_y="NEXT")
            if src_breakdown:
                sources = " | ".join(f"{k}: {v}" for k, v in src_breakdown.items())
                pdf.cell(0, 5, _safe(f"Data sources: {sources}", 200), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(4)

        # Per-opportunity strategic rationale
        sorted_opps = sorted(opportunities, key=lambda o: float(o.get("estimated_impact", 0) or 0), reverse=True)
        for i, opp in enumerate(sorted_opps[:8], 1):
            if pdf.get_y() > 220:
                pdf.add_page()

            title = opp.get("title") or opp.get("gap_id", f"Strategy {i}")
            priority = opp.get("priority", "medium")
            impact = float(opp.get("estimated_impact", 0) or 0)
            confidence = float(opp.get("confidence", 0) or 0)
            gap_id = opp.get("gap_id", "")

            # Title with priority color
            pdf.set_font("Helvetica", "B", 11)
            if priority == "high":
                pdf.set_text_color(180, 60, 40)
            elif priority == "medium":
                pdf.set_text_color(160, 130, 40)
            else:
                pdf.set_text_color(80, 80, 80)
            pdf.cell(0, 7, _safe(f"{i}. [{priority.upper()}] {title}", 150), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)

            # Metrics bar
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(60, 60, 60)
            metrics = f"Expected impact: {impact:.0%} | Confidence: {confidence:.0%}"
            primary_src = opp.get("primary_source", "")
            sources = opp.get("sources", [])
            if primary_src:
                metrics += f" | Primary source: {primary_src}"
            pdf.cell(0, 5, _safe(metrics, 250), new_x="LMARGIN", new_y="NEXT")
            if sources and isinstance(sources, list):
                pdf.set_font("Helvetica", "I", 8)
                pdf.cell(0, 4, _safe(f"Data signals: {', '.join(str(s) for s in sources[:5])}", 250), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)

            # WHY section: impact reasoning
            impact_reasoning = opp.get("impact_reasoning", "")
            if impact_reasoning:
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(0, 6, "    Why this strategy:", new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 9)
                pdf.set_text_color(40, 40, 40)
                pdf.multi_cell(0, 4, _safe(f"    {impact_reasoning}", 600), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)

            # Description / context
            description = opp.get("description", "")
            if description and description != impact_reasoning:
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(0, 6, "    Context:", new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 8)
                pdf.set_text_color(60, 60, 60)
                pdf.multi_cell(0, 4, _safe(f"    {description}", 600), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)

            pdf.ln(3)

    # ── Implementation Playbook (HOW) ──
    if opportunities:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 18)
        pdf.cell(0, 12, "Implementation Playbook: How to Execute", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(80, 80, 80)
        pdf.multi_cell(0, 5, _safe(
            "Step-by-step action plan for each strategy. Assign owners, follow timelines, "
            "and track KPIs to ensure execution translates into measurable results. "
            "Strategies are ordered by estimated impact.", 500
        ), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(4)

        # Build a map of pack goals for cross-referencing
        pack_map = {}
        for pk in (packs or []):
            pk_goal = pk.goal or "awareness"
            if pk_goal not in pack_map:
                variant_count = db.query(ContentVariant).filter(
                    ContentVariant.content_pack_id == pk.id
                ).count() if pk else 0
                ch_list = pk.channels_json or []
                pack_map[pk_goal] = {
                    "id": str(pk.id)[:8],
                    "channels": [ch.get("channel", "?") for ch in ch_list],
                    "variants": variant_count,
                    "language": pk.language or "es-AR",
                }

        sorted_opps = sorted(opportunities, key=lambda o: float(o.get("estimated_impact", 0) or 0), reverse=True)
        for i, opp in enumerate(sorted_opps[:8], 1):
            if pdf.get_y() > 200:
                pdf.add_page()

            title = opp.get("title") or opp.get("gap_id", f"Strategy {i}")
            priority = opp.get("priority", "medium")
            impact = float(opp.get("estimated_impact", 0) or 0)
            strategy_text = opp.get("strategy", "")

            # Section header
            pdf.set_font("Helvetica", "B", 12)
            if priority == "high":
                pdf.set_text_color(180, 60, 40)
            elif priority == "medium":
                pdf.set_text_color(160, 130, 40)
            else:
                pdf.set_text_color(80, 80, 80)
            pdf.cell(0, 8, _safe(f"Strategy {i}: {title}", 130), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)

            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(0, 4, _safe(f"Priority: {priority.upper()} | Expected impact: {impact:.0%}", 150), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(2)

            # Action steps from strategy
            if strategy_text:
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(0, 6, "    Action Steps:", new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 9)

                # Parse numbered steps from strategy text
                import re as _re
                steps_raw = _re.split(r'\n\s*\d+\.\s*', strategy_text)
                if len(steps_raw) <= 1:
                    # Try splitting on "1. " "2. " etc.
                    steps_raw = _re.split(r'(?:^|\n)\s*\d+\.\s*', strategy_text)

                step_items = [s.strip() for s in steps_raw if s.strip()]
                if step_items:
                    for si, step_text in enumerate(step_items[:7], 1):
                        if pdf.get_y() > 265:
                            pdf.add_page()
                        pdf.set_font("Helvetica", "B", 9)
                        pdf.set_text_color(30, 80, 50)
                        pdf.cell(8, 5, "")
                        pdf.cell(8, 5, _safe(f"{si}.", 5))
                        pdf.set_font("Helvetica", "", 9)
                        pdf.set_text_color(30, 30, 30)
                        pdf.multi_cell(0, 5, _safe(step_text, 400), new_x="LMARGIN", new_y="NEXT")
                else:
                    pdf.multi_cell(0, 5, _safe(f"    {strategy_text}", 600), new_x="LMARGIN", new_y="NEXT")

            pdf.ln(2)

            # Content assets available
            # Try to match opportunity to content pack by goal keywords
            opp_title_lower = (opp.get("title", "") or "").lower()
            matched_pack = None
            if "premium" in opp_title_lower or "sale" in opp_title_lower or "monetiz" in opp_title_lower or "revenue" in opp_title_lower:
                matched_pack = pack_map.get("sales")
            if not matched_pack and ("lead" in opp_title_lower or "captar" in opp_title_lower):
                matched_pack = pack_map.get("leads")
            if not matched_pack and ("retenci" in opp_title_lower or "retent" in opp_title_lower or "transformation" in opp_title_lower or "documentation" in opp_title_lower):
                matched_pack = pack_map.get("retention")
            if not matched_pack:
                # Use first available pack
                matched_pack = next(iter(pack_map.values()), None)

            if matched_pack and matched_pack.get("variants", 0) > 0:
                if pdf.get_y() > 255:
                    pdf.add_page()
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(0, 6, "    Content Assets Ready:", new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 9)
                pdf.set_text_color(30, 80, 130)
                ch_str = ", ".join(matched_pack["channels"][:6])
                pdf.cell(0, 5, _safe(
                    f"    Content Pack {matched_pack['id']} | {matched_pack['variants']} variants | "
                    f"Channels: {ch_str} | Language: {matched_pack['language']}", 250
                ), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_text_color(80, 80, 80)
                pdf.cell(0, 4, _safe(
                    "    Use the Content Studio page to view, lock preferred variants, and export assets.", 250
                ), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)

            pdf.ln(2)

            # KPIs to track
            if pdf.get_y() > 255:
                pdf.add_page()
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 6, "    KPIs to Track:", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(50, 50, 50)

            # Generate relevant KPIs based on opportunity keywords
            opp_text_lower = (opp.get("title", "") + " " + opp.get("strategy", "")).lower()
            kpis = []
            if any(kw in opp_text_lower for kw in ["lead", "captar", "formulario", "sign up"]):
                kpis = ["Cost per lead (CPL)", "Lead volume per week", "Lead quality score", "Form completion rate"]
            elif any(kw in opp_text_lower for kw in ["sale", "venta", "revenue", "premium", "monetiz", "price"]):
                kpis = ["Revenue per customer", "Conversion rate", "Average order value", "Customer acquisition cost (CAC)"]
            elif any(kw in opp_text_lower for kw in ["retenci", "retent", "alumni", "churn", "sustain"]):
                kpis = ["Monthly retention rate", "Churn rate", "Lifetime value (LTV)", "Re-engagement rate"]
            elif any(kw in opp_text_lower for kw in ["content", "transformation", "documentation"]):
                kpis = ["Content engagement rate", "Avg. time on content", "Share/save rate", "Content-to-lead conversion"]
            elif any(kw in opp_text_lower for kw in ["saturation", "creative", "scale", "fresh"]):
                kpis = ["Ad frequency", "CTR trend (week-over-week)", "CPM efficiency", "Creative fatigue index"]
            elif any(kw in opp_text_lower for kw in ["budget", "diversif", "campaign", "portfolio"]):
                kpis = ["ROAS by campaign objective", "Budget utilization rate", "Cross-campaign CTR", "Cost per result by objective"]
            elif any(kw in opp_text_lower for kw in ["naming", "tracking", "utm"]):
                kpis = ["Attribution accuracy", "Campaign identification speed", "Cross-channel tracking coverage"]
            elif any(kw in opp_text_lower for kw in ["competitor", "counter", "exploit", "positioning"]):
                kpis = ["Share of voice vs competitor", "Brand mention sentiment", "Competitive content engagement", "Audience overlap shift"]
            else:
                kpis = ["CTR (Click-through rate)", "CPM (Cost per 1000 impressions)", "Engagement rate", "Reach growth"]

            for kpi in kpis[:4]:
                pdf.cell(0, 5, _safe(f"    * {kpi}", 150), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)

            # Timeline
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 6, "    Suggested Timeline:", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(50, 50, 50)
            if priority == "high":
                pdf.cell(0, 5, _safe("    Week 1-2: Set up and launch | Week 3-4: Monitor and optimize | Week 5-8: Scale what works", 250), new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.cell(0, 5, _safe("    Week 1-4: Plan and prepare | Week 5-8: Launch and test | Week 9-12: Evaluate and iterate", 250), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)

            pdf.ln(5)

            # Separator line
            pdf.set_draw_color(200, 200, 200)
            pdf.line(pdf.get_x() + 10, pdf.get_y(), pdf.get_x() + 180, pdf.get_y())
            pdf.ln(3)

    # ── Footer ──
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    pdf.cell(0, 10, f"Generated by Meta Ops Agent on {now}", new_x="LMARGIN", new_y="NEXT")

    return pdf.output()
