"""
Sprint 9 — BLOQUE B: Abstract base class for LLM providers.
"""
from abc import ABC, abstractmethod

from backend.src.llm.schema import LLMRequest, LLMResponse


class LLMProvider(ABC):
    """Abstract base for LLM provider implementations."""

    provider_name: str = ""

    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        """Send a request to the LLM and return a structured response."""
        ...

    @classmethod
    @abstractmethod
    def is_configured(cls) -> bool:
        """Return True if the provider has valid credentials configured."""
        ...
