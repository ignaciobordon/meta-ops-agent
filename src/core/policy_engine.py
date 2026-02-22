"""
CP5 — Policy Engine
Pre-execution validation engine that enforces safety guardrails.
Validates ActionRequests against a registry of rules and manages entity locks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from src.schemas.policy import ActionRequest, LockEntry, RuleViolation, ValidationResult
from src.core.rules import DEFAULT_RULES, Rule
from src.utils.logging_config import logger, get_trace_id


@dataclass
class PolicyContext:
    """Dynamic context from entity memory for adaptive policy thresholds."""
    trust_score: float = 50.0  # 0-100 from entity_memory
    volatility: Dict[str, float] = field(default_factory=dict)
    recent_outcomes: List[str] = field(default_factory=list)  # ["win", "loss"]
    plan: str = "trial"


class LockStore:
    """In-memory lock store for entity cooldown management."""

    def __init__(self):
        self._locks: Dict[str, LockEntry] = {}

    def acquire(
        self, entity_id: str, request: ActionRequest, ttl_hours: int = 24
    ) -> LockEntry:
        """Acquire a lock on an entity for the specified TTL."""
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=ttl_hours)
        lock = LockEntry(
            entity_id=entity_id,
            locked_by_trace_id=request.trace_id,
            locked_at=now,
            expires_at=expires,
            action_type=request.action_type,
        )
        self._locks[entity_id] = lock
        logger.info(
            f"POLICY_LOCK_ACQUIRED | entity={entity_id} | expires={expires.isoformat()} | trace_id={request.trace_id}"
        )
        return lock

    def is_locked(self, entity_id: str) -> bool:
        """Check if an entity is currently locked (within cooldown)."""
        lock = self._locks.get(entity_id)
        if not lock:
            return False
        if datetime.now(timezone.utc) > lock.expires_at:
            # Lock expired — remove it
            del self._locks[entity_id]
            return False
        return True

    def get_lock(self, entity_id: str) -> Optional[LockEntry]:
        """Retrieve the active lock for an entity, if any."""
        if not self.is_locked(entity_id):
            return None
        return self._locks.get(entity_id)

    def release(self, entity_id: str):
        """Manually release a lock (for testing or emergency override)."""
        if entity_id in self._locks:
            del self._locks[entity_id]
            logger.info(f"POLICY_LOCK_RELEASED | entity={entity_id}")

    def clear_all(self):
        """Clear all locks (for testing)."""
        self._locks.clear()


class PolicyEngine:
    """
    Validates ActionRequests against a registry of policy rules.
    If approved, acquires a cooldown lock on the entity.
    """

    def __init__(
        self, rules: Optional[List[Rule]] = None, lock_store: Optional[LockStore] = None
    ):
        self.rules = rules if rules is not None else DEFAULT_RULES
        self.lock_store = lock_store if lock_store is not None else LockStore()

    def validate(
        self,
        request: ActionRequest,
        context: Optional[PolicyContext] = None,
    ) -> ValidationResult:
        """
        Validate an ActionRequest against all registered rules.
        Returns a ValidationResult with approval status and any violations.
        If approved, a cooldown lock is acquired on the entity.
        """
        trace_id = get_trace_id()
        logger.info(
            f"POLICY_VALIDATION_STARTED | trace_id={trace_id} "
            f"| action={request.action_type} | entity={request.entity_id}"
        )

        violations: List[RuleViolation] = []
        for rule in self.rules:
            # Use context-aware check if available and context provided
            if context and hasattr(rule, 'check_with_context'):
                violation = rule.check_with_context(request, self.lock_store, context)
            else:
                violation = rule.check(request, self.lock_store)
            if violation:
                violations.append(violation)

        blocking = [v for v in violations if v.severity == "block"]
        approved = len(blocking) == 0

        lock_acquired = False
        cooldown_until = None

        if approved:
            # Acquire lock for structural changes
            structural = {"budget_change", "creative_swap", "bid_change", "adset_pause"}
            if request.action_type in structural:
                lock = self.lock_store.acquire(request.entity_id, request)
                lock_acquired = True
                cooldown_until = lock.expires_at

        result = ValidationResult(
            approved=approved,
            action_request=request,
            violations=violations,
            lock_acquired=lock_acquired,
            cooldown_until=cooldown_until,
        )

        logger.info(
            f"POLICY_VALIDATION_DONE | approved={approved} "
            f"| violations={len(violations)} | blocking={len(blocking)}"
        )
        return result

    def add_rule(self, rule: Rule):
        """Add a custom rule to the registry."""
        self.rules.append(rule)

    def remove_rule(self, rule_name: str):
        """Remove a rule from the registry by name."""
        self.rules = [r for r in self.rules if r.__class__.__name__ != rule_name]
