"""
Pytest configuration for test suite.
Sets up Python path to support dual-module structure (root src/ and backend/src/).
"""
import os
import sys
import uuid
from pathlib import Path
import pytest

# ── SQLite UUID compat for SQLAlchemy 2.x ──────────────────────────────────
# PG_UUID stores UUIDs as integers in SQLite by default. Patch bind/result
# processors so they serialize as strings and deserialize back to uuid.UUID.
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

_orig_bp = PG_UUID.bind_processor
_orig_rp = PG_UUID.result_processor


def _sqlite_bind_processor(self, dialect):
    if dialect.name == "sqlite":
        def process(value):
            if value is not None:
                return str(value) if not isinstance(value, str) else value
            return value
        return process
    return _orig_bp(self, dialect)


def _sqlite_result_processor(self, dialect, coltype):
    if dialect.name == "sqlite":
        def process(value):
            if value is None:
                return None
            if isinstance(value, uuid.UUID):
                return value
            if isinstance(value, int):
                return uuid.UUID(int=value)
            return uuid.UUID(str(value))
        return process
    return _orig_rp(self, dialect, coltype)


PG_UUID.bind_processor = _sqlite_bind_processor
PG_UUID.result_processor = _sqlite_result_processor
PG_UUID.impl = String(36)

# Get project root
root_path = Path(__file__).parent.parent

# Add project root to Python path
# root src/ (core modules) must be discoverable first so `from src.utils` resolves correctly
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

# Data paths fixture
@pytest.fixture(scope="session")
def data_dir():
    """Return path to test data directory."""
    return root_path / "data"

@pytest.fixture(scope="session")
def demo_brand_path(data_dir):
    """Return path to demo brand text file."""
    return data_dir / "demo_brand.txt"

@pytest.fixture(scope="session")
def demo_ads_csv_path(data_dir):
    """Return path to demo ads CSV file."""
    return data_dir / "demo_ads_performance.csv"


@pytest.fixture(autouse=True)
def _reset_login_rate_limiter():
    """Reset the login rate limiter between every test to prevent cross-contamination."""
    os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")
    try:
        from backend.src.middleware.rate_limit import login_limiter
        login_limiter.attempts.clear()
    except ImportError:
        pass
    yield
    try:
        from backend.src.middleware.rate_limit import login_limiter
        login_limiter.attempts.clear()
    except ImportError:
        pass
