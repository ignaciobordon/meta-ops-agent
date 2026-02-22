"""
Sprint 7 -- BLOQUE 4: Error Classifier & Backoff Policies Tests.
Tests classify_error categories (transient, auth_required, quota_exceeded,
permanent, default) and backoff delay logic (schedules, jitter, max_attempts).
"""
import os

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from datetime import timedelta

import pytest

from backend.src.retries.error_classifier import classify_error, ErrorClassification
from backend.src.retries.backoff import get_next_retry_delay, get_max_attempts


# ---------------------------------------------------------------------------
# Error Classification Tests
# ---------------------------------------------------------------------------


class TestClassifyTransientErrors:
    """Transient errors should be retryable."""

    def test_classify_timeout_error(self):
        """TimeoutError is classified as transient and retryable."""
        result = classify_error(TimeoutError("request timed out"))
        assert result.code == "transient"
        assert result.retryable is True

    def test_classify_connection_error(self):
        """ConnectionError is classified as transient and retryable."""
        result = classify_error(ConnectionError("connection refused"))
        assert result.code == "transient"
        assert result.retryable is True

    def test_classify_502_error(self):
        """Exception with '502 Bad Gateway' is classified as transient and retryable."""
        result = classify_error(Exception("502 Bad Gateway"))
        assert result.code == "transient"
        assert result.retryable is True

    def test_classify_503_error(self):
        """Exception with '503 Service Unavailable' is classified as transient and retryable."""
        result = classify_error(Exception("503 Service Unavailable"))
        assert result.code == "transient"
        assert result.retryable is True


class TestClassifyAuthErrors:
    """Auth errors should NOT be retryable."""

    def test_classify_401_error(self):
        """Exception with '401 Unauthorized' is classified as auth_required and NOT retryable."""
        result = classify_error(Exception("401 Unauthorized"))
        assert result.code == "auth_required"
        assert result.retryable is False

    def test_classify_expired_token(self):
        """Exception with 'expired token' is classified as auth_required and NOT retryable."""
        result = classify_error(Exception("token expired"))
        assert result.code == "auth_required"
        assert result.retryable is False


class TestClassifyQuotaErrors:
    """Quota / rate-limit errors should be retryable."""

    def test_classify_429_error(self):
        """Exception with '429 Too Many Requests' is classified as quota_exceeded and retryable."""
        result = classify_error(Exception("429 Too Many Requests"))
        assert result.code == "quota_exceeded"
        assert result.retryable is True

    def test_classify_rate_limit(self):
        """Exception with 'rate limit exceeded' is classified as quota_exceeded and retryable."""
        result = classify_error(Exception("rate limit exceeded"))
        assert result.code == "quota_exceeded"
        assert result.retryable is True


class TestClassifyPermanentErrors:
    """Permanent errors should NOT be retryable."""

    def test_classify_400_error(self):
        """Exception with '400 Bad Request' is classified as permanent and NOT retryable."""
        result = classify_error(Exception("400 Bad Request"))
        assert result.code == "permanent"
        assert result.retryable is False


class TestClassifyDefaultFallback:
    """Unknown errors default to transient (retryable) for safety."""

    def test_classify_unknown_error(self):
        """Exception with unrecognized message defaults to transient and retryable."""
        result = classify_error(Exception("something weird"))
        assert result.code == "transient"
        assert result.retryable is True
        assert result.message is not None


# ---------------------------------------------------------------------------
# Backoff Policy Tests
# ---------------------------------------------------------------------------


class TestBackoffDelay:
    """Backoff delay calculations and jitter behaviour."""

    def test_backoff_delay_meta_sync(self):
        """get_next_retry_delay for meta_sync_assets attempt 1 returns ~60s (+-20%)."""
        delay = get_next_retry_delay("meta_sync_assets", 1)
        assert isinstance(delay, timedelta)
        seconds = delay.total_seconds()
        # 60s base with +-20% jitter => range [48, 72]
        assert 48 <= seconds <= 72, (
            f"Expected delay between 48s and 72s, got {seconds}s"
        )

    def test_backoff_delay_increases(self):
        """Delays should increase with higher attempt numbers."""
        delay_1 = get_next_retry_delay("meta_sync_assets", 1).total_seconds()
        delay_2 = get_next_retry_delay("meta_sync_assets", 2).total_seconds()
        delay_3 = get_next_retry_delay("meta_sync_assets", 3).total_seconds()

        # Even with jitter, the base delays [60, 300, 900] are far enough apart
        # that the ordering should hold.
        assert delay_1 < delay_2 < delay_3, (
            f"Expected increasing delays: {delay_1}, {delay_2}, {delay_3}"
        )

    def test_backoff_jitter(self):
        """Multiple calls should produce different values due to jitter."""
        samples = [
            get_next_retry_delay("meta_sync_assets", 1).total_seconds()
            for _ in range(20)
        ]
        unique_values = set(samples)
        # With 20 random samples there should be more than 1 unique value.
        assert len(unique_values) > 1, (
            "Expected jitter to produce varying delays, but all 20 samples "
            f"were identical: {samples[0]}s"
        )


class TestMaxAttempts:
    """get_max_attempts returns correct values per job type and default."""

    def test_get_max_attempts_meta(self):
        """meta_sync_assets should have max_attempts == 8."""
        assert get_max_attempts("meta_sync_assets") == 8

    def test_get_max_attempts_default(self):
        """Unknown job type should fall back to default max_attempts == 5."""
        assert get_max_attempts("unknown_type") == 5
