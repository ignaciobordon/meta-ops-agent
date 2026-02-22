"""
Sprint 9 — LLM Router Integration Tests
Verifies that engines (BrandMapBuilder, Factory, Scorer) correctly integrate
with the LLM Router, and that config, metrics, and end-to-end mock flows work.

All tests use unittest.mock — no real API calls are made.
"""
import json
import pytest
from unittest.mock import patch, MagicMock

from backend.src.llm.schema import LLMRequest, LLMResponse, LLMProviderError
from backend.src.llm.router import reset_llm_router


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

VALID_BRAND_MAP_CONTENT = {
    "core_identity": {
        "mission": "Test",
        "values": ["v1"],
        "tone_voice": "casual",
        "personality_traits": ["bold"],
    },
    "offer_layer": {
        "main_product": "Widget",
        "upsells": ["Pro"],
        "pricing_psychology": "anchoring",
        "risk_reversal": "30-day guarantee",
    },
    "audience_model": [
        {
            "avatar_name": "User",
            "demographics": "25-35",
            "psychographics": "tech-savvy",
            "pains": ["slow"],
            "desires": ["fast"],
            "triggers": ["demo"],
        }
    ],
    "differentiation_layer": {
        "usp": "Fastest",
        "competitive_moat": "tech",
        "proof_points": ["10x"],
    },
    "narrative_assets": {
        "lore": "Founded in garage",
        "story_hooks": ["origin"],
        "core_myths": ["innovation"],
    },
    "creative_dna": {
        "color_palette": ["#FF0000"],
        "typography_intent": "modern",
        "visual_constraints": ["no stock"],
    },
    "market_context": {
        "seasonal_factors": ["summer"],
        "current_trends": ["AI"],
    },
    "competitor_map": [
        {"name": "Rival", "strategy_type": "price", "weak_points": ["slow"]}
    ],
    "opportunity_map": [
        {"gap_id": "OPP-001", "strategy_recommendation": "Speed campaign"}
    ],
}

VALID_SCORING_CONTENT = {
    "hook_strength": {"score": 7.5, "reasoning": "Good hook"},
    "brand_alignment": {"score": 8.0, "reasoning": "On brand"},
    "clarity": {"score": 7.0, "reasoning": "Clear"},
    "audience_fit": {"score": 6.5, "reasoning": "Decent"},
    "cta_quality": {"score": 7.0, "reasoning": "Actionable"},
    "overall_reasoning": "Good creative overall",
}

VALID_FACTORY_CONTENT = {
    "scripts": [
        {
            "hook": "Hey!",
            "body": "Try this",
            "cta": "Buy now",
            "framework": "PAS",
            "target_avatar": "User",
            "visual_brief": "Video of product",
        }
    ]
}


def _make_brand_map_mock():
    """Return a MagicMock that looks like a BrandMap for Factory / Scorer."""
    bm = MagicMock()
    bm.metadata.hash = "abc123"
    bm.core_identity.mission = "Test"
    bm.core_identity.tone_voice = "casual"
    bm.core_identity.personality_traits = ["bold"]
    bm.differentiation_layer.usp = "Fastest"
    bm.offer_layer.main_product = "Widget"
    bm.offer_layer.risk_reversal = "30-day guarantee"
    bm.creative_dna.color_palette = ["#FF0000"]
    bm.creative_dna.typography_intent = "modern"
    bm.creative_dna.visual_constraints = ["no stock"]

    avatar = MagicMock()
    avatar.avatar_name = "User"
    avatar.demographics = "25-35"
    avatar.pains = ["slow"]
    avatar.desires = ["fast"]
    bm.audience_model = [avatar]

    return bm


# ===========================================================================
# 1. BrandMapBuilder uses LLM Router
# ===========================================================================


@patch("src.engines.brand_map.builder.VectorDBClient")
@patch("src.engines.brand_map.builder.get_llm_router")
def test_builder_uses_llm_router(mock_get_router, mock_vector_db):
    """BrandMapBuilder.build() should call router.generate() with task_type='brand_map'."""
    try:
        mock_router = MagicMock()
        mock_router.generate.return_value = LLMResponse(
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            content=VALID_BRAND_MAP_CONTENT,
        )
        mock_get_router.return_value = mock_router

        from src.engines.brand_map.builder import BrandMapBuilder

        builder = BrandMapBuilder()
        result = builder.build("test brand text")

        # Verify router.generate() was called
        mock_router.generate.assert_called_once()

        # Verify the request had the correct task_type
        call_args = mock_router.generate.call_args
        request = call_args[0][0]
        assert isinstance(request, LLMRequest)
        assert request.task_type == "brand_map"

        # Verify a BrandMap was returned
        assert result.core_identity.mission == "Test"
    finally:
        reset_llm_router()


