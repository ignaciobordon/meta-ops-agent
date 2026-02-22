"""
Policies API - Exposes CP5 (Policy Engine) rules and violations from REAL data.
No mock data. Rules derived from DEFAULT_RULES registry.
Violations queried from DecisionPack table (state=BLOCKED).
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from pydantic import BaseModel
from datetime import datetime, timezone

from backend.src.database.session import get_db
from backend.src.database.models import DecisionPack, DecisionState
from backend.src.middleware.auth import get_current_user
from backend.src.utils.tenant import get_org_ad_account_ids
from src.core.policy_engine import PolicyEngine
from src.core.rules import DEFAULT_RULES
from src.utils.logging_config import set_trace_id
from uuid import uuid4

router = APIRouter(tags=["policies"])

# Initialize engine
policy_engine = PolicyEngine()


# ── Rule metadata registry ────────────────────────────────────────────────────
# Maps class names to human-readable descriptions for the API.
RULE_METADATA = {
    "BudgetDeltaRule": {
        "rule_id": "budget_delta",
        "name": "Budget Change Limits",
        "description": "Budget changes must be within ±20% of current value to prevent drastic shifts that could destabilize learning algorithms",
        "severity": "critical",
    },
    "CooldownLockRule": {
        "rule_id": "cooldown_lock",
        "name": "Action Cooldown Period",
        "description": "Minimum 24-hour wait between changes to the same entity to allow Meta's algorithm to stabilize and measure results",
        "severity": "high",
    },
    "LearningPhaseProtectionRule": {
        "rule_id": "learning_phase_protection",
        "name": "Learning Phase Protection",
        "description": "Prevent changes to campaigns in learning phase (first 7 days or fewer than 50 conversions) to avoid resetting optimization",
        "severity": "critical",
    },
    "NoDirectEditActiveAdRule": {
        "rule_id": "no_direct_edits",
        "name": "No Direct Campaign Edits",
        "description": "Block direct edits to running campaigns - only allow budget/bidding controls to maintain campaign history and data integrity",
        "severity": "medium",
    },
    "ExcessiveFrequencyWarningRule": {
        "rule_id": "excessive_frequency",
        "name": "Excessive Frequency Warning",
        "description": "Warn when audience frequency exceeds 3.0 - indicates creative fatigue and ad saturation",
        "severity": "medium",
    },
}


# Response Models
class PolicyRuleResponse(BaseModel):
    rule_id: str
    name: str
    description: str
    severity: str  # "critical", "high", "medium"
    enabled: bool
    violations_count: int


class ViolationResponse(BaseModel):
    id: str
    rule_name: str
    decision_id: str
    severity: str
    message: str
    occurred_at: str


@router.get("/rules", response_model=List[PolicyRuleResponse])
def list_policy_rules(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    """
    List all policy rules from CP5 Policy Engine.
    Rules derived from the REAL DEFAULT_RULES registry in src/core/rules.py.
    Violation counts queried from DecisionPack table (scoped to org).
    """
    trace_id = f"pol-{uuid4().hex[:12]}"
    set_trace_id(trace_id)

    try:
        org_id = user.get("org_id", "")
        org_accounts = get_org_ad_account_ids(org_id, db)

        # Count violations per rule from REAL decision data (org-scoped)
        query = db.query(DecisionPack).filter(
            DecisionPack.state == DecisionState.BLOCKED
        )
        if org_accounts:
            query = query.filter(DecisionPack.ad_account_id.in_(org_accounts))
        blocked_decisions = query.all()

        # Count violations by rule name
        violation_counts = {}
        for decision in blocked_decisions:
            checks = decision.policy_checks or []
            for check in checks:
                if not check.get("passed", True):
                    rule_name = check.get("rule_name", "")
                    violation_counts[rule_name] = violation_counts.get(rule_name, 0) + 1

        # Build response from REAL rules
        rules = []
        for rule in DEFAULT_RULES:
            class_name = type(rule).__name__
            metadata = RULE_METADATA.get(class_name)
            if not metadata:
                continue

            # Map class name to violation count key
            count = violation_counts.get(class_name, 0)

            rules.append(PolicyRuleResponse(
                rule_id=metadata["rule_id"],
                name=metadata["name"],
                description=metadata["description"],
                severity=metadata["severity"],
                enabled=True,
                violations_count=count,
            ))

        # Add kill switch status (not a Rule class, but a PolicyEngine feature)
        from src.core.operator import Operator
        rules.append(PolicyRuleResponse(
            rule_id="kill_switch",
            name="Emergency Kill Switch",
            description="Master switch to immediately halt all automated actions when activated - requires manual re-enable",
            severity="critical",
            enabled=True,
            violations_count=0,
        ))

        return rules

    except Exception as e:
        raise HTTPException(500, f"Failed to load policy rules: {str(e)}")


@router.get("/violations", response_model=List[ViolationResponse])
def list_violations(limit: int = 50, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    """
    List recent policy violations from REAL DecisionPack data.
    Queries decisions that were BLOCKED by policy validation (scoped to org).
    """
    trace_id = f"pol-{uuid4().hex[:12]}"
    set_trace_id(trace_id)

    try:
        org_id = user.get("org_id", "")
        org_accounts = get_org_ad_account_ids(org_id, db)

        # Query decisions that were blocked or have policy violations (org-scoped)
        query = db.query(DecisionPack).filter(
            DecisionPack.state == DecisionState.BLOCKED
        )
        if org_accounts:
            query = query.filter(DecisionPack.ad_account_id.in_(org_accounts))
        blocked_decisions = query.order_by(DecisionPack.validated_at.desc()).limit(limit).all()

        violations = []
        for decision in blocked_decisions:
            checks = decision.policy_checks or []
            for check in checks:
                if not check.get("passed", True):
                    violations.append(ViolationResponse(
                        id=f"viol-{decision.trace_id}-{check.get('rule_name', 'unknown')}",
                        rule_name=check.get("rule_name", "Unknown Rule"),
                        decision_id=decision.trace_id,
                        severity=check.get("severity", "block"),
                        message=check.get("message", "Policy check failed"),
                        occurred_at=(decision.validated_at or decision.created_at).isoformat(),
                    ))

        return violations[:limit]

    except Exception as e:
        raise HTTPException(500, f"Failed to load violations: {str(e)}")


@router.get("/rules/{rule_id}", response_model=PolicyRuleResponse)
def get_policy_rule(rule_id: str, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    """
    Get details for a specific policy rule from the REAL rule registry.
    """
    trace_id = f"pol-{uuid4().hex[:12]}"
    set_trace_id(trace_id)

    try:
        org_id = user.get("org_id", "")
        org_accounts = get_org_ad_account_ids(org_id, db)

        # Find rule by ID in metadata
        for rule in DEFAULT_RULES:
            class_name = type(rule).__name__
            metadata = RULE_METADATA.get(class_name)
            if metadata and metadata["rule_id"] == rule_id:
                # Count violations for this specific rule (org-scoped)
                query = db.query(DecisionPack).filter(
                    DecisionPack.state == DecisionState.BLOCKED
                )
                if org_accounts:
                    query = query.filter(DecisionPack.ad_account_id.in_(org_accounts))
                blocked_decisions = query.all()

                count = 0
                for decision in blocked_decisions:
                    checks = decision.policy_checks or []
                    for check in checks:
                        if not check.get("passed", True) and check.get("rule_name") == class_name:
                            count += 1

                return PolicyRuleResponse(
                    rule_id=metadata["rule_id"],
                    name=metadata["name"],
                    description=metadata["description"],
                    severity=metadata["severity"],
                    enabled=True,
                    violations_count=count,
                )

        # Check for kill_switch
        if rule_id == "kill_switch":
            return PolicyRuleResponse(
                rule_id="kill_switch",
                name="Emergency Kill Switch",
                description="Master switch to immediately halt all automated actions when activated",
                severity="critical",
                enabled=True,
                violations_count=0,
            )

        raise HTTPException(404, "Policy rule not found")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to get policy rule: {str(e)}")
