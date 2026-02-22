"""
Unit tests for LLM provider abstraction (Sprint 9 — BLOQUE B).
Tests AnthropicProvider, OpenAIProvider, schema dataclasses,
tool conversion, and response extraction logic.
"""
import json
from unittest.mock import patch, MagicMock

import pytest

from backend.src.llm.schema import LLMRequest, LLMResponse, LLMProviderError


# ── 1. AnthropicProvider.is_configured() returns True when key is set ────────

@patch("backend.src.llm.anthropic_provider.settings")
def test_anthropic_is_configured_true(mock_settings):
    """is_configured() returns True when ANTHROPIC_API_KEY is non-empty."""
    mock_settings.ANTHROPIC_API_KEY = "sk-test"

    from backend.src.llm.anthropic_provider import AnthropicProvider

    assert AnthropicProvider.is_configured() is True


# ── 2. AnthropicProvider.is_configured() returns False when key is empty ─────

@patch("backend.src.llm.anthropic_provider.settings")
def test_anthropic_is_configured_false(mock_settings):
    """is_configured() returns False when ANTHROPIC_API_KEY is empty."""
    mock_settings.ANTHROPIC_API_KEY = ""

    from backend.src.llm.anthropic_provider import AnthropicProvider

    assert AnthropicProvider.is_configured() is False


# ── 3. OpenAIProvider.is_configured() returns True when key is set ───────────

@patch("backend.src.llm.openai_provider.settings")
def test_openai_is_configured_true(mock_settings):
    """is_configured() returns True when OPENAI_API_KEY is non-empty."""
    mock_settings.OPENAI_API_KEY = "sk-test"

    from backend.src.llm.openai_provider import OpenAIProvider

    assert OpenAIProvider.is_configured() is True


# ── 4. OpenAIProvider.is_configured() returns False when key is empty ────────

@patch("backend.src.llm.openai_provider.settings")
def test_openai_is_configured_false(mock_settings):
    """is_configured() returns False when OPENAI_API_KEY is empty."""
    mock_settings.OPENAI_API_KEY = ""

    from backend.src.llm.openai_provider import OpenAIProvider

    assert OpenAIProvider.is_configured() is False


# ── 5. AnthropicProvider.generate() with tool_use block ──────────────────────

@patch("backend.src.llm.anthropic_provider.Anthropic")
@patch("backend.src.llm.anthropic_provider.settings")
def test_anthropic_generate_with_tool_use(mock_settings, MockAnthropic):
    """generate() extracts content from a tool_use block and populates LLMResponse."""
    mock_settings.ANTHROPIC_API_KEY = "sk-test"

    # Build mock tool_use content block
    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.input = {"key": "value"}

    # Build mock usage
    mock_usage = MagicMock()
    mock_usage.input_tokens = 10
    mock_usage.output_tokens = 20

    # Build mock response
    mock_response = MagicMock()
    mock_response.content = [tool_use_block]
    mock_response.usage = mock_usage

    # Wire mock client
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    MockAnthropic.return_value = mock_client

    from backend.src.llm.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider()
    request = LLMRequest(
        task_type="brand_map",
        system_prompt="You are a helpful assistant.",
        user_content="Analyze this brand.",
        tools=[{"type": "function", "function": {"name": "foo", "description": "bar", "parameters": {"type": "object"}}}],
    )

    result = provider.generate(request)

    assert result.provider == "anthropic"
    assert result.content == {"key": "value"}
    assert result.latency_ms >= 0
    assert result.tokens_used == 30  # 10 + 20
    assert result.raw_text is None


# ── 6. OpenAIProvider.generate() with tool_calls ─────────────────────────────

@patch("backend.src.llm.openai_provider.OpenAI")
@patch("backend.src.llm.openai_provider.settings")
def test_openai_generate_with_tool_calls(mock_settings, MockOpenAI):
    """generate() extracts content from tool_calls and populates LLMResponse."""
    mock_settings.OPENAI_API_KEY = "sk-test"

    # Build mock tool call
    mock_function = MagicMock()
    mock_function.arguments = '{"key": "value"}'

    mock_tool_call = MagicMock()
    mock_tool_call.function = mock_function

    # Build mock message
    mock_message = MagicMock()
    mock_message.tool_calls = [mock_tool_call]

    # Build mock choice
    mock_choice = MagicMock()
    mock_choice.message = mock_message

    # Build mock usage
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 10
    mock_usage.completion_tokens = 20

    # Build mock response
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    # Wire mock client
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    MockOpenAI.return_value = mock_client

    from backend.src.llm.openai_provider import OpenAIProvider

    provider = OpenAIProvider()
    request = LLMRequest(
        task_type="scoring",
        system_prompt="Score this creative.",
        user_content="Creative data here.",
        tools=[{"type": "function", "function": {"name": "score", "description": "Score", "parameters": {"type": "object"}}}],
    )

    result = provider.generate(request)

    assert result.provider == "openai"
    assert result.content == {"key": "value"}
    assert result.latency_ms >= 0
    assert result.tokens_used == 30  # 10 + 20
    assert result.raw_text is None


# ── 7. _convert_tools_to_anthropic converts OpenAI tool format ───────────────

