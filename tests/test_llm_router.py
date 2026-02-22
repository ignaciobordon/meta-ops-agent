"""
Sprint 9 -- LLM Router Tests
Tests for LLMRouter: provider init, generate with primary/fallback,
circuit breaker integration, rate limiter, metrics tracking, and singleton.
"""
import os
import pytest
from unittest.mock import patch, MagicMock, ANY

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.src.llm.router import LLMRouter, get_llm_router, reset_llm_router
from backend.src.llm.schema import LLMRequest, LLMResponse, LLMProviderError


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_request() -> LLMRequest:
    return LLMRequest(task_type="scoring", system_prompt="test", user_content="test")


def _make_response(provider: str = "anthropic") -> LLMResponse:
    return LLMResponse(
        provider=provider,
        model="test",
        content={"key": "value"},
        latency_ms=100,
        tokens_used=50,
    )


def _build_router(providers: dict, circuit_breakers: dict | None = None) -> LLMRouter:
    """Build an LLMRouter without calling __init__, injecting mock providers."""
    router = LLMRouter.__new__(LLMRouter)
    router.providers = providers
    router._circuit_breakers = circuit_breakers or {}
    return router


# ── 1. Router init with available providers ──────────────────────────────────


@patch("backend.src.llm.router.OpenAIProvider")
@patch("backend.src.llm.router.AnthropicProvider")
def test_router_init_with_available_providers(mock_anthropic_cls, mock_openai_cls):
    """When both providers are configured, router.providers has both keys."""
    mock_anthropic_cls.is_configured.return_value = True
    mock_openai_cls.is_configured.return_value = True
    mock_anthropic_cls.return_value = MagicMock()
    mock_openai_cls.return_value = MagicMock()

    router = LLMRouter()

    assert "anthropic" in router.providers
    assert "openai" in router.providers
    assert len(router.providers) == 2


# ── 2. Router init with no providers ─────────────────────────────────────────


@patch("backend.src.llm.router.OpenAIProvider")
@patch("backend.src.llm.router.AnthropicProvider")
def test_router_init_no_providers(mock_anthropic_cls, mock_openai_cls):
    """When no providers are configured, router.providers is empty."""
    mock_anthropic_cls.is_configured.return_value = False
    mock_openai_cls.is_configured.return_value = False

    router = LLMRouter()

    assert router.providers == {}


# ── 3. Generate calls primary provider ───────────────────────────────────────


@patch("backend.src.llm.router.ProviderRateLimiter")
@patch("backend.src.llm.router.PersistentCircuitBreaker")
@patch("backend.src.llm.router.settings")
def test_router_generate_calls_primary(mock_settings, mock_pcb_cls, mock_limiter_cls):
    """generate() calls the primary provider and returns its response."""
    mock_settings.LLM_DEFAULT_PROVIDER = "anthropic"
    mock_settings.LLM_FALLBACK_PROVIDER = "openai"
    mock_settings.LLM_TIMEOUT_SECONDS = 30

    # PersistentCircuitBreaker allows requests and records success
    mock_pcb = MagicMock()
    mock_pcb.allow_request.return_value = True
    mock_pcb.state = "closed"
    mock_pcb_cls.return_value = mock_pcb

    # RateLimiter allows requests
    mock_limiter = MagicMock()
    mock_limiter.acquire.return_value = True
    mock_limiter_cls.return_value = mock_limiter

    expected_response = _make_response("anthropic")
    mock_provider = MagicMock()
    mock_provider.generate.return_value = expected_response

    router = _build_router({"anthropic": mock_provider})
    request = _make_request()

    response = router.generate(request)

    mock_provider.generate.assert_called_once_with(request)
    assert response.provider == "anthropic"
    assert response.content == {"key": "value"}


# ── 4. Fallback on primary failure ───────────────────────────────────────────


