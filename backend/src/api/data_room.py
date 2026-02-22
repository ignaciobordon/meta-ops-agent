"""Data Room API — Schema, export, and download endpoints."""
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from uuid import UUID, uuid4
from datetime import datetime
import io

from backend.src.database.session import get_db
from backend.src.database.models import DataExport
from backend.src.middleware.auth import get_current_user
from backend.src.services.data_room_export_service import DataRoomExportService
from backend.src.jobs.queue import enqueue
from src.utils.logging_config import logger

router = APIRouter(tags=["data-room"])


# ── Request/Response Models ──────────────────────────────────────────────────


class DatasetSchemaResponse(BaseModel):
    key: str
    display_name: str
    description: str
    columns: List[str] = []


class ExportRequest(BaseModel):
    datasets: Optional[List[str]] = None  # None = all datasets
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    entity_type: Optional[str] = None
    ad_account_id: Optional[str] = None
    status: Optional[str] = None
    severity: Optional[str] = None
    limit: int = 10000
    include_json_columns: bool = True


class AsyncExportResponse(BaseModel):
    export_id: str
    job_id: str
    status: str = "queued"


class ExportStatusResponse(BaseModel):
    id: str
    status: str
    rows_exported: int = 0
    file_path: Optional[str] = None
    created_at: Optional[str] = None
    finished_at: Optional[str] = None
    last_error: Optional[str] = None
    params_json: Dict[str, Any] = {}


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/schema", response_model=List[DatasetSchemaResponse])
def get_schema(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Return available datasets and their column info."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization context")

    svc = DataRoomExportService(db, org_id)
    datasets = svc.get_schema()
    return [DatasetSchemaResponse(**d) for d in datasets]


@router.post("/export", status_code=202, response_model=AsyncExportResponse)
def create_export(
    request: ExportRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Create a DataExport record and enqueue data_room_export job."""
    org_id = user.get("org_id", "")
    user_id = user.get("user_id", "")
    if not org_id:
        raise HTTPException(400, "No organization context")

    params = {
        "datasets": request.datasets,
        "date_from": request.date_from,
        "date_to": request.date_to,
        "entity_type": request.entity_type,
        "ad_account_id": request.ad_account_id,
        "status": request.status,
        "severity": request.severity,
        "limit": request.limit,
        "include_json_columns": request.include_json_columns,
    }

    export = DataExport(
        id=uuid4(),
        org_id=UUID(org_id),
        status="queued",
        requested_by_user_id=UUID(user_id) if user_id else None,
        params_json=params,
    )
    db.add(export)
    db.flush()

    job_id = enqueue(
        task_name="data_room_export",
        payload={"export_id": str(export.id)},
        org_id=org_id,
        db=db,
    )

    export.job_run_id = UUID(job_id)
    db.commit()

    logger.info(
        "DATA_ROOM_EXPORT_ENQUEUED | export={} | job={} | org={}",
        export.id, job_id, org_id,
    )

    return AsyncExportResponse(export_id=str(export.id), job_id=job_id, status="queued")


@router.get("/exports", response_model=List[ExportStatusResponse])
def list_exports(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List previous exports for org."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization context")

    exports = (
        db.query(DataExport)
        .filter(DataExport.org_id == UUID(org_id))
        .order_by(DataExport.created_at.desc())
        .limit(limit)
        .all()
    )

    return [
        ExportStatusResponse(
            id=str(e.id),
            status=e.status or "queued",
            rows_exported=e.rows_exported or 0,
            file_path=e.file_path,
            created_at=e.created_at.isoformat() if e.created_at else None,
            finished_at=e.finished_at.isoformat() if e.finished_at else None,
            last_error=e.last_error,
            params_json=e.params_json or {},
        )
        for e in exports
    ]


@router.get("/exports/{export_id}", response_model=ExportStatusResponse)
def get_export(
    export_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get export status."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization context")

    export = (
        db.query(DataExport)
        .filter(DataExport.id == UUID(export_id), DataExport.org_id == UUID(org_id))
        .first()
    )
    if not export:
        raise HTTPException(404, "Export not found")

    return ExportStatusResponse(
        id=str(export.id),
        status=export.status or "queued",
        rows_exported=export.rows_exported or 0,
        file_path=export.file_path,
        created_at=export.created_at.isoformat() if export.created_at else None,
        finished_at=export.finished_at.isoformat() if export.finished_at else None,
        last_error=export.last_error,
        params_json=export.params_json or {},
    )


@router.get("/exports/{export_id}/download")
def download_export(
    export_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Download the XLSX file for a completed export."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization context")

    export = (
        db.query(DataExport)
        .filter(DataExport.id == UUID(export_id), DataExport.org_id == UUID(org_id))
        .first()
    )
    if not export:
        raise HTTPException(404, "Export not found")

    if export.status != "succeeded":
        raise HTTPException(400, f"Export is not ready (status: {export.status})")

    if not export.file_path:
        raise HTTPException(404, "Export file not available")

    try:
        with open(export.file_path, "rb") as f:
            file_bytes = f.read()
    except FileNotFoundError:
        raise HTTPException(404, "Export file not found on disk")

    filename = f"data_room_export_{str(export.id)[:8]}_{datetime.utcnow().strftime('%Y%m%d')}.xlsx"

    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