def test_anthropic_converts_openai_tools():
    """_convert_tools_to_anthropic transforms OpenAI-format tools to Anthropic format."""
    from backend.src.llm.anthropic_provider import _convert_tools_to_anthropic

    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": "foo",
                "description": "bar",
                "parameters": {"type": "object"},
            },
        }
    ]

    result = _convert_tools_to_anthropic(openai_tools)

    assert len(result) == 1
    assert result[0] == {
        "name": "foo",
        "description": "bar",
        "input_schema": {"type": "object"},
    }


# ── 8. OpenAIProvider extracts tool_calls arguments dict ─────────────────────

@patch("backend.src.llm.openai_provider.OpenAI")
@patch("backend.src.llm.openai_provider.settings")
def test_openai_extracts_tool_calls_arguments(mock_settings, MockOpenAI):
    """generate() correctly parses JSON from tool_calls[0].function.arguments."""
    mock_settings.OPENAI_API_KEY = "sk-test"

    mock_function = MagicMock()
    mock_function.arguments = '{"key": "value"}'

    mock_tool_call = MagicMock()
    mock_tool_call.function = mock_function

    mock_message = MagicMock()
    mock_message.tool_calls = [mock_tool_call]

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 5
    mock_usage.completion_tokens = 15

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    MockOpenAI.return_value = mock_client

    from backend.src.llm.openai_provider import OpenAIProvider

    provider = OpenAIProvider()
    request = LLMRequest(
        task_type="brand_map",
        system_prompt="Prompt.",
        user_content="Content.",
    )

    result = provider.generate(request)

    assert isinstance(result.content, dict)
    assert result.content == {"key": "value"}
    assert result.raw_text is None


# ── 9. OpenAIProvider falls back to JSON in message.content ──────────────────

@patch("backend.src.llm.openai_provider.OpenAI")
@patch("backend.src.llm.openai_provider.settings")
def test_openai_falls_back_to_json_content(mock_settings, MockOpenAI):
    """When no tool_calls, generate() parses JSON from message.content."""
    mock_settings.OPENAI_API_KEY = "sk-test"

    mock_message = MagicMock()
    mock_message.tool_calls = None  # No tool calls
    mock_message.content = '{"result": 42}'

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 8
    mock_usage.completion_tokens = 12

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    MockOpenAI.return_value = mock_client

    from backend.src.llm.openai_provider import OpenAIProvider

    provider = OpenAIProvider()
    request = LLMRequest(
        task_type="creative_factory",
        system_prompt="Generate creative.",
        user_content="Brand data.",
    )

    result = provider.generate(request)

    assert result.content == {"result": 42}
    assert result.raw_text == '{"result": 42}'


# ── 10. AnthropicProvider falls back when no tool_use block ──────────────────

@patch("backend.src.llm.anthropic_provider.Anthropic")
@patch("backend.src.llm.anthropic_provider.settings")
def test_anthropic_no_tool_use_block_falls_back(mock_settings, MockAnthropic):
    """When response has only text blocks, generate() parses JSON from text."""
    mock_settings.ANTHROPIC_API_KEY = "sk-test"

    # Build a text-only content block (no tool_use)
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = '{"fallback": true}'

    mock_usage = MagicMock()
    mock_usage.input_tokens = 5
    mock_usage.output_tokens = 10

    mock_response = MagicMock()
    mock_response.content = [text_block]
    mock_response.usage = mock_usage

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    MockAnthropic.return_value = mock_client

    from backend.src.llm.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider()
    request = LLMRequest(
        task_type="scoring",
        system_prompt="Score this.",
        user_content="Data.",
    )

    result = provider.generate(request)

    assert result.content == {"fallback": True}
    assert result.raw_text == '{"fallback": true}'


# ── 11. LLMRequest dataclass stores all fields correctly ─────────────────────

def test_llm_request_dataclass():
    """LLMRequest dataclass stores all provided fields and uses defaults."""
    tools = [{"type": "function", "function": {"name": "t", "description": "d", "parameters": {}}}]
    tool_choice = {"type": "function", "function": {"name": "t"}}

    req = LLMRequest(
        task_type="brand_map",
        system_prompt="System prompt.",
        user_content="User content.",
        max_tokens=2048,
        tools=tools,
        tool_choice=tool_choice,
        temperature=0.5,
    )

    assert req.task_type == "brand_map"
    assert req.system_prompt == "System prompt."
    assert req.user_content == "User content."
    assert req.max_tokens == 2048
    assert req.tools == tools
    assert req.tool_choice == tool_choice
    assert req.temperature == 0.5


# ── 12. LLMResponse dataclass stores fields and has defaults ─────────────────

def test_llm_response_dataclass():
    """LLMResponse stores all fields; was_fallback defaults to False."""
    resp = LLMResponse(
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        content={"result": "ok"},
        raw_text=None,
        latency_ms=123.4,
        tokens_used=30,
    )

    assert resp.provider == "anthropic"
    assert resp.model == "claude-haiku-4-5-20251001"
    assert resp.content == {"result": "ok"}
    assert resp.raw_text is None
    assert resp.latency_ms == 123.4
    assert resp.tokens_used == 30
    assert resp.was_fallback is False  # default value
