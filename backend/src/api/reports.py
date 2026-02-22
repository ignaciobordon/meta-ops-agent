"""
Sprint 11 — BLOQUE E: Decision report export endpoints (DOCX + XLSX).
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user
from backend.src.services.report_service import ReportBuilder
from backend.src.utils.tenant import get_org_ad_account_ids

router = APIRouter(tags=["Reports"])


@router.get("/decisions/{decision_id}/docx")
def export_decision_docx(
    decision_id: UUID,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Download a DOCX report for a decision."""
    org_id = user.get("org_id", "")
    ad_account_ids = get_org_ad_account_ids(org_id, db)

    builder = ReportBuilder(db)
    buf = builder.build_docx(decision_id, ad_account_ids)
    if not buf:
        raise HTTPException(status_code=404, detail="Decision not found or not accessible")

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=decision_{decision_id}.docx"},
    )


@router.get("/decisions/{decision_id}/xlsx")
def export_decision_xlsx(
    decision_id: UUID,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Download an XLSX report for a decision."""
    org_id = user.get("org_id", "")
    ad_account_ids = get_org_ad_account_ids(org_id, db)

    builder = ReportBuilder(db)
    buf = builder.build_xlsx(decision_id, ad_account_ids)
    if not buf:
        raise HTTPException(status_code=404, detail="Decision not found or not accessible")

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=decision_{decision_id}.xlsx"},
    )
