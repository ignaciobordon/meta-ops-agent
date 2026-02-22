"""
Meta Ops Agent - FastAPI Backend
Multi-tenant SaaS platform for autonomous Meta Ads management.
"""
import sys
from pathlib import Path

# Add project root to path for src.* imports
# This makes both src/ (utils, engines, core) and backend/ accessible
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.src.api import (
    alerts, analytics, api_keys, audit, auth, billing, brain, brandmap, ci_autoloop,
    content_studio, creatives, dashboard, data_room, decisions, events, flywheel, meta,
    meta_sync, onboarding, ops, org_config, orgs, opportunities, outcomes, policies,
    reports, saturation, system, templates,
)
from backend.src.ci.router import router as ci_router
from backend.src.database.session import init_db
from backend.src.middleware.auth import (
    require_admin,
    require_any_authenticated,
    require_operator_or_admin,
    require_permission,
    Permission,
)
from backend.src.middleware.error_handler import GlobalErrorHandler
from backend.src.middleware.rate_limit import RateLimitMiddleware
from backend.src.middleware.request_context import RequestContextMiddleware
from backend.src.middleware.security_headers import SecurityHeadersMiddleware
from backend.src.observability import health_router, metrics_middleware
from backend.src.observability.metrics import metrics_endpoint
from src.utils.logging_config import logger

app = FastAPI(
    title="Meta Ops Agent API",
    version="1.0.0",
    description="Autonomous Meta Ads management with human-in-the-loop approval",
    redirect_slashes=False,
)

# Prometheus Metrics Middleware (track HTTP requests, durations, etc.)
app.add_middleware(metrics_middleware)

# Security Headers (X-Frame-Options, X-Content-Type-Options, etc.)
app.add_middleware(SecurityHeadersMiddleware)

# Rate Limiting (200 requests per minute per client)
# Note: /api/auth has its own dedicated LoginRateLimiter (5 attempts/5 min/IP)
app.add_middleware(
    RateLimitMiddleware,
    rate=200,
    window=60,
    exclude_paths=["/api/health", "/api/auth", "/metrics", "/docs", "/openapi.json", "/redoc"]
)

# CORS — configurable via FRONTEND_URL env var
from backend.src.config import settings as _settings
_cors_origins = [o.strip() for o in _settings.FRONTEND_URL.split(",") if o.strip()]
if "http://localhost:5173" not in _cors_origins:
    _cors_origins.append("http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
)

# Request Context (X-Request-ID correlation + structured request logging)
app.add_middleware(RequestContextMiddleware)

# Global Error Handler (catch unhandled exceptions → structured JSON)
# Added last → runs outermost in Starlette's middleware stack
app.add_middleware(GlobalErrorHandler)

# ── Public routes (no auth) ──────────────────────────────────────────────────
app.include_router(health_router, prefix="/api", tags=["Health"])
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])

# ── Protected routes (viewer+: read-only) ────────────────────────────────────
app.include_router(
    dashboard.router, prefix="/api/dashboard", tags=["Dashboard"],
    dependencies=[Depends(require_any_authenticated)],
)
app.include_router(
    audit.router, prefix="/api/audit", tags=["Audit"],
    dependencies=[Depends(require_any_authenticated)],
)
app.include_router(
    creatives.router, prefix="/api/creatives", tags=["Creatives"],
    dependencies=[Depends(require_any_authenticated)],
)
app.include_router(
    opportunities.router, prefix="/api/opportunities", tags=["Opportunities"],
    dependencies=[Depends(require_any_authenticated)],
)
app.include_router(
    saturation.router, prefix="/api/saturation", tags=["Saturation"],
    dependencies=[Depends(require_any_authenticated)],
)
app.include_router(
    policies.router, prefix="/api/policies", tags=["Policies"],
    dependencies=[Depends(require_any_authenticated)],
)

# ── Protected routes (operator+: create/approve decisions) ────────────────────
app.include_router(
    decisions.router, prefix="/api/decisions", tags=["Decisions"],
    dependencies=[Depends(require_any_authenticated)],
)

# ── Meta OAuth + Multi-Account (FASE 5.4) ────────────────────────────────────
# Individual endpoints handle their own auth via Depends().
# OAuth callback has no auth (it's a redirect from Meta; CSRF via state param).
app.include_router(
    meta.router, prefix="/api/meta", tags=["Meta"],
)

# ── Protected routes (admin: org management, settings) ────────────────────────
app.include_router(
    orgs.router, prefix="/api/orgs", tags=["Organizations"],
    dependencies=[Depends(require_any_authenticated)],
)

# ── Billing (Sprint 4) ────────────────────────────────────────────────────────
# Webhook is public (verified via Stripe signature); other endpoints require auth.
app.include_router(
    billing.router, prefix="/api/billing", tags=["Billing"],
)

