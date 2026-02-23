"""Sprint 8 — Alert Center API: unified alert management with ack/resolve/snooze."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.src.database.models import MetaAlert
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user

router = APIRouter()


class AlertResponse(BaseModel):
    id: str
    alert_type: str
    severity: str
    message: str
    entity_type: Optional[str] = None
    entity_meta_id: Optional[str] = None
    detected_at: str
    resolved_at: Optional[str] = None
    status: str = "active"
    acknowledged_at: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


def _serialize_alert(a: MetaAlert) -> dict:
    return {
        "id": str(a.id),
        "alert_type": a.alert_type,
        "severity": a.severity.value if hasattr(a.severity, 'value') else str(a.severity),
        "message": a.message,
        "entity_type": a.entity_type,
        "entity_meta_id": a.entity_meta_id,
        "detected_at": a.detected_at.isoformat() if a.detected_at else None,
        "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
        "status": a.status or "active",
        "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
        "payload": a.payload_json,
    }


@router.get("/")
def list_alerts(
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    alert_type: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List alerts with filters."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    query = db.query(MetaAlert).filter(MetaAlert.org_id == UUID(org_id))

    if status:
        query = query.filter(MetaAlert.status == status)
    else:
        # Default: active only (not resolved, not snoozed)
        query = query.filter(MetaAlert.status.in_(["active", "acknowledged"]))

    if severity:
        query = query.filter(MetaAlert.severity == severity)

    if alert_type:
        query = query.filter(MetaAlert.alert_type == alert_type)

    total = query.count()
    alerts = query.order_by(MetaAlert.detected_at.desc()).offset(offset).limit(limit).all()

    return {
        "data": [_serialize_alert(a) for a in alerts],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/stats")
def get_alert_stats(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get alert counts by severity and status."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    alerts = db.query(MetaAlert).filter(
        MetaAlert.org_id == UUID(org_id),
        MetaAlert.status.in_(["active", "acknowledged"]),
    ).all()

    by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    by_status = {"active": 0, "acknowledged": 0}

    for a in alerts:
        sev = a.severity.value if hasattr(a.severity, 'value') else str(a.severity)
        if sev in by_severity:
            by_severity[sev] += 1
        status = a.status or "active"
        if status in by_status:
            by_status[status] += 1

    return {
        "total": len(alerts),
        "by_severity": by_severity,
        "by_status": by_status,
    }


@router.get("/{alert_id}")
def get_alert(
    alert_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get alert detail."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    alert = db.query(MetaAlert).filter(
        MetaAlert.id == UUID(alert_id),
        MetaAlert.org_id == UUID(org_id),
    ).first()

    if not alert:
        raise HTTPException(404, "Alert not found")

    return _serialize_alert(alert)


@router.post("/{alert_id}/acknowledge")
def acknowledge_alert(
    alert_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Acknowledge an alert."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    alert = db.query(MetaAlert).filter(
        MetaAlert.id == UUID(alert_id),
        MetaAlert.org_id == UUID(org_id),
    ).first()

    if not alert:
        raise HTTPException(404, "Alert not found")

    alert.status = "acknowledged"
    alert.acknowledged_by_user_id = UUID(user["id"])
    alert.acknowledged_at = datetime.utcnow()
    db.commit()

    return _serialize_alert(alert)


@router.post("/{alert_id}/resolve")
def resolve_alert(
    alert_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Resolve an alert."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    alert = db.query(MetaAlert).filter(
        MetaAlert.id == UUID(alert_id),
        MetaAlert.org_id == UUID(org_id),
    ).first()

    if not alert:
        raise HTTPException(404, "Alert not found")

    alert.status = "resolved"
    alert.resolved_at = datetime.utcnow()
    db.commit()

    return _serialize_alert(alert)


class SnoozeRequest(BaseModel):
    snooze_until: Optional[str] = None


@router.post("/{alert_id}/snooze")
def snooze_alert(
    alert_id: str,
    body: SnoozeRequest = SnoozeRequest(),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Snooze an alert."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    alert = db.query(MetaAlert).filter(
        MetaAlert.id == UUID(alert_id),
        MetaAlert.org_id == UUID(org_id),
    ).first()

    if not alert:
        raise HTTPException(404, "Alert not found")

    alert.status = "snoozed"
    # Store snooze_until in payload
    payload = dict(alert.payload_json or {})
    if body.snooze_until:
        payload["snooze_until"] = body.snooze_until
    alert.payload_json = payload
    db.commit()

    return _serialize_alert(alert)


# ── Alerts Export (PDF) ──────────────────────────────────────────────────────


def _build_alerts_pdf(alerts_data: list, stats_data: dict) -> bytes:
    """Build PDF report for alerts."""
    from fpdf import FPDF
    from backend.src.utils.pdf_fonts import setup_pdf_fonts

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)

    _font = setup_pdf_fonts(pdf)

    pdf.add_page()

    # Title
    pdf.set_font(_font, "B", 18)
    pdf.cell(0, 12, "Alert Center Report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(_font, "", 10)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6, f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | {len(alerts_data)} alerts", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Stats Summary
    by_sev = stats_data.get("by_severity", {})
    pdf.set_draw_color(212, 175, 55)
    pdf.set_fill_color(252, 249, 240)
    pdf.rect(10, pdf.get_y(), 190, 14, style="DF")
    y0 = pdf.get_y() + 2
    pdf.set_xy(14, y0)
    pdf.set_text_color(60, 60, 60)
    pdf.set_font(_font, "B", 9)
    sev_labels = [
        f"Critical: {by_sev.get('critical', 0)}",
        f"High: {by_sev.get('high', 0)}",
        f"Medium: {by_sev.get('medium', 0)}",
        f"Low: {by_sev.get('low', 0)}",
        f"Total: {stats_data.get('total', 0)}",
    ]
    for i, label in enumerate(sev_labels):
        pdf.set_x(14 + i * 38)
        pdf.cell(38, 10, label)
    pdf.set_y(y0 + 14)
    pdf.ln(4)

    # Alert Table
    if alerts_data:
        pdf.set_font(_font, "B", 7)
        pdf.set_fill_color(240, 240, 235)
        cols = [18, 25, 75, 25, 25, 22]
        hdrs = ["Severity", "Type", "Message", "Entity", "Status", "Detected"]
        for i, h in enumerate(hdrs):
            pdf.cell(cols[i], 6, h, border=1, fill=True)
        pdf.ln()

        severity_colors = {
            "critical": (186, 96, 68),
            "high": (196, 130, 52),
            "medium": (196, 164, 52),
            "low": (139, 152, 87),
            "info": (120, 120, 120),
        }

        pdf.set_font(_font, "", 7)
        for a in alerts_data[:50]:
            sev = a.get("severity", "info")
            r, g, b = severity_colors.get(sev, (120, 120, 120))
            pdf.set_text_color(r, g, b)
            pdf.cell(cols[0], 5, sev.upper(), border=1)
            pdf.set_text_color(60, 60, 60)
            pdf.cell(cols[1], 5, str(a.get("alert_type", ""))[:14], border=1)
            pdf.cell(cols[2], 5, str(a.get("message", ""))[:42], border=1)
            entity = a.get("entity_meta_id", "") or ""
            pdf.cell(cols[3], 5, str(entity)[:14], border=1)
            pdf.cell(cols[4], 5, str(a.get("status", ""))[:12], border=1)
            detected = a.get("detected_at", "")
            if detected:
                detected = detected[:10]
            pdf.cell(cols[5], 5, detected, border=1)
            pdf.ln()
        pdf.ln(4)

    # Footer
    pdf.ln(4)
    pdf.set_font(_font, "I", 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 5, "Generated by Meta Ops Agent - Alert Center", new_x="LMARGIN", new_y="NEXT")

    return pdf.output()


@router.get("/export/pdf")
def export_alerts_pdf(
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export alerts as a PDF report."""
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization")

    try:
        # Reuse query logic from list_alerts
        query = db.query(MetaAlert).filter(MetaAlert.org_id == UUID(org_id))
        if status:
            query = query.filter(MetaAlert.status == status)
        if severity:
            query = query.filter(MetaAlert.severity == severity)

        alerts = query.order_by(MetaAlert.detected_at.desc()).limit(100).all()
        alerts_data = [_serialize_alert(a) for a in alerts]

        # Get stats
        all_active = db.query(MetaAlert).filter(
            MetaAlert.org_id == UUID(org_id),
            MetaAlert.status.in_(["active", "acknowledged"]),
        ).all()

        by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        for a in all_active:
            sev = a.severity.value if hasattr(a.severity, 'value') else str(a.severity)
            if sev in by_severity:
                by_severity[sev] += 1

        stats_data = {"total": len(all_active), "by_severity": by_severity}

        pdf_bytes = _build_alerts_pdf(alerts_data, stats_data)

        filename = f"alerts_report_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to generate alerts PDF: {str(e)}")