# ===========================================================================
# 2. Factory uses LLM Router
# ===========================================================================


@patch("src.engines.factory.factory.get_llm_router")
def test_factory_uses_llm_router(mock_get_router):
    """Factory.generate_scripts() should call router.generate() with task_type='creative_factory'."""
    try:
        mock_router = MagicMock()
        mock_router.generate.return_value = LLMResponse(
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            content=VALID_FACTORY_CONTENT,
        )
        mock_get_router.return_value = mock_router

        brand_map_mock = _make_brand_map_mock()

        from src.engines.factory.factory import Factory

        factory = Factory()
        scripts = factory.generate_scripts(
            brand_map=brand_map_mock,
            target_angles=["Social Proof"],
            num_variants=1,
        )

        # Verify router.generate() was called
        mock_router.generate.assert_called_once()

        # Verify the request had the correct task_type
        call_args = mock_router.generate.call_args
        request = call_args[0][0]
        assert isinstance(request, LLMRequest)
        assert request.task_type == "creative_factory"

        # Verify scripts were produced
        assert len(scripts) == 1
        assert scripts[0].hook == "Hey!"
        assert scripts[0].cta == "Buy now"
    finally:
        reset_llm_router()


# ===========================================================================
# 3. Scorer uses LLM Router
# ===========================================================================


@patch("src.engines.scoring.scorer.get_llm_router")
def test_scorer_uses_llm_router(mock_get_router):
    """Scorer.evaluate() should call router.generate() with task_type='scoring'."""
    try:
        mock_router = MagicMock()
        mock_router.generate.return_value = LLMResponse(
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            content=VALID_SCORING_CONTENT,
        )
        mock_get_router.return_value = mock_router

        brand_map_mock = _make_brand_map_mock()

        from src.engines.scoring.scorer import Scorer

        scorer = Scorer()
        result = scorer.evaluate("test ad copy", brand_map_mock)

        # Verify router.generate() was called
        mock_router.generate.assert_called_once()

        # Verify the request had the correct task_type
        call_args = mock_router.generate.call_args
        request = call_args[0][0]
        assert isinstance(request, LLMRequest)
        assert request.task_type == "scoring"

        # Verify the evaluation result
        assert result.hook_strength.score == 7.5
        assert result.brand_alignment.score == 8.0
        assert result.overall_reasoning == "Good creative overall"
    finally:
        reset_llm_router()


# ===========================================================================
# 4. BrandMapBuilder handles LLMProviderError
# ===========================================================================


@patch("src.engines.brand_map.builder.VectorDBClient")
@patch("src.engines.brand_map.builder.get_llm_router")
def test_builder_handles_provider_error(mock_get_router, mock_vector_db):
    """BrandMapBuilder.build() should propagate LLMProviderError when all providers fail."""
    try:
        mock_router = MagicMock()
        mock_router.generate.side_effect = LLMProviderError(
            "All LLM providers failed for task_type=brand_map"
        )
        mock_get_router.return_value = mock_router

        from src.engines.brand_map.builder import BrandMapBuilder

        builder = BrandMapBuilder()

        with pytest.raises(LLMProviderError):
            builder.build("text")
    finally:
        reset_llm_router()


# ===========================================================================
# 5. Factory handles fallback response
# ===========================================================================


@patch("src.engines.factory.factory.get_llm_router")
def test_factory_handles_fallback_response(mock_get_router):
    """Factory should still produce AdScript objects when the response comes from fallback."""
    try:
        mock_router = MagicMock()
        mock_router.generate.return_value = LLMResponse(
            provider="openai",
            model="gpt-4o-2024-08-06",
            content=VALID_FACTORY_CONTENT,
            was_fallback=True,
        )
        mock_get_router.return_value = mock_router

        brand_map_mock = _make_brand_map_mock()

        from src.engines.factory.factory import Factory

        factory = Factory()
        scripts = factory.generate_scripts(
            brand_map=brand_map_mock,
            target_angles=["Social Proof"],
            num_variants=1,
        )

        # Even though was_fallback=True, scripts should be produced normally
        assert len(scripts) == 1
        assert scripts[0].hook == "Hey!"
        assert scripts[0].body == "Try this"
        assert scripts[0].cta == "Buy now"
        assert scripts[0].framework == "PAS"
        assert scripts[0].target_avatar == "User"
    finally:
        reset_llm_router()


# ===========================================================================
# 6. Config LLM settings have correct defaults
# ===========================================================================


