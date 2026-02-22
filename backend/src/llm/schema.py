"""
Sprint 9 — BLOQUE B: LLM Request/Response schemas.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class LLMRequest:
    """Unified request for any LLM provider."""
    task_type: str                          # "brand_map" | "creative_factory" | "scoring"
    system_prompt: str
    user_content: str
    max_tokens: int = 4096
    tools: Optional[List[Dict[str, Any]]] = None      # OpenAI-format tool definitions
    tool_choice: Optional[Dict[str, Any]] = None
    temperature: float = 0.7


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""
    provider: str                           # "anthropic" | "openai"
    model: str
    content: Dict[str, Any]                 # parsed tool_use output or JSON
    raw_text: Optional[str] = None          # raw text content (if no tool_use)
    latency_ms: float = 0.0
    tokens_used: int = 0
    was_fallback: bool = False
    stop_reason: Optional[str] = None       # "end_turn" | "max_tokens" | "stop_sequence"


class LLMProviderError(Exception):
    """Raised when all LLM providers fail."""
    pass
