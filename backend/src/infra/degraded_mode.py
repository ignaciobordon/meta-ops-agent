"""
Sprint 7 -- BLOQUE 9: Degraded Mode Detection.
Determines system state and enforces restrictions.
"""
from enum import Enum
from typing import Dict


class SystemMode(str, Enum):
    NORMAL = "normal"
    DEGRADED = "degraded"
    RESTRICTED = "restricted"


def get_system_mode() -> Dict:
    """Check all dependencies and return system mode."""
    from backend.src.infra.redis_client import redis_available

    redis_ok = redis_available()

    if not redis_ok:
        return {
            "mode": SystemMode.RESTRICTED,
            "reason": "Redis unavailable",
            "reads_ok": True,
            "writes_ok": False,
            "jobs_ok": False,
        }

    return {
        "mode": SystemMode.NORMAL,
        "reason": None,
        "reads_ok": True,
        "writes_ok": True,
        "jobs_ok": True,
    }
