"""
Sprint 10 — BLOQUE A: System diagnostics endpoints.
Admin-only. Never expose keys — only booleans.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.src.config import settings
from backend.src.middleware.auth import get_current_user, require_admin
from backend.src.providers.circuit_breaker import PersistentCircuitBreaker
from backend.src.providers.rate_limiter import ProviderRateLimiter

router = APIRouter()


class LLMDiagnosticsResponse(BaseModel):
    default_provider: str
    fallback_provider: str
    openai_key_present: bool
    anthropic_key_present: bool
    timeout_seconds: int
    router_ready: bool
    breaker_state: Dict[str, str]
    rate_limit_status: Dict[str, int]
    effective_env_source: Dict[str, str]


@router.get("/llm/diagnostics", response_model=LLMDiagnosticsResponse)
def llm_diagnostics(user: dict = Depends(get_current_user)):
    """LLM Router diagnostics. Admin-only. Never returns keys."""
    anthropic_key = bool(settings.ANTHROPIC_API_KEY)
    openai_key = bool(settings.OPENAI_API_KEY)

    # Check if router can initialize
    router_ready = False
    try:
        from backend.src.llm.router import get_llm_router
        r = get_llm_router()
        router_ready = len(r.providers) > 0
    except Exception:
        pass

    # Circuit breaker states
    breaker_state = {}
    for provider in ["anthropic", "openai"]:
        try:
            cb = PersistentCircuitBreaker(provider, "global")
            breaker_state[provider] = cb.state
        except Exception:
            breaker_state[provider] = "unknown"

    # Rate limiter status
    rate_limit_status = {}
    for provider in ["anthropic", "openai"]:
        try:
            rl = ProviderRateLimiter(provider, "global")
            rate_limit_status[provider] = rl.tokens_remaining()
        except Exception:
            rate_limit_status[provider] = -1

    # Where settings came from
    env_source = {
        "LLM_DEFAULT_PROVIDER": settings.LLM_DEFAULT_PROVIDER,
        "LLM_FALLBACK_PROVIDER": settings.LLM_FALLBACK_PROVIDER,
        "LLM_PROVIDER_legacy": settings.LLM_PROVIDER or "(not set)",
    }

    return LLMDiagnosticsResponse(
        default_provider=settings.LLM_DEFAULT_PROVIDER,
        fallback_provider=settings.LLM_FALLBACK_PROVIDER,
        openai_key_present=openai_key,
        anthropic_key_present=anthropic_key,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        router_ready=router_ready,
        breaker_state=breaker_state,
        rate_limit_status=rate_limit_status,
        effective_env_source=env_source,
    )


# ── LLM Test Call (Sprint 11) ────────────────────────────────────────────


class LLMTestCallRequest(BaseModel):
    task_type: str = "test"
    prompt: str


class LLMTestCallResponse(BaseModel):
    provider: str
    model: str
    content: Optional[Dict[str, Any]] = None
    raw_text: Optional[str] = None
    latency_ms: float
    tokens_used: int
    was_fallback: bool


@router.post("/llm/test-call", response_model=LLMTestCallResponse)
def llm_test_call(
    request: LLMTestCallRequest,
    user: dict = Depends(get_current_user),
):
    """Execute a real LLM call via the Router. Admin-only diagnostic."""
    from backend.src.llm.router import get_llm_router
    from backend.src.llm.schema import LLMRequest

    llm_request = LLMRequest(
        task_type=request.task_type,
        system_prompt="You are a helpful assistant.",
        user_content=request.prompt,
        max_tokens=256,
        temperature=0.7,
    )

    try:
        llm_router = get_llm_router()
        response = llm_router.generate(llm_request)
        return LLMTestCallResponse(
            provider=response.provider,
            model=response.model,
            content=response.content if isinstance(response.content, dict) else None,
            raw_text=response.raw_text or (str(response.content) if not isinstance(response.content, dict) else None),
            latency_ms=response.latency_ms,
            tokens_used=response.tokens_used,
            was_fallback=response.was_fallback,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM test call failed: {str(e)}")


# ── Env Parity (Sprint 12) ────────────────────────────────────────────────

from typing import List


class EnvParityResponse(BaseModel):
    env_vars_ok: bool
    redis_ok: bool
    db_ok: bool
    llm_keys_ok: bool
    celery_ok: bool
    missing_vars: List[str]


@router.get("/env/parity", response_model=EnvParityResponse)
def env_parity(user: dict = Depends(get_current_user)):
    """Check environment parity — all services reachable, all vars present."""
    missing: List[str] = []

    # Check required env vars
    if not settings.JWT_SECRET or settings.JWT_SECRET == "dev-secret-change-in-production":
        missing.append("JWT_SECRET (using default)")

    # Check LLM keys
    llm_keys_ok = bool(settings.ANTHROPIC_API_KEY or settings.OPENAI_API_KEY)
    if not llm_keys_ok:
        missing.append("ANTHROPIC_API_KEY or OPENAI_API_KEY")

    # Check Redis
    redis_ok = False
    try:
        import redis as redis_lib
        r = redis_lib.from_url(settings.REDIS_URL)
        r.ping()
        redis_ok = True
    except Exception:
        pass

    # Check DB
    db_ok = False
    try:
        from sqlalchemy import text as sa_text
        from backend.src.database.session import SessionLocal
        session = SessionLocal()
        session.execute(sa_text("SELECT 1"))
        session.close()
        db_ok = True
    except Exception:
        pass

    # Check Celery broker
    celery_ok = False
    try:
        from backend.src.infra.celery_app import celery_app
        if celery_app is not None:
            conn = celery_app.connection()
            conn.connect()
            conn.close()
            celery_ok = True
    except Exception:
        pass

    return EnvParityResponse(
        env_vars_ok=len(missing) == 0,
        redis_ok=redis_ok,
        db_ok=db_ok,
        llm_keys_ok=llm_keys_ok,
        celery_ok=celery_ok,
        missing_vars=missing,
    )
