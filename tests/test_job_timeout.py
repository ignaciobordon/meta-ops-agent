"""
Job Execution Timeout Tests.
Unit tests for per-job-type timeout constants in task_runner.py.
4 tests covering: constants existence, creatives timeout, opportunities timeout, default timeout.
"""
import os

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

import pytest

from backend.src.jobs.task_runner import _JOB_TIMEOUT, _DEFAULT_JOB_TIMEOUT


# ── 1. test_timeout_constants_exist ───────────────────────────────────────────


class TestTimeoutConstantsExist:

    def test_timeout_constants_exist(self):
        """_JOB_TIMEOUT and _DEFAULT_JOB_TIMEOUT are defined and accessible."""
        assert _JOB_TIMEOUT is not None, "_JOB_TIMEOUT should be defined"
        assert isinstance(_JOB_TIMEOUT, dict), "_JOB_TIMEOUT should be a dict"
        assert _DEFAULT_JOB_TIMEOUT is not None, "_DEFAULT_JOB_TIMEOUT should be defined"
        assert isinstance(_DEFAULT_JOB_TIMEOUT, (int, float)), (
            "_DEFAULT_JOB_TIMEOUT should be numeric"
        )


# ── 2. test_creatives_timeout_value ───────────────────────────────────────────


class TestCreativesTimeoutValue:

    def test_creatives_timeout_value(self):
        """creatives_generate has a 180-second timeout."""
        assert "creatives_generate" in _JOB_TIMEOUT, (
            "creatives_generate should have an explicit timeout in _JOB_TIMEOUT"
        )
        assert _JOB_TIMEOUT["creatives_generate"] == 180, (
            f"Expected creatives_generate timeout of 180s, "
            f"got {_JOB_TIMEOUT['creatives_generate']}s"
        )


# ── 3. test_opportunities_timeout_value ───────────────────────────────────────


class TestOpportunitiesTimeoutValue:

    def test_opportunities_timeout_value(self):
        """opportunities_analyze has a 180-second timeout."""
        assert "opportunities_analyze" in _JOB_TIMEOUT, (
            "opportunities_analyze should have an explicit timeout in _JOB_TIMEOUT"
        )
        assert _JOB_TIMEOUT["opportunities_analyze"] == 180, (
            f"Expected opportunities_analyze timeout of 180s, "
            f"got {_JOB_TIMEOUT['opportunities_analyze']}s"
        )


# ── 4. test_default_timeout_value ─────────────────────────────────────────────


class TestDefaultTimeoutValue:

    def test_default_timeout_value(self):
        """Default timeout for unlisted job types is 120 seconds."""
        assert _DEFAULT_JOB_TIMEOUT == 120, (
            f"Expected _DEFAULT_JOB_TIMEOUT of 120s, got {_DEFAULT_JOB_TIMEOUT}s"
        )
