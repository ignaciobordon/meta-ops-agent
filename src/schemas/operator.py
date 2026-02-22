from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from src.schemas.policy import ActionRequest, ValidationResult


class DecisionPack(BaseModel):
    """A proposed action with context — fed to Operator for execution."""

    action_request: ActionRequest
    rationale: str  # Why this action (from saturation analysis, scorer, etc.)
    source: str  # Which engine triggered this (e.g., "SaturationEngine", "Manual")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    """Result of executing a single action via Meta API."""

    success: bool
    api_response: Dict[str, Any] = Field(default_factory=dict)
    error_message: str = ""
    dry_run: bool = False  # Was this a simulated execution?


class ExecutionLog(BaseModel):
    """Complete audit trail of a decision execution attempt."""

    decision_pack: DecisionPack
    policy_result: ValidationResult
    action_result: Optional[ActionResult] = None
    executed_at: datetime = Field(default_factory=datetime.utcnow)
    trace_id: str
    killed: bool = False  # Was this stopped by kill switch?


class DecisionMemoryEntry(BaseModel):
    """Persistent record of an execution stored in DecisionMemory."""

    log_id: str
    execution_log: ExecutionLog
    stored_at: datetime = Field(default_factory=datetime.utcnow)