def test_config_llm_settings():
    """Settings should expose LLM_DEFAULT_PROVIDER, LLM_FALLBACK_PROVIDER, LLM_TIMEOUT_SECONDS."""
    from backend.src.config import settings

    assert hasattr(settings, "LLM_DEFAULT_PROVIDER")
    assert hasattr(settings, "LLM_FALLBACK_PROVIDER")
    assert hasattr(settings, "LLM_TIMEOUT_SECONDS")

    assert settings.LLM_DEFAULT_PROVIDER == "anthropic"
    assert settings.LLM_FALLBACK_PROVIDER == "openai"
    assert settings.LLM_TIMEOUT_SECONDS >= 30  # default 30, may be higher via .env


# ===========================================================================
# 7. Metrics increment on LLM call
# ===========================================================================


@patch("backend.src.observability.metrics.metrics")
def test_metrics_increment_on_llm_call(mock_metrics):
    """track_llm_request should increment llm_requests_total counter with correct labels."""
    from backend.src.observability.metrics import track_llm_request

    track_llm_request("anthropic", "scoring", "success", 1.5)

    mock_metrics.llm_requests_total.labels.assert_called_once_with(
        provider="anthropic", task_type="scoring", status="success"
    )
    mock_metrics.llm_requests_total.labels().inc.assert_called_once()

    # Latency > 0, so observe should also be called
    mock_metrics.llm_latency_seconds.labels.assert_called_once_with(
        provider="anthropic", task_type="scoring"
    )
    mock_metrics.llm_latency_seconds.labels().observe.assert_called_once_with(1.5)


# ===========================================================================
# 8. Router-to-Provider end-to-end mock flow
# ===========================================================================


@patch("backend.src.llm.router.PersistentCircuitBreaker")
@patch("backend.src.llm.router.ProviderRateLimiter")
@patch("backend.src.llm.router.track_provider_call")
@patch("backend.src.llm.router.track_llm_request")
@patch("backend.src.llm.router.set_circuit_breaker_state")
@patch("backend.src.llm.router.settings")
@patch("backend.src.llm.router.AnthropicProvider")
@patch("backend.src.llm.router.OpenAIProvider")
def test_router_to_provider_e2e_mock(
    mock_openai_cls,
    mock_anthropic_cls,
    mock_settings,
    mock_set_cb_state,
    mock_track_llm,
    mock_track_provider,
    mock_rate_limiter_cls,
    mock_pcb_cls,
):
    """Full mock flow: LLMRouter -> AnthropicProvider -> mock SDK -> LLMResponse."""
    try:
        # Configure settings
        mock_settings.LLM_DEFAULT_PROVIDER = "anthropic"
        mock_settings.LLM_FALLBACK_PROVIDER = "openai"
        mock_settings.LLM_TIMEOUT_SECONDS = 30

        # Configure AnthropicProvider as available
        mock_anthropic_cls.is_configured.return_value = True
        mock_openai_cls.is_configured.return_value = False

        # Create a mock provider instance that returns an LLMResponse
        mock_provider_instance = MagicMock()
        expected_response = LLMResponse(
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            content={"result": "mock data"},
            latency_ms=150.0,
            tokens_used=500,
        )
        mock_provider_instance.generate.return_value = expected_response
        mock_anthropic_cls.return_value = mock_provider_instance

        # Allow circuit breaker and rate limiter
        mock_pcb_instance = MagicMock()
        mock_pcb_instance.allow_request.return_value = True
        mock_pcb_instance.state = "closed"
        mock_pcb_cls.return_value = mock_pcb_instance

        mock_rl_instance = MagicMock()
        mock_rl_instance.acquire.return_value = True
        mock_rate_limiter_cls.return_value = mock_rl_instance

        # Create the router (uses mocked classes)
        from backend.src.llm.router import LLMRouter

        router = LLMRouter()

        # Verify anthropic provider was registered
        assert "anthropic" in router.providers

        # Make a request
        request = LLMRequest(
            task_type="scoring",
            system_prompt="Test prompt",
            user_content="Test content",
        )
        response = router.generate(request)

        # Verify the response flowed through correctly
        assert response.provider == "anthropic"
        assert response.model == "claude-haiku-4-5-20251001"
        assert response.content == {"result": "mock data"}
        assert response.tokens_used == 500

        # Verify the provider's generate was called with the request
        mock_provider_instance.generate.assert_called_once_with(request)

        # Verify metrics were tracked
        mock_track_provider.assert_called_once()
        mock_track_llm.assert_called_once()
    finally:
        reset_llm_router()
