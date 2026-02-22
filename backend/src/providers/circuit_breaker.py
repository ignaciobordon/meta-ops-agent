"""
Sprint 7 -- BLOQUE 6: Redis-Backed Persistent Circuit Breaker.
State stored per provider+org in Redis.
"""
import json
import time
from uuid import UUID

from src.utils.logging_config import logger


class PersistentCircuitBreaker:
    """
    Circuit breaker with state in Redis.
    Key: cb:{provider}:{org_id}
    Value: JSON {state, failure_count, last_failure_time, last_success_time}
    """

    def __init__(
        self,
        provider: str,
        org_id,
        failure_threshold: int = 5,
        cooldown_seconds: int = 60,
    ):
        self.provider = provider
        self.org_id = str(org_id)
        self.key = f"cb:{provider}:{org_id}"
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds

    def _get_redis(self):
        try:
            from backend.src.infra.redis_client import get_redis
            return get_redis()
        except Exception:
            return None

    def _load_state(self) -> dict:
        redis = self._get_redis()
        if redis is None:
            return {"state": "closed", "failure_count": 0}
        try:
            raw = redis.get(self.key)
            if raw is None:
                return {"state": "closed", "failure_count": 0}
            return json.loads(raw)
        except Exception:
            return {"state": "closed", "failure_count": 0}

    def _save_state(self, data: dict):
        redis = self._get_redis()
        if redis is None:
            return
        try:
            redis.set(self.key, json.dumps(data), ex=3600)  # 1 hour TTL
        except Exception as e:
            logger.warning("CB_SAVE_FAILED | {} | {}", self.key, str(e))

    @property
    def state(self) -> str:
        data = self._load_state()
        if data["state"] == "open":
            last_failure = data.get("last_failure_time", 0)
            if time.time() - last_failure >= self.cooldown_seconds:
                data["state"] = "half_open"
                self._save_state(data)
        return data["state"]

    def allow_request(self) -> bool:
        s = self.state
        return s in ("closed", "half_open")

    def record_success(self):
        data = {
            "state": "closed",
            "failure_count": 0,
            "last_success_time": time.time(),
        }
        self._save_state(data)

    def record_failure(self):
        data = self._load_state()
        data["failure_count"] = data.get("failure_count", 0) + 1
        data["last_failure_time"] = time.time()
        if data["failure_count"] >= self.failure_threshold:
            data["state"] = "open"
            logger.warning(
                "CIRCUIT_BREAKER_OPEN | provider={} | org={} | failures={}",
                self.provider, self.org_id, data["failure_count"],
            )
        self._save_state(data)

    def get_status(self) -> dict:
        """For /api/ops/providers endpoint."""
        data = self._load_state()
        return {
            "provider": self.provider,
            "org_id": self.org_id,
            "state": self.state,
            "failure_count": data.get("failure_count", 0),
            "last_failure_time": data.get("last_failure_time"),
            "last_success_time": data.get("last_success_time"),
        }