@patch("backend.src.llm.router.ProviderRateLimiter")
@patch("backend.src.llm.router.PersistentCircuitBreaker")
@patch("backend.src.llm.router.settings")
def test_router_fallback_on_primary_failure(mock_settings, mock_pcb_cls, mock_limiter_cls):
    """When primary provider fails, fallback is used and was_fallback=True."""
    mock_settings.LLM_DEFAULT_PROVIDER = "anthropic"
    mock_settings.LLM_FALLBACK_PROVIDER = "openai"
    mock_settings.LLM_TIMEOUT_SECONDS = 30

    mock_pcb = MagicMock()
    mock_pcb.allow_request.return_value = True
    mock_pcb.state = "closed"
    mock_pcb_cls.return_value = mock_pcb

    mock_limiter = MagicMock()
    mock_limiter.acquire.return_value = True
    mock_limiter_cls.return_value = mock_limiter

    mock_primary = MagicMock()
    mock_primary.generate.side_effect = Exception("anthropic down")

    fallback_response = _make_response("openai")
    mock_fallback = MagicMock()
    mock_fallback.generate.return_value = fallback_response

    router = _build_router({"anthropic": mock_primary, "openai": mock_fallback})
    request = _make_request()

    response = router.generate(request)

    mock_fallback.generate.assert_called_once_with(request)
    assert response.was_fallback is True
    assert response.provider == "openai"


# ── 5. Raises when all providers fail ────────────────────────────────────────


@patch("backend.src.llm.router.ProviderRateLimiter")
@patch("backend.src.llm.router.PersistentCircuitBreaker")
@patch("backend.src.llm.router.settings")
def test_router_raises_when_all_fail(mock_settings, mock_pcb_cls, mock_limiter_cls):
    """When both primary and fallback fail, LLMProviderError is raised."""
    mock_settings.LLM_DEFAULT_PROVIDER = "anthropic"
    mock_settings.LLM_FALLBACK_PROVIDER = "openai"
    mock_settings.LLM_TIMEOUT_SECONDS = 30

    mock_pcb = MagicMock()
    mock_pcb.allow_request.return_value = True
    mock_pcb.state = "closed"
    mock_pcb_cls.return_value = mock_pcb

    mock_limiter = MagicMock()
    mock_limiter.acquire.return_value = True
    mock_limiter_cls.return_value = mock_limiter

    mock_primary = MagicMock()
    mock_primary.generate.side_effect = Exception("anthropic down")

    mock_fallback = MagicMock()
    mock_fallback.generate.side_effect = Exception("openai down")

    router = _build_router({"anthropic": mock_primary, "openai": mock_fallback})
    request = _make_request()

    with pytest.raises(LLMProviderError, match="All LLM providers failed"):
        router.generate(request)


# ── 6. Respects circuit breaker open ─────────────────────────────────────────


@patch("backend.src.llm.router.ProviderRateLimiter")
@patch("backend.src.llm.router.PersistentCircuitBreaker")
@patch("backend.src.llm.router.settings")
def test_router_respects_circuit_breaker_open(mock_settings, mock_pcb_cls, mock_limiter_cls):
    """When the persistent circuit breaker is open for primary, router falls back or raises."""
    mock_settings.LLM_DEFAULT_PROVIDER = "anthropic"
    mock_settings.LLM_FALLBACK_PROVIDER = "openai"
    mock_settings.LLM_TIMEOUT_SECONDS = 30

    def pcb_factory(provider_name, _org_id):
        mock_pcb = MagicMock()
        if provider_name == "anthropic":
            # Primary circuit breaker is OPEN
            mock_pcb.allow_request.return_value = False
            mock_pcb.state = "open"
        else:
            # Fallback circuit breaker is CLOSED
            mock_pcb.allow_request.return_value = True
            mock_pcb.state = "closed"
        return mock_pcb

    mock_pcb_cls.side_effect = pcb_factory

    mock_limiter = MagicMock()
    mock_limiter.acquire.return_value = True
    mock_limiter_cls.return_value = mock_limiter

    mock_primary = MagicMock()
    mock_primary.generate.return_value = _make_response("anthropic")

    fallback_response = _make_response("openai")
    mock_fallback = MagicMock()
    mock_fallback.generate.return_value = fallback_response

    router = _build_router({"anthropic": mock_primary, "openai": mock_fallback})
    request = _make_request()

    response = router.generate(request)

    # Primary should NOT have been called (circuit breaker open)
    mock_primary.generate.assert_not_called()
    # Fallback should have been called
    mock_fallback.generate.assert_called_once_with(request)
    assert response.was_fallback is True


