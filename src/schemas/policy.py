from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

ActionType = Literal[
    "budget_change",
    "creative_swap",
    "bid_change",
    "adset_pause",
    "adset_duplicate",
    "creative_edit",  # direct edit — should always be blocked
]

EntityType = Literal["adset", "ad", "campaign"]
Severity = Literal["warning", "block"]


class ActionRequest(BaseModel):
    """A proposed change to a Meta Ads entity."""
    action_type: ActionType
    entity_id: str
    entity_type: EntityType
    payload: Dict[str, Any] = Field(default_factory=dict)
    trace_id: str
    requested_at: datetime = Field(default_factory=datetime.utcnow)


class RuleViolation(BaseModel):
    """A rule that was triggered by an action request."""
    rule_name: str
    severity: Severity
    message: str
    suggested_action: str = ""


class ValidationResult(BaseModel):
    """Outcome of validating an action request against policy rules."""
    approved: bool
    action_request: ActionRequest
    violations: List[RuleViolation] = Field(default_factory=list)
    lock_acquired: bool = False
    cooldown_until: Optional[datetime] = None

    def blocking_violations(self) -> List[RuleViolation]:
        return [v for v in self.violations if v.severity == "block"]


class LockEntry(BaseModel):
    """A lock on an entity preventing further changes during cooldown."""
    entity_id: str
    locked_by_trace_id: str
    locked_at: datetime
    expires_at: datetime
    action_type: str
