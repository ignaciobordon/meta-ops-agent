"""
Sprint 7 -- BLOQUE 9: Degraded Mode Detection Tests
Tests for SystemMode enum and get_system_mode behaviour under different
Redis availability scenarios.
"""
import os
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.src.infra.degraded_mode import SystemMode, get_system_mode


# -- 1. Normal mode when Redis is available ------------------------------------

def test_normal_mode_with_redis():
    """get_system_mode returns NORMAL when Redis is reachable."""
    with patch("backend.src.infra.redis_client.redis_available", return_value=True):
        result = get_system_mode()
    assert result["mode"] is SystemMode.NORMAL


# -- 2. Restricted mode when Redis is unavailable -----------------------------

def test_restricted_mode_without_redis():
    """get_system_mode returns RESTRICTED when Redis is unreachable."""
    with patch("backend.src.infra.redis_client.redis_available", return_value=False):
        result = get_system_mode()
    assert result["mode"] is SystemMode.RESTRICTED


# -- 3. All capabilities enabled in normal mode -------------------------------

def test_normal_capabilities():
    """When Redis is available, reads, writes, and jobs are all enabled."""
    with patch("backend.src.infra.redis_client.redis_available", return_value=True):
        result = get_system_mode()
    assert result["reads_ok"] is True
    assert result["writes_ok"] is True
    assert result["jobs_ok"] is True
    assert result["reason"] is None


# -- 4. Restricted capabilities without Redis ----------------------------------

def test_restricted_capabilities():
    """When Redis is down, writes and jobs are disabled; reads remain ok."""
    with patch("backend.src.infra.redis_client.redis_available", return_value=False):
        result = get_system_mode()
    assert result["reads_ok"] is True
    assert result["writes_ok"] is False
    assert result["jobs_ok"] is False
    assert result["reason"] == "Redis unavailable"


# -- 5. SystemMode enum members -----------------------------------------------

def test_system_mode_enum_values():
    """SystemMode must expose NORMAL, DEGRADED, and RESTRICTED members."""
    assert SystemMode.NORMAL.value == "normal"
    assert SystemMode.DEGRADED.value == "degraded"
    assert SystemMode.RESTRICTED.value == "restricted"
    # Ensure exactly three members exist
    assert set(SystemMode.__members__.keys()) == {"NORMAL", "DEGRADED", "RESTRICTED"}