# ── API Keys (Sprint 4) ──────────────────────────────────────────────────────
app.include_router(
    api_keys.router, prefix="/api/keys", tags=["API Keys"],
    dependencies=[Depends(require_any_authenticated)],
)

# ── Meta Sync Data Plane (Sprint 6) ──────────────────────────────────────────
app.include_router(
    meta_sync.router, prefix="/api/meta", tags=["Meta Sync"],
    dependencies=[Depends(require_any_authenticated)],
)

# ── Ops Console (Sprint 7) ──────────────────────────────────────────────────
app.include_router(
    ops.router, prefix="/api/ops", tags=["Ops Console"],
    dependencies=[Depends(require_admin)],
)

# ── Sprint 8: Growth + Product ──────────────────────────────────────────────
app.include_router(
    onboarding.router, prefix="/api/onboarding", tags=["Onboarding"],
    dependencies=[Depends(require_any_authenticated)],
)
app.include_router(
    templates.router, prefix="/api/templates", tags=["Templates"],
    dependencies=[Depends(require_any_authenticated)],
)
app.include_router(
    org_config.router, prefix="/api/org-config", tags=["Org Config"],
    dependencies=[Depends(require_any_authenticated)],
)
app.include_router(
    alerts.router, prefix="/api/alerts", tags=["Alert Center"],
    dependencies=[Depends(require_any_authenticated)],
)
app.include_router(
    analytics.router, prefix="/api/analytics", tags=["Analytics"],
    dependencies=[Depends(require_any_authenticated)],
)
app.include_router(
    events.router, prefix="/api/events", tags=["Events"],
    dependencies=[Depends(require_any_authenticated)],
)

# ── Sprint 10: System Diagnostics (admin-only) ──────────────────────────────
app.include_router(
    system.router, prefix="/api/system", tags=["System"],
    dependencies=[Depends(require_admin)],
)

# ── Sprint 11: Decision Report Exports ──────────────────────────────────────
app.include_router(
    reports.router, prefix="/api/reports", tags=["Reports"],
    dependencies=[Depends(require_any_authenticated)],
)

# ── Sprint 13: Content Studio ─────────────────────────────────────────────
app.include_router(
    content_studio.router, prefix="/api/content-studio", tags=["Content Studio"],
    dependencies=[Depends(require_any_authenticated)],
)

# ── BrandMap Profiles ───────────────────────────────────────────────────────
app.include_router(
    brandmap.router, prefix="/api/brandmap", tags=["BrandMap"],
    dependencies=[Depends(require_any_authenticated)],
)

# ── Competitive Intelligence (CI Module) ───────────────────────────────────
app.include_router(
    ci_router, prefix="/api/ci", tags=["Competitive Intelligence"],
    dependencies=[Depends(require_any_authenticated)],
)
app.include_router(
    ci_autoloop.router, prefix="/api/ci/autoloop", tags=["CI AutoLoop"],
    dependencies=[Depends(require_any_authenticated)],
)

# ── Sprint 13: Flywheel & Data Room ─────────────────────────────────────────
app.include_router(
    flywheel.router, prefix="/api/flywheel", tags=["Flywheel"],
    dependencies=[Depends(require_any_authenticated)],
)
app.include_router(
    data_room.router, prefix="/api/data-room", tags=["Data Room"],
    dependencies=[Depends(require_any_authenticated)],
)

# ── Outcomes + Brain (Sprint 5) ──────────────────────────────────────────────
app.include_router(
    outcomes.router, prefix="/api", tags=["Outcomes"],
    dependencies=[Depends(require_any_authenticated)],
)
app.include_router(
    brain.router, prefix="/api", tags=["Brain"],
    dependencies=[Depends(require_any_authenticated)],
)

# Prometheus metrics endpoint (scraped by Prometheus)
app.add_route("/metrics", metrics_endpoint, methods=["GET"])


# ── Exception handlers (structured JSON errors) ─────────────────────────────

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Return structured JSON for all HTTPExceptions (FastAPI + Starlette).
    Keeps 'detail' for backward compat; adds 'error' for structured clients.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "error": {
                "code": f"HTTP_{exc.status_code}",
                "message": exc.detail,
                "request_id": request_id,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return structured JSON for validation errors.
    Keeps 'detail' for backward compat; adds 'error' for structured clients.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=422,
        content={
            "detail": exc.errors(),
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": exc.errors(),
                "request_id": request_id,
            }
        },
    )


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    logger.info("API_STARTUP | Initializing database...")
    init_db()
    logger.info("API_STARTUP | Database initialized")

    # OpenTelemetry instrumentation (Sprint 7)
    from backend.src.observability.telemetry import setup_telemetry
    setup_telemetry(app=app)


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("API_SHUTDOWN")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
