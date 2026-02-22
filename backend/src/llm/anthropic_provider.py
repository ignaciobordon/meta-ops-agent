"""
Sprint 9 — BLOQUE B: Anthropic LLM Provider.
Wraps the Anthropic SDK with unified LLMRequest/LLMResponse interface.
"""
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

from anthropic import Anthropic

from backend.src.config import settings
from backend.src.llm.base import LLMProvider
from backend.src.llm.schema import LLMRequest, LLMResponse, LLMProviderError
from src.utils.logging_config import logger, get_trace_id

# Default models per task type
_TASK_MODELS = {
    "brand_map": "claude-haiku-4-5-20251001",
    "creative_factory": "claude-sonnet-4-5-20250929",
    "scoring": "claude-haiku-4-5-20251001",
    "content_studio": "claude-sonnet-4-5-20250929",
    "ci_analysis": "claude-sonnet-4-5-20250929",
}


def _convert_tools_to_anthropic(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert OpenAI-format tool definitions to Anthropic format."""
    anthropic_tools = []
    for tool in tools:
        if tool.get("type") == "function":
            func = tool["function"]
            anthropic_tools.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func["parameters"],
            })
        elif "name" in tool and "input_schema" in tool:
            # Already Anthropic format
            anthropic_tools.append(tool)
    return anthropic_tools


def _convert_tool_choice(tool_choice: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Convert OpenAI-format tool_choice to Anthropic format."""
    if tool_choice is None:
        return None
    # OpenAI: {"type": "function", "function": {"name": "foo"}}
    if "function" in tool_choice:
        return {"type": "tool", "name": tool_choice["function"]["name"]}
    # Already Anthropic format: {"type": "tool", "name": "foo"}
    if tool_choice.get("type") == "tool":
        return tool_choice
    return None


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider."""

    provider_name = "anthropic"

    def __init__(self):
        api_key = settings.ANTHROPIC_API_KEY
        if not api_key:
            raise LLMProviderError("ANTHROPIC_API_KEY not configured")
        self.client = Anthropic(api_key=api_key)

    @classmethod
    def is_configured(cls) -> bool:
        return bool(settings.ANTHROPIC_API_KEY)

    def _get_model(self, task_type: str) -> str:
        override = os.environ.get("ANTHROPIC_MODEL")
        if override:
            return override
        return _TASK_MODELS.get(task_type, "claude-haiku-4-5-20251001")

    @staticmethod
    def _extract_json(content_str: str) -> dict:
        """Extract JSON from raw text that may contain markdown code fences."""
        # Try stripping ```json ... ``` fences
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content_str, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        # Try raw parse
        try:
            return json.loads(content_str)
        except json.JSONDecodeError:
            pass
        # Try extracting first JSON object
        match = re.search(r"\{.*\}", content_str, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return {}

    def generate(self, request: LLMRequest) -> LLMResponse:
        model = self._get_model(request.task_type)
        trace_id = get_trace_id()

        logger.bind(trace_id=trace_id).info(
            "LLM_REQUEST_START | provider=anthropic | task_type={} | model={}",
            request.task_type, model,
        )

        t0 = time.monotonic()

        kwargs: Dict[str, Any] = {
            "model": model,
            "max_tokens": request.max_tokens,
            "system": request.system_prompt,
            "messages": [{"role": "user", "content": request.user_content}],
        }

        if request.tools:
            kwargs["tools"] = _convert_tools_to_anthropic(request.tools)
        if request.tool_choice:
            converted = _convert_tool_choice(request.tool_choice)
            if converted:
                kwargs["tool_choice"] = converted

        response = self.client.messages.create(**kwargs)
        latency_ms = (time.monotonic() - t0) * 1000

        # Extract token usage
        tokens_used = 0
        if hasattr(response, "usage") and response.usage:
            tokens_used = (response.usage.input_tokens or 0) + (response.usage.output_tokens or 0)

        # Extract tool_use block
        tool_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_block:
            content = tool_block.input if isinstance(tool_block.input, dict) else json.loads(tool_block.input)
            raw_text = None
        else:
            # Fallback: try to parse text content as JSON
            text_blocks = [b for b in response.content if b.type == "text"]
            raw_text = text_blocks[0].text if text_blocks else ""
            try:
                content = json.loads(raw_text)
            except (json.JSONDecodeError, TypeError):
                content = self._extract_json(raw_text)

        logger.bind(trace_id=trace_id).info(
            "LLM_REQUEST_SUCCESS | provider=anthropic | task_type={} | latency_ms={:.0f} | tokens={}",
            request.task_type, latency_ms, tokens_used,
        )

        # Capture stop reason for truncation detection
        stop_reason = getattr(response, 'stop_reason', None)
        if stop_reason == 'max_tokens':
            logger.bind(trace_id=trace_id).warning(
                "LLM_RESPONSE_TRUNCATED | provider=anthropic | task_type={} | "
                "max_tokens={} | Response was cut off by token limit",
                request.task_type, request.max_tokens,
            )

        return LLMResponse(
            provider="anthropic",
            model=model,
            content=content,
            raw_text=raw_text,
            latency_ms=latency_ms,
            tokens_used=tokens_used,
            stop_reason=stop_reason,
        )
