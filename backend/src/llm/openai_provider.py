"""
Sprint 9 — BLOQUE B: OpenAI LLM Provider.
Wraps the OpenAI SDK with unified LLMRequest/LLMResponse interface.
"""
import json
import os
import re
import time
from typing import Any, Dict

from openai import OpenAI

from backend.src.config import settings
from backend.src.llm.base import LLMProvider
from backend.src.llm.schema import LLMRequest, LLMResponse, LLMProviderError
from src.utils.logging_config import logger, get_trace_id

_DEFAULT_MODEL = "gpt-4o-2024-08-06"


class OpenAIProvider(LLMProvider):
    """OpenAI GPT provider."""

    provider_name = "openai"

    def __init__(self):
        api_key = settings.OPENAI_API_KEY
        if not api_key:
            raise LLMProviderError("OPENAI_API_KEY not configured")
        self.client = OpenAI(api_key=api_key)

    @classmethod
    def is_configured(cls) -> bool:
        return bool(settings.OPENAI_API_KEY)

    def _get_model(self) -> str:
        return os.environ.get("OPENAI_MODEL", _DEFAULT_MODEL)

    def generate(self, request: LLMRequest) -> LLMResponse:
        model = self._get_model()
        trace_id = get_trace_id()

        logger.bind(trace_id=trace_id).info(
            "LLM_REQUEST_START | provider=openai | task_type={} | model={}",
            request.task_type, model,
        )

        t0 = time.monotonic()

        messages = [
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": request.user_content},
        ]

        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
        }

        if request.tools:
            kwargs["tools"] = request.tools  # Already OpenAI format
        if request.tool_choice:
            kwargs["tool_choice"] = request.tool_choice

        response = self.client.chat.completions.create(**kwargs)
        latency_ms = (time.monotonic() - t0) * 1000

        # Extract token usage
        tokens_used = 0
        if response.usage:
            tokens_used = (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0)

        message = response.choices[0].message

        # Try tool_calls first
        if message.tool_calls:
            content = json.loads(message.tool_calls[0].function.arguments)
            raw_text = None
        else:
            # Fallback: parse JSON from message content
            raw_text = message.content or ""
            content = self._extract_json(raw_text)

        logger.bind(trace_id=trace_id).info(
            "LLM_REQUEST_SUCCESS | provider=openai | task_type={} | latency_ms={:.0f} | tokens={}",
            request.task_type, latency_ms, tokens_used,
        )

        return LLMResponse(
            provider="openai",
            model=model,
            content=content,
            raw_text=raw_text,
            latency_ms=latency_ms,
            tokens_used=tokens_used,
        )

    @staticmethod
    def _extract_json(content: str) -> dict:
        """Extract JSON from raw text content (markdown fences, raw JSON, etc.)."""
        # Strip markdown code fences
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return {}
