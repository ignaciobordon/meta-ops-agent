"""
Sprint 7 -- BLOQUE 4: Backoff Policies.
Per-job-type retry schedules with exponential backoff + jitter.
"""
import random
from datetime import timedelta
from typing import Dict


# Backoff policy: delays_seconds list + max_attempts
BACKOFF_POLICIES: Dict[str, Dict] = {
    "meta_sync_assets":     {"delays": [60, 300, 900, 3600], "max_attempts": 8},
    "meta_sync_insights":   {"delays": [60, 300, 900, 3600], "max_attempts": 8},
    "meta_live_monitor":    {"delays": [60, 300, 900, 3600], "max_attempts": 8},
    "meta_generate_alerts": {"delays": [60, 300, 900, 3600], "max_attempts": 8},
    "outcome_capture":      {"delays": [300, 1800, 7200], "max_attempts": 6},
    "decision_execute":     {"delays": [60, 300, 900], "max_attempts": 4},
    "creatives_generate":   {"delays": [30, 120, 600], "max_attempts": 6},
    "opportunities_analyze": {"delays": [30, 120, 600], "max_attempts": 6},
    "ci_ingest":             {"delays": [60, 300, 900], "max_attempts": 4},
    "ci_detect":             {"delays": [30, 120, 600], "max_attempts": 4},
}

DEFAULT_POLICY = {"delays": [60, 300, 900], "max_attempts": 5}


def get_next_retry_delay(job_type: str, current_attempt: int) -> timedelta:
    """
    Calculate next retry delay with jitter.
    Uses the delay schedule if attempt falls within range,
    otherwise uses exponential backoff from the last defined delay.
    """
    policy = BACKOFF_POLICIES.get(job_type, DEFAULT_POLICY)
    delays = policy["delays"]

    idx = current_attempt - 1
    if idx < len(delays):
        base_delay = delays[idx]
    else:
        # Exponential from last known delay
        last_delay = delays[-1]
        overflow = idx - len(delays) + 1
        base_delay = min(last_delay * (2 ** overflow), 14400)  # Cap at 4 hours

    # Add jitter: ±20%
    jitter = base_delay * 0.2 * (2 * random.random() - 1)
    final_delay = max(10, base_delay + jitter)

    return timedelta(seconds=final_delay)


def get_max_attempts(job_type: str) -> int:
    """Get the max attempts for a job type."""
    policy = BACKOFF_POLICIES.get(job_type, DEFAULT_POLICY)
    return policy["max_attempts"]
