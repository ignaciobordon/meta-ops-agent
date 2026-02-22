"""
FASE 4.2: Enhanced Health Checks
Comprehensive health monitoring with dependency checks.
"""
from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from typing import Dict, Optional
from enum import Enum
import time
from datetime import datetime

from backend.src.config import settings


class HealthStatus(str, Enum):
    """Health status values."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class DependencyHealth(BaseModel):
    """Health status for a single dependency."""
    status: HealthStatus
    response_time_ms: Optional[float] = None
    details: Optional[str] = None
    error: Optional[str] = None


class HealthCheckResponse(BaseModel):
    """Complete health check response."""
    status: HealthStatus
    timestamp: str
    uptime_seconds: float
    dependencies: Dict[str, DependencyHealth]
    version: str = "1.0.0"


router = APIRouter(tags=["Health"])

# Track application start time
_start_time = time.time()


def check_database() -> DependencyHealth:
    """Check PostgreSQL database connectivity."""
    start = time.time()
    try:
        from backend.src.database.session import get_db
        from sqlalchemy import text

        # Get database session
        db = next(get_db())

        # Execute simple query
        db.execute(text("SELECT 1"))
        db.close()

        elapsed = (time.time() - start) * 1000
        return DependencyHealth(
            status=HealthStatus.HEALTHY,
            response_time_ms=round(elapsed, 2),
            details="Database connection successful"
        )
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return DependencyHealth(
            status=HealthStatus.UNHEALTHY,
            response_time_ms=round(elapsed, 2),
            error=str(e)
        )


def check_chromadb() -> DependencyHealth:
    """Check ChromaDB vector database connectivity."""
    start = time.time()
    try:
        from src.database.vector.db_client import VectorDBClient

        # Initialize client
        client = VectorDBClient()

        # Test collection access
        client.get_collection("brand_maps")

        elapsed = (time.time() - start) * 1000
        return DependencyHealth(
            status=HealthStatus.HEALTHY,
            response_time_ms=round(elapsed, 2),
            details="ChromaDB accessible"
        )
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return DependencyHealth(
            status=HealthStatus.UNHEALTHY,
            response_time_ms=round(elapsed, 2),
            error=str(e)
        )


def check_anthropic_api() -> DependencyHealth:
    """Check Anthropic API availability."""
    start = time.time()
    try:
        api_key = settings.ANTHROPIC_API_KEY

        if not api_key:
            return DependencyHealth(
                status=HealthStatus.DEGRADED,
                response_time_ms=0,
                details="ANTHROPIC_API_KEY not configured"
            )

        # Simple check: API key is present
        # For full check, would need to make actual API call (costs money)
        elapsed = (time.time() - start) * 1000
        return DependencyHealth(
            status=HealthStatus.HEALTHY,
            response_time_ms=round(elapsed, 2),
            details="API key configured"
        )
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return DependencyHealth(
            status=HealthStatus.DEGRADED,
            response_time_ms=round(elapsed, 2),
            error=str(e)
        )


def check_disk_space() -> DependencyHealth:
    """Check available disk space."""
    start = time.time()
    try:
        import shutil

        # Check disk space for current directory
        total, used, free = shutil.disk_usage("/")

        # Convert to GB
        free_gb = free / (1024**3)
        total_gb = total / (1024**3)
        percent_free = (free / total) * 100

        # Alert if less than 10% or 5GB free
        if percent_free < 10 or free_gb < 5:
            status_val = HealthStatus.DEGRADED
            details = f"Low disk space: {free_gb:.1f}GB / {total_gb:.1f}GB ({percent_free:.1f}% free)"
        else:
            status_val = HealthStatus.HEALTHY
            details = f"Disk space OK: {free_gb:.1f}GB / {total_gb:.1f}GB ({percent_free:.1f}% free)"

        elapsed = (time.time() - start) * 1000
        return DependencyHealth(
            status=status_val,
            response_time_ms=round(elapsed, 2),
            details=details
        )
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return DependencyHealth(
            status=HealthStatus.DEGRADED,
            response_time_ms=round(elapsed, 2),
            error=str(e)
        )


def check_redis() -> DependencyHealth:
    """Check Redis connectivity."""
    start = time.time()
    try:
        from backend.src.infra.redis_client import redis_available
        if redis_available():
            elapsed = (time.time() - start) * 1000
            return DependencyHealth(
                status=HealthStatus.HEALTHY,
                response_time_ms=round(elapsed, 2),
                details="Redis connection successful",
            )
        else:
            elapsed = (time.time() - start) * 1000
            return DependencyHealth(
                status=HealthStatus.DEGRADED,
                response_time_ms=round(elapsed, 2),
                details="Redis unavailable — system in degraded mode",
            )
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return DependencyHealth(
            status=HealthStatus.DEGRADED,
            response_time_ms=round(elapsed, 2),
            error=str(e),
        )


def check_meta_api() -> DependencyHealth:
    """Check Meta API configuration."""
    start = time.time()
    try:
        app_id = settings.META_APP_ID or ""
        app_secret = settings.META_APP_SECRET or ""

        if not app_id or not app_secret:
            return DependencyHealth(
                status=HealthStatus.DEGRADED,
                response_time_ms=0,
                details="Meta API credentials not configured"
            )

        elapsed = (time.time() - start) * 1000
        return DependencyHealth(
            status=HealthStatus.HEALTHY,
            response_time_ms=round(elapsed, 2),
            details="Meta API credentials configured"
        )
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return DependencyHealth(
            status=HealthStatus.DEGRADED,
            response_time_ms=round(elapsed, 2),
            error=str(e)
        )


@router.get("/health", response_model=HealthCheckResponse)
async def health_check(response: Response):
    """
    Comprehensive health check endpoint.

    Checks:
    - Database connectivity (PostgreSQL)
    - Vector database (ChromaDB)
    - API credentials (Anthropic, Meta)
    - Disk space

    Returns:
    - 200 OK: All critical systems healthy
    - 207 Multi-Status: Some degraded dependencies
    - 503 Service Unavailable: Critical systems down
    """
    # Check all dependencies
    dependencies = {
        "database": check_database(),
        "redis": check_redis(),
        "chromadb": check_chromadb(),
        "anthropic_api": check_anthropic_api(),
        "meta_api": check_meta_api(),
        "disk_space": check_disk_space(),
    }

    # Determine overall status
    unhealthy_count = sum(1 for dep in dependencies.values() if dep.status == HealthStatus.UNHEALTHY)
    degraded_count = sum(1 for dep in dependencies.values() if dep.status == HealthStatus.DEGRADED)

    if unhealthy_count > 0:
        overall_status = HealthStatus.UNHEALTHY
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    elif degraded_count > 0:
        overall_status = HealthStatus.DEGRADED
        http_status = status.HTTP_207_MULTI_STATUS
    else:
        overall_status = HealthStatus.HEALTHY
        http_status = status.HTTP_200_OK

    # Calculate uptime
    uptime = time.time() - _start_time

    # Set HTTP status code
    response.status_code = http_status

    return HealthCheckResponse(
        status=overall_status,
        timestamp=datetime.utcnow().isoformat(),
        uptime_seconds=round(uptime, 2),
        dependencies=dependencies
    )


@router.get("/health/ready")
async def readiness_check(response: Response):
    """
    Kubernetes-style readiness probe.

    Returns 200 if application is ready to serve traffic.
    Checks only critical dependencies (database, chromadb).
    """
    db = check_database()
    chroma = check_chromadb()

    if db.status == HealthStatus.UNHEALTHY or chroma.status == HealthStatus.UNHEALTHY:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"ready": False, "reason": "Critical dependencies unavailable"}

    return {"ready": True}


@router.get("/health/live")
async def liveness_check():
    """
    Kubernetes-style liveness probe.

    Returns 200 if application process is alive.
    Does not check dependencies (fast check).
    """
    return {
        "alive": True,
        "uptime_seconds": round(time.time() - _start_time, 2)
    }
