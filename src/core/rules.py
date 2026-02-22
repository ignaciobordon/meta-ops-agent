"""
CP5 — Policy Rules
Individual validation rules that check ActionRequests against safety constraints.
Each rule can produce a RuleViolation (warning or block).
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

from src.schemas.policy import ActionRequest, RuleViolation

if TYPE_CHECKING:
    from src.core.policy_engine import LockStore


class Rule(ABC):
    """Base class for policy rules."""

    @abstractmethod
    def check(self, request: ActionRequest, lock_store: LockStore) -> Optional[RuleViolation]:
        """Return a RuleViolation if the request violates this rule, else None."""
        pass


class BudgetDeltaRule(Rule):
    """Block budget changes exceeding ±20% per iteration (adaptive with context)."""

    HARD_CAP = 0.30  # Never allow > 30% regardless of trust

    def __init__(self, max_delta_pct: float = 0.20):
        self.max_delta_pct = max_delta_pct

    def check(self, request: ActionRequest, lock_store: LockStore) -> Optional[RuleViolation]:
        if request.action_type != "budget_change":
            return None

        current = request.payload.get("current_budget", 0)
        new = request.payload.get("new_budget", 0)

        if current == 0:
            return None  # Can't compute delta for zero baseline

        delta_pct = abs(new - current) / current

        if delta_pct > self.max_delta_pct:
            return RuleViolation(
                rule_name="BudgetDeltaRule",
                severity="block",
                message=f"Budget change {delta_pct:.1%} exceeds max allowed {self.max_delta_pct:.0%}.",
                suggested_action=f"Reduce change to ±{self.max_delta_pct:.0%} ({current * (1 + self.max_delta_pct):.2f} max).",
            )
        return None

    def check_with_context(self, request: ActionRequest, lock_store: LockStore, context) -> Optional[RuleViolation]:
        """Context-aware budget delta check: trust adjusts the threshold."""
        if request.action_type != "budget_change":
            return None

        current = request.payload.get("current_budget", 0)
        new = request.payload.get("new_budget", 0)

        if current == 0:
            return None

        delta_pct = abs(new - current) / current

        # Dynamic threshold based on trust
        trust = getattr(context, 'trust_score', 50.0)
        if trust >= 80:
            adjusted_max = 0.25  # Relaxed: 25%
        elif trust < 30:
            adjusted_max = 0.15  # Strict: 15%
        else:
            adjusted_max = self.max_delta_pct  # Default: 20%

        # Hard cap always enforced
        adjusted_max = min(adjusted_max, self.HARD_CAP)

        if delta_pct > adjusted_max:
            return RuleViolation(
                rule_name="BudgetDeltaRule",
                severity="block",
                message=f"Budget change {delta_pct:.1%} exceeds max allowed {adjusted_max:.0%} (trust={trust:.0f}).",
                suggested_action=f"Reduce change to ±{adjusted_max:.0%} ({current * (1 + adjusted_max):.2f} max).",
            )
        return None


class CooldownLockRule(Rule):
    """Block changes to entities still in cooldown (locked from previous change)."""

    def check(self, request: ActionRequest, lock_store: LockStore) -> Optional[RuleViolation]:
        # Only structural changes trigger cooldown
        structural = {"budget_change", "creative_swap", "bid_change", "adset_pause"}
        if request.action_type not in structural:
            return None

        if lock_store.is_locked(request.entity_id):
            lock = lock_store.get_lock(request.entity_id)
            return RuleViolation(
                rule_name="CooldownLockRule",
                severity="block",
                message=f"Entity {request.entity_id} is locked until {lock.expires_at.isoformat()}.",
                suggested_action=f"Wait until cooldown expires or release lock manually.",
            )
        return None


class LearningPhaseProtectionRule(Rule):
    """Block changes to adsets in LEARNING phase unless CPA > 3x target."""

    def __init__(self, cpa_threshold_multiplier: float = 3.0):
        self.cpa_threshold = cpa_threshold_multiplier

    def check(self, request: ActionRequest, lock_store: LockStore) -> Optional[RuleViolation]:
        if request.entity_type != "adset":
            return None

        status = request.payload.get("adset_status", "").upper()
        if status != "LEARNING":
            return None

        cpa_ratio = request.payload.get("cpa_ratio", 0.0)  # current_cpa / target_cpa

        if cpa_ratio <= self.cpa_threshold:
            return RuleViolation(
                rule_name="LearningPhaseProtectionRule",
                severity="block",
                message=f"AdSet is in LEARNING phase with acceptable CPA ratio {cpa_ratio:.2f}x.",
                suggested_action=f"Wait for Learning Phase to complete or CPA to exceed {self.cpa_threshold}x target.",
            )
        return None


class NoDirectEditActiveAdRule(Rule):
    """Block direct edits to active ads — always duplicate instead."""

    def check(self, request: ActionRequest, lock_store: LockStore) -> Optional[RuleViolation]:
        if request.action_type != "creative_edit":
            return None

        ad_status = request.payload.get("ad_status", "").upper()
        if ad_status == "ACTIVE":
            return RuleViolation(
                rule_name="NoDirectEditActiveAdRule",
                severity="block",
                message="Direct edits to ACTIVE ads are prohibited to preserve historical performance data.",
                suggested_action="Duplicate the ad, edit the duplicate, then pause the original.",
            )
        return None


class ExcessiveFrequencyWarningRule(Rule):
    """Warn (not block) if an action targets an audience with frequency > 3.0."""

    def check(self, request: ActionRequest, lock_store: LockStore) -> Optional[RuleViolation]:
        frequency = request.payload.get("frequency", 0.0)
        if frequency > 3.0:
            return RuleViolation(
                rule_name="ExcessiveFrequencyWarningRule",
                severity="warning",
                message=f"Target audience has high frequency ({frequency:.2f}). Creative may be saturated.",
                suggested_action="Consider refreshing creative or expanding audience targeting.",
            )
        return None


# Rule registry — all active rules
DEFAULT_RULES = [
    BudgetDeltaRule(max_delta_pct=0.20),
    CooldownLockRule(),
    LearningPhaseProtectionRule(cpa_threshold_multiplier=3.0),
    NoDirectEditActiveAdRule(),
    ExcessiveFrequencyWarningRule(),
]
