"""
LLM Error Classification Tests.
Tests classify_llm_error from error_classifier.py for LLM-specific error codes.
6 tests covering: llm_auth, llm_timeout, llm_rate_limit, llm_degraded,
llm_provider_misconfig, and non-LLM fallback behavior.
"""
import os

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

import pytest

from backend.src.retries.error_classifier import classify_llm_error


# ── 1. test_classify_llm_auth ─────────────────────────────────────────────────


class TestClassifyLlmAuth:

    def test_classify_llm_auth(self):
        """Exception mentioning 'Anthropic unauthorized 401' is classified as
        llm_auth and NOT retryable."""
        result = classify_llm_error(Exception("Anthropic unauthorized 401"))
        assert result.code == "llm_auth", (
            f"Expected code='llm_auth', got '{result.code}'"
        )
        assert result.retryable is False


# ── 2. test_classify_llm_timeout ──────────────────────────────────────────────


class TestClassifyLlmTimeout:

    def test_classify_llm_timeout(self):
        """Exception mentioning 'Anthropic request timed out' is classified as
        llm_timeout and IS retryable."""
        result = classify_llm_error(Exception("Anthropic request timed out"))
        assert result.code == "llm_timeout", (
            f"Expected code='llm_timeout', got '{result.code}'"
        )
        assert result.retryable is True


# ── 3. test_classify_llm_rate_limit ───────────────────────────────────────────


class TestClassifyLlmRateLimit:

    def test_classify_llm_rate_limit(self):
        """Exception mentioning 'OpenAI rate limit exceeded 429' is classified as
        llm_rate_limit and IS retryable."""
        result = classify_llm_error(Exception("OpenAI rate limit exceeded 429"))
        assert result.code == "llm_rate_limit", (
            f"Expected code='llm_rate_limit', got '{result.code}'"
        )
        assert result.retryable is True


# ── 4. test_classify_llm_degraded ─────────────────────────────────────────────


class TestClassifyLlmDegraded:

    def test_classify_llm_degraded(self):
        """Exception mentioning 'circuit breaker open for provider' is classified as
        llm_degraded and IS retryable."""
        result = classify_llm_error(Exception("circuit breaker open for provider"))
        assert result.code == "llm_degraded", (
            f"Expected code='llm_degraded', got '{result.code}'"
        )
        assert result.retryable is True


# ── 5. test_classify_llm_misconfig ────────────────────────────────────────────


class TestClassifyLlmMisconfig:

    def test_classify_llm_misconfig(self):
        """Exception mentioning 'anthropic_api_key not set' is classified as
        llm_provider_misconfig and NOT retryable."""
        result = classify_llm_error(Exception("anthropic_api_key not set"))
        assert result.code == "llm_provider_misconfig", (
            f"Expected code='llm_provider_misconfig', got '{result.code}'"
        )
        assert result.retryable is False


# ── 6. test_classify_non_llm_unchanged ────────────────────────────────────────


class TestClassifyNonLlmUnchanged:

    def test_classify_non_llm_unchanged(self):
        """A generic error with no LLM provider keywords should NOT produce an
        llm_-prefixed error code; it falls back to the base classifier."""
        result = classify_llm_error(Exception("some random error"))
        assert not result.code.startswith("llm_"), (
            f"Expected a non-llm code for a generic error, got '{result.code}'"
        )