# ── 7. Records circuit breaker success ───────────────────────────────────────


@patch("backend.src.llm.router.ProviderRateLimiter")
@patch("backend.src.llm.router.PersistentCircuitBreaker")
@patch("backend.src.llm.router.settings")
def test_router_records_circuit_breaker_success(mock_settings, mock_pcb_cls, mock_limiter_cls):
    """On successful generate, the persistent circuit breaker record_success() is called."""
    mock_settings.LLM_DEFAULT_PROVIDER = "anthropic"
    mock_settings.LLM_FALLBACK_PROVIDER = "openai"
    mock_settings.LLM_TIMEOUT_SECONDS = 30

    mock_pcb = MagicMock()
    mock_pcb.allow_request.return_value = True
    mock_pcb.state = "closed"
    mock_pcb_cls.return_value = mock_pcb

    mock_limiter = MagicMock()
    mock_limiter.acquire.return_value = True
    mock_limiter_cls.return_value = mock_limiter

    mock_provider = MagicMock()
    mock_provider.generate.return_value = _make_response("anthropic")

    router = _build_router({"anthropic": mock_provider})
    request = _make_request()

    router.generate(request)

    mock_pcb.record_success.assert_called_once()


# ── 8. Tracks metrics on success ─────────────────────────────────────────────


@patch("backend.src.llm.router.track_llm_request")
@patch("backend.src.llm.router.ProviderRateLimiter")
@patch("backend.src.llm.router.PersistentCircuitBreaker")
@patch("backend.src.llm.router.settings")
def test_router_tracks_metrics_on_success(
    mock_settings, mock_pcb_cls, mock_limiter_cls, mock_track_llm_request
):
    """On success, track_llm_request is called with provider, task_type, 'success', and latency."""
    mock_settings.LLM_DEFAULT_PROVIDER = "anthropic"
    mock_settings.LLM_FALLBACK_PROVIDER = "openai"
    mock_settings.LLM_TIMEOUT_SECONDS = 30

    mock_pcb = MagicMock()
    mock_pcb.allow_request.return_value = True
    mock_pcb.state = "closed"
    mock_pcb_cls.return_value = mock_pcb

    mock_limiter = MagicMock()
    mock_limiter.acquire.return_value = True
    mock_limiter_cls.return_value = mock_limiter

    mock_provider = MagicMock()
    mock_provider.generate.return_value = _make_response("anthropic")

    router = _build_router({"anthropic": mock_provider})
    request = _make_request()

    router.generate(request)

    mock_track_llm_request.assert_called_with("anthropic", "scoring", "success", ANY)


# ── 9. Tracks metrics on failure ─────────────────────────────────────────────


@patch("backend.src.llm.router.track_llm_request")
@patch("backend.src.llm.router.ProviderRateLimiter")
@patch("backend.src.llm.router.PersistentCircuitBreaker")
@patch("backend.src.llm.router.settings")
def test_router_tracks_metrics_on_failure(
    mock_settings, mock_pcb_cls, mock_limiter_cls, mock_track_llm_request
):
    """On provider failure, track_llm_request is called with 'error' status."""
    mock_settings.LLM_DEFAULT_PROVIDER = "anthropic"
    mock_settings.LLM_FALLBACK_PROVIDER = ""
    mock_settings.LLM_TIMEOUT_SECONDS = 30

    mock_pcb = MagicMock()
    mock_pcb.allow_request.return_value = True
    mock_pcb.state = "closed"
    mock_pcb_cls.return_value = mock_pcb

    mock_limiter = MagicMock()
    mock_limiter.acquire.return_value = True
    mock_limiter_cls.return_value = mock_limiter

    mock_provider = MagicMock()
    mock_provider.generate.side_effect = Exception("provider down")

    router = _build_router({"anthropic": mock_provider})
    request = _make_request()

    with pytest.raises(LLMProviderError):
        router.generate(request)

    mock_track_llm_request.assert_called_with("anthropic", "scoring", "error", ANY)


