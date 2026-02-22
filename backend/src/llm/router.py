"""
Sprint 9 — BLOQUE C+D: LLM Router with fallback, circuit breaker, retry, and metrics.
Unified entry point for all LLM calls in the system.
"""
import time
import threading

from backend.src.config import settings
from backend.src.llm.schema import LLMRequest, LLMResponse, LLMProviderError
from backend.src.llm.anthropic_provider import AnthropicProvider
from backend.src.llm.openai_provider import OpenAIProvider
from backend.src.providers.circuit_breaker import PersistentCircuitBreaker
from backend.src.utils.resilience import CircuitBreaker, CircuitBreakerOpen
from backend.src.providers.rate_limiter import ProviderRateLimiter
from backend.src.observability.metrics import (
    track_provider_call,
    track_llm_request,
    track_llm_fallback,
    set_circuit_breaker_state,
)
from src.utils.logging_config import logger, get_trace_id


class LLMRouter:
    """Routes LLM requests to primary/fallback providers with resilience."""

    def __init__(self):
        self.providers = {}
        self._circuit_breakers = {}

        if AnthropicProvider.is_configured():
            try:
                self.providers["anthropic"] = AnthropicProvider()
            except Exception as e:
                logger.warning("LLM_ROUTER_INIT | anthropic provider failed: {}", str(e)[:200])

        if OpenAIProvider.is_configured():
            try:
                self.providers["openai"] = OpenAIProvider()
            except Exception as e:
                logger.warning("LLM_ROUTER_INIT | openai provider failed: {}", str(e)[:200])

        logger.info(
            "LLM_ROUTER_INIT | providers={} | default={} | fallback={}",
            list(self.providers.keys()),
            settings.LLM_DEFAULT_PROVIDER,
            settings.LLM_FALLBACK_PROVIDER,
        )

    def _get_circuit_breaker(self, provider_name: str) -> CircuitBreaker:
        """Get or create an in-memory circuit breaker per provider."""
        if provider_name not in self._circuit_breakers:
            self._circuit_breakers[provider_name] = CircuitBreaker(
                failure_threshold=5, cooldown_seconds=60
            )
        return self._circuit_breakers[provider_name]

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Route to primary provider; fallback on failure."""
        primary = settings.LLM_DEFAULT_PROVIDER
        fallback = settings.LLM_FALLBACK_PROVIDER
        trace_id = get_trace_id()

        # Try primary
        if primary in self.providers:
            try:
                return self._call_with_resilience(primary, request)
            except Exception as e:
                logger.bind(trace_id=trace_id).warning(
                    "LLM_PRIMARY_FAILED | provider={} | task_type={} | error={}",
                    primary, request.task_type, str(e)[:200],
                )

        # Try fallback
        if fallback and fallback != primary and fallback in self.providers:
            try:
                response = self._call_with_resilience(fallback, request)
                response.was_fallback = True
                track_llm_fallback(primary, fallback, request.task_type)
                logger.bind(trace_id=trace_id).info(
                    "LLM_FALLBACK | from={} | to={} | task_type={}",
                    primary, fallback, request.task_type,
                )
                return response
            except Exception as e:
                logger.bind(trace_id=trace_id).error(
                    "LLM_FALLBACK_FAILED | provider={} | task_type={} | error={}",
                    fallback, request.task_type, str(e)[:200],
                )

        raise LLMProviderError(
            f"All LLM providers failed for task_type={request.task_type}. "
            f"Tried: primary={primary}, fallback={fallback}"
        )

    def _call_with_resilience(self, provider_name: str, request: LLMRequest) -> LLMResponse:
        """Call a provider with circuit breaker, rate limiter, and timeout."""
        trace_id = get_trace_id()

        # 1. Check persistent circuit breaker (Redis)
        pcb = PersistentCircuitBreaker(provider_name, "global")
        if not pcb.allow_request():
            set_circuit_breaker_state(provider_name, "global", pcb.state)
            raise CircuitBreakerOpen(
                f"Circuit breaker open for provider={provider_name}"
            )

        # 2. Check rate limiter
        limiter = ProviderRateLimiter(provider_name, "global")
        if not limiter.acquire():
            track_llm_request(provider_name, request.task_type, "rate_limited")
            raise LLMProviderError(
                f"Rate limited for provider={provider_name}"
            )

        # 3. Call with in-memory circuit breaker + timeout
        cb = self._get_circuit_breaker(provider_name)
        if not cb.allow_request():
            raise CircuitBreakerOpen(
                f"In-memory circuit breaker open for provider={provider_name}"
            )

        provider = self.providers[provider_name]
        timeout = settings.LLM_TIMEOUT_SECONDS

        t0 = time.monotonic()
        try:
            response = _call_with_timeout(provider.generate, request, timeout)
            latency = time.monotonic() - t0

            # Record success
            cb.record_success()
            pcb.record_success()
            set_circuit_breaker_state(provider_name, "global", "closed")
            track_provider_call(provider_name, "success", latency)
            track_llm_request(provider_name, request.task_type, "success", latency)

            return response

        except Exception as e:
            latency = time.monotonic() - t0

            # Record failure
            cb.record_failure()
            pcb.record_failure()
            set_circuit_breaker_state(provider_name, "global", pcb.state)
            track_provider_call(provider_name, "error", latency)
            track_llm_request(provider_name, request.task_type, "error", latency)

            logger.bind(trace_id=trace_id).warning(
                "LLM_REQUEST_FAILED | provider={} | task_type={} | latency={:.2f}s | error={}",
                provider_name, request.task_type, latency, str(e)[:200],
            )
            raise


def _call_with_timeout(func, request: LLMRequest, timeout_seconds: float) -> LLMResponse:
    """Call a function with a thread-based timeout."""
    result = [None]
    error = [None]

    def target():
        try:
            result[0] = func(request)
        except Exception as e:
            error[0] = e

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        raise TimeoutError(f"LLM call timed out after {timeout_seconds}s")
    if error[0]:
        raise error[0]
    return result[0]


# ── Singleton ────────────────────────────────────────────────────────────────

_router = None
_router_lock = threading.Lock()


def get_llm_router() -> LLMRouter:
    """Get or create the global LLM router singleton."""
    global _router
    if _router is None:
        with _router_lock:
            if _router is None:
                _router = LLMRouter()
    return _router


def reset_llm_router():
    """Reset the singleton (for testing)."""
    global _router
    _router = None
