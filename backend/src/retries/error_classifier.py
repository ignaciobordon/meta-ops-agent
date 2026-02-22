"""
Sprint 7 -- BLOQUE 4: Error Classifier.
Classifies exceptions into categories for retry decisions.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class ErrorClassification:
    code: str            # "transient", "auth_required", "quota_exceeded", "permanent"
    retryable: bool
    message: Optional[str] = None


# Keywords for each category (checked against lower-cased error string)
_AUTH_KEYWORDS = [
    "unauthorized", "401", "invalid token", "oauth",
    "authentication", "token expired", "190", "102",
]
_QUOTA_KEYWORDS = [
    "rate limit", "429", "too many requests", "quota",
    "throttl", "rate_limit",
]
_TRANSIENT_KEYWORDS = [
    "timeout", "timed out", "connection", "503", "502", "504",
    "econnreset", "temporary", "5xx", "service unavailable",
    "connection refused", "network",
]
_PERMANENT_KEYWORDS = [
    "400", "404", "invalid", "not found", "validation",
    "permission denied", "forbidden", "403",
]

_TRANSIENT_TYPES = (
    "TimeoutError", "ConnectionError", "ConnectionRefusedError",
    "ConnectionResetError", "BrokenPipeError", "OSError",
)


def classify_error(error: Exception) -> ErrorClassification:
    """Classify an exception for retry/dead-letter decisions."""
    error_str = str(error).lower()
    error_type = type(error).__name__

    # Check auth first (not retryable)
    if any(kw in error_str for kw in _AUTH_KEYWORDS):
        return ErrorClassification(
            code="auth_required",
            retryable=False,
            message="Authentication failure",
        )

    # Quota / rate limit (retryable with longer backoff)
    if any(kw in error_str for kw in _QUOTA_KEYWORDS):
        return ErrorClassification(
            code="quota_exceeded",
            retryable=True,
            message="Rate limit or quota exceeded",
        )

    # Transient network/server errors (retryable)
    if any(kw in error_str for kw in _TRANSIENT_KEYWORDS):
        return ErrorClassification(
            code="transient",
            retryable=True,
            message="Transient error",
        )

    # Check by exception type name
    if error_type in _TRANSIENT_TYPES:
        return ErrorClassification(
            code="transient",
            retryable=True,
            message=f"Transient: {error_type}",
        )

    # Permanent errors (not retryable)
    if any(kw in error_str for kw in _PERMANENT_KEYWORDS):
        return ErrorClassification(
            code="permanent",
            retryable=False,
            message="Permanent error",
        )

    # Default: treat as transient (safe for retries)
    return ErrorClassification(
        code="transient",
        retryable=True,
        message=f"Unclassified: {error_type}",
    )


# ── LLM-specific error codes ─────────────────────────────────────────────────

_LLM_PROVIDER_KEYWORDS = ["anthropic", "openai"]

_MISCONFIG_KEYWORDS = [
    "api_key not set", "no providers", "provider not configured",
    "missing api key", "anthropic_api_key", "openai_api_key",
    "api key is required",
]

_CIRCUIT_BREAKER_KEYWORDS = [
    "circuit breaker", "circuit_breaker", "breaker open",
    "provider unavailable",
]


def classify_llm_error(error: Exception) -> ErrorClassification:
    """
    Extended classifier for LLM-context errors.
    Returns specific codes: llm_auth, llm_timeout, llm_rate_limit,
    llm_degraded, llm_provider_misconfig.
    Falls back to classify_error() for non-LLM errors.
    """
    error_str = str(error).lower()

    # Misconfiguration (missing API keys) — not retryable
    if any(kw in error_str for kw in _MISCONFIG_KEYWORDS):
        return ErrorClassification(
            code="llm_provider_misconfig",
            retryable=False,
            message="LLM provider not configured (missing API key)",
        )

    # Circuit breaker open — retryable (wait for recovery)
    if any(kw in error_str for kw in _CIRCUIT_BREAKER_KEYWORDS):
        return ErrorClassification(
            code="llm_degraded",
            retryable=True,
            message="LLM provider circuit breaker open",
        )

    # Get base classification first
    base = classify_error(error)

    # Refine base classification when LLM provider is mentioned
    is_llm_related = any(kw in error_str for kw in _LLM_PROVIDER_KEYWORDS)

    if base.code == "auth_required" and is_llm_related:
        return ErrorClassification(
            code="llm_auth",
            retryable=False,
            message="LLM API authentication failure",
        )

    if base.code == "quota_exceeded" and is_llm_related:
        return ErrorClassification(
            code="llm_rate_limit",
            retryable=True,
            message="LLM provider rate limited",
        )

    if base.code == "transient" and is_llm_related:
        if "timeout" in error_str or "timed out" in error_str:
            return ErrorClassification(
                code="llm_timeout",
                retryable=True,
                message="LLM call timed out",
            )

    return base