# ── 10. Tracks fallback metrics ──────────────────────────────────────────────


@patch("backend.src.llm.router.track_llm_fallback")
@patch("backend.src.llm.router.ProviderRateLimiter")
@patch("backend.src.llm.router.PersistentCircuitBreaker")
@patch("backend.src.llm.router.settings")
def test_router_tracks_fallback_metrics(
    mock_settings, mock_pcb_cls, mock_limiter_cls, mock_track_fallback
):
    """When fallback is used, track_llm_fallback is called with from/to providers."""
    mock_settings.LLM_DEFAULT_PROVIDER = "anthropic"
    mock_settings.LLM_FALLBACK_PROVIDER = "openai"
    mock_settings.LLM_TIMEOUT_SECONDS = 30

    mock_pcb = MagicMock()
    mock_pcb.allow_request.return_value = True
    mock_pcb.state = "closed"
    mock_pcb_cls.return_value = mock_pcb

    mock_limiter = MagicMock()
    mock_limiter.acquire.return_value = True
    mock_limiter_cls.return_value = mock_limiter

    mock_primary = MagicMock()
    mock_primary.generate.side_effect = Exception("anthropic down")

    mock_fallback = MagicMock()
    mock_fallback.generate.return_value = _make_response("openai")

    router = _build_router({"anthropic": mock_primary, "openai": mock_fallback})
    request = _make_request()

    router.generate(request)

    mock_track_fallback.assert_called_once_with("anthropic", "openai", "scoring")


# ── 11. Checks rate limiter ──────────────────────────────────────────────────


@patch("backend.src.llm.router.ProviderRateLimiter")
@patch("backend.src.llm.router.PersistentCircuitBreaker")
@patch("backend.src.llm.router.settings")
def test_router_checks_rate_limiter(mock_settings, mock_pcb_cls, mock_limiter_cls):
    """When rate limiter denies, LLMProviderError is raised with rate limit message."""
    mock_settings.LLM_DEFAULT_PROVIDER = "anthropic"
    mock_settings.LLM_FALLBACK_PROVIDER = ""
    mock_settings.LLM_TIMEOUT_SECONDS = 30

    mock_pcb = MagicMock()
    mock_pcb.allow_request.return_value = True
    mock_pcb.state = "closed"
    mock_pcb_cls.return_value = mock_pcb

    mock_limiter = MagicMock()
    mock_limiter.acquire.return_value = False
    mock_limiter_cls.return_value = mock_limiter

    mock_provider = MagicMock()
    mock_provider.generate.return_value = _make_response("anthropic")

    router = _build_router({"anthropic": mock_provider})
    request = _make_request()

    with pytest.raises(LLMProviderError, match="All LLM providers failed"):
        router.generate(request)

    # The provider's generate should never be called (blocked by rate limiter)
    mock_provider.generate.assert_not_called()


# ── 12. Singleton get_llm_router / reset_llm_router ─────────────────────────


@patch("backend.src.llm.router.OpenAIProvider")
@patch("backend.src.llm.router.AnthropicProvider")
def test_get_llm_router_singleton(mock_anthropic_cls, mock_openai_cls):
    """get_llm_router() returns the same instance; reset_llm_router() clears it."""
    mock_anthropic_cls.is_configured.return_value = False
    mock_openai_cls.is_configured.return_value = False

    try:
        # Ensure clean state
        reset_llm_router()

        router_a = get_llm_router()
        router_b = get_llm_router()

        assert router_a is router_b, "get_llm_router() must return the same singleton"

        # Reset and verify a new instance is created
        reset_llm_router()
        router_c = get_llm_router()

        assert router_c is not router_a, "After reset, a new instance must be created"
    finally:
        reset_llm_router()
