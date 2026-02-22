"""
CP5 Test Suite — Policy Engine
DoD:
  - validate() returns a ValidationResult
  - Budget change >20% is blocked by BudgetDeltaRule
  - Second change within 24h is blocked by CooldownLockRule
  - Learning phase protection blocks changes unless CPA > 3x target
  - Direct edit of active ad is blocked by NoDirectEditActiveAdRule
  - All 5 deliberately injected violations are caught
"""
import pytest
from datetime import datetime, timedelta
from src.utils.logging_config import setup_logging, set_trace_id
from src.core import PolicyEngine, LockStore
from src.schemas.policy import ActionRequest, ValidationResult

setup_logging()


@pytest.fixture
def engine():
    """PolicyEngine with fresh lock store for each test."""
    return PolicyEngine()


def test_returns_validation_result(engine):
    """validate() must return a ValidationResult instance."""
    set_trace_id("cp5-test-type")
    request = ActionRequest(
        action_type="budget_change",
        entity_id="adset_123",
        entity_type="adset",
        payload={"current_budget": 100, "new_budget": 110},
        trace_id="test-trace",
    )
    result = engine.validate(request)
    assert isinstance(result, ValidationResult)


def test_budget_within_20pct_approved(engine):
    """Budget change within ±20% should be approved and lock acquired."""
    set_trace_id("cp5-test-budget-ok")
    request = ActionRequest(
        action_type="budget_change",
        entity_id="adset_200",
        entity_type="adset",
        payload={"current_budget": 100, "new_budget": 115},  # 15% increase
        trace_id="test-trace",
    )
    result = engine.validate(request)
    assert result.approved is True
    assert result.lock_acquired is True
    assert len(result.blocking_violations()) == 0


def test_budget_exceeding_20pct_blocked(engine):
    """Budget change >20% should be blocked by BudgetDeltaRule."""
    set_trace_id("cp5-test-budget-block")
    request = ActionRequest(
        action_type="budget_change",
        entity_id="adset_300",
        entity_type="adset",
        payload={"current_budget": 100, "new_budget": 150},  # 50% increase
        trace_id="test-trace",
    )
    result = engine.validate(request)
    assert result.approved is False
    assert result.lock_acquired is False
    assert len(result.blocking_violations()) == 1
    assert result.blocking_violations()[0].rule_name == "BudgetDeltaRule"


def test_cooldown_blocks_second_change(engine):
    """Second change on same entity within 24h should be blocked by CooldownLockRule."""
    set_trace_id("cp5-test-cooldown")
    # First change — approved
    request1 = ActionRequest(
        action_type="budget_change",
        entity_id="adset_400",
        entity_type="adset",
        payload={"current_budget": 100, "new_budget": 110},
        trace_id="trace-1",
    )
    result1 = engine.validate(request1)
    assert result1.approved is True
    assert result1.lock_acquired is True

    # Second change on same entity — blocked
    request2 = ActionRequest(
        action_type="budget_change",
        entity_id="adset_400",
        entity_type="adset",
        payload={"current_budget": 110, "new_budget": 120},
        trace_id="trace-2",
    )
    result2 = engine.validate(request2)
    assert result2.approved is False
    assert len(result2.blocking_violations()) == 1
    assert result2.blocking_violations()[0].rule_name == "CooldownLockRule"


def test_cooldown_expires_allows_change(engine):
    """After releasing the lock, a new change should be approved."""
    set_trace_id("cp5-test-cooldown-expired")
    entity_id = "adset_500"

    # First change
    request1 = ActionRequest(
        action_type="budget_change",
        entity_id=entity_id,
        entity_type="adset",
        payload={"current_budget": 100, "new_budget": 110},
        trace_id="trace-1",
    )
    engine.validate(request1)

    # Manually release lock (simulating 24h expiry or manual override)
    engine.lock_store.release(entity_id)

    # Second change — now approved
    request2 = ActionRequest(
        action_type="budget_change",
        entity_id=entity_id,
        entity_type="adset",
        payload={"current_budget": 110, "new_budget": 120},
        trace_id="trace-2",
    )
    result2 = engine.validate(request2)
    assert result2.approved is True


def test_learning_phase_protection_blocks(engine):
    """AdSet in LEARNING phase with acceptable CPA should be blocked."""
    set_trace_id("cp5-test-learning-block")
    request = ActionRequest(
        action_type="budget_change",
        entity_id="adset_600",
        entity_type="adset",
        payload={
            "current_budget": 100,
            "new_budget": 110,
            "adset_status": "LEARNING",
            "cpa_ratio": 1.5,  # 1.5x target — below 3.0 threshold
        },
        trace_id="test-trace",
    )
    result = engine.validate(request)
    assert result.approved is False
    violations = [v for v in result.blocking_violations() if v.rule_name == "LearningPhaseProtectionRule"]
    assert len(violations) == 1


def test_learning_phase_high_cpa_allowed(engine):
    """AdSet in LEARNING phase with CPA > 3x target should be allowed."""
    set_trace_id("cp5-test-learning-allow")
    request = ActionRequest(
        action_type="budget_change",
        entity_id="adset_700",
        entity_type="adset",
        payload={
            "current_budget": 100,
            "new_budget": 110,
            "adset_status": "LEARNING",
            "cpa_ratio": 4.5,  # 4.5x target — exceeds 3.0 threshold
        },
        trace_id="test-trace",
    )
    result = engine.validate(request)
    # Should pass learning phase rule (but still need to check other rules)
    learning_violations = [v for v in result.violations if v.rule_name == "LearningPhaseProtectionRule"]
    assert len(learning_violations) == 0


def test_no_direct_edit_active_ad_blocked(engine):
    """Direct edit of ACTIVE ad should be blocked by NoDirectEditActiveAdRule."""
    set_trace_id("cp5-test-no-edit")
    request = ActionRequest(
        action_type="creative_edit",
        entity_id="ad_800",
        entity_type="ad",
        payload={"ad_status": "ACTIVE"},
        trace_id="test-trace",
    )
    result = engine.validate(request)
    assert result.approved is False
    violations = [v for v in result.blocking_violations() if v.rule_name == "NoDirectEditActiveAdRule"]
    assert len(violations) == 1


def test_excessive_frequency_warning(engine):
    """High frequency should trigger a warning (not block)."""
    set_trace_id("cp5-test-frequency-warning")
    request = ActionRequest(
        action_type="budget_change",
        entity_id="adset_900",
        entity_type="adset",
        payload={"current_budget": 100, "new_budget": 110, "frequency": 5.2},
        trace_id="test-trace",
    )
    result = engine.validate(request)
    # Should be approved (warning doesn't block)
    assert result.approved is True
    # But should have a warning violation
    warnings = [v for v in result.violations if v.severity == "warning"]
    assert len(warnings) >= 1
    assert any(v.rule_name == "ExcessiveFrequencyWarningRule" for v in warnings)


def test_all_violations_injected_are_caught(engine):
    """Test that all 5 rule types can be triggered."""
    set_trace_id("cp5-test-all-violations")

    # 1. BudgetDeltaRule
    r1 = engine.validate(
        ActionRequest(
            action_type="budget_change",
            entity_id="test1",
            entity_type="adset",
            payload={"current_budget": 100, "new_budget": 200},
            trace_id="t1",
        )
    )
    assert any(v.rule_name == "BudgetDeltaRule" for v in r1.violations)

    # 2. CooldownLockRule (acquire lock first)
    engine.validate(
        ActionRequest(
            action_type="budget_change",
            entity_id="test2",
            entity_type="adset",
            payload={"current_budget": 100, "new_budget": 110},
            trace_id="t2a",
        )
    )
    r2 = engine.validate(
        ActionRequest(
            action_type="budget_change",
            entity_id="test2",
            entity_type="adset",
            payload={"current_budget": 110, "new_budget": 120},
            trace_id="t2b",
        )
    )
    assert any(v.rule_name == "CooldownLockRule" for v in r2.violations)

    # 3. LearningPhaseProtectionRule
    r3 = engine.validate(
        ActionRequest(
            action_type="budget_change",
            entity_id="test3",
            entity_type="adset",
            payload={
                "current_budget": 100,
                "new_budget": 110,
                "adset_status": "LEARNING",
                "cpa_ratio": 1.0,
            },
            trace_id="t3",
        )
    )
    assert any(v.rule_name == "LearningPhaseProtectionRule" for v in r3.violations)

    # 4. NoDirectEditActiveAdRule
    r4 = engine.validate(
        ActionRequest(
            action_type="creative_edit",
            entity_id="test4",
            entity_type="ad",
            payload={"ad_status": "ACTIVE"},
            trace_id="t4",
        )
    )
    assert any(v.rule_name == "NoDirectEditActiveAdRule" for v in r4.violations)

    # 5. ExcessiveFrequencyWarningRule
    r5 = engine.validate(
        ActionRequest(
            action_type="budget_change",
            entity_id="test5",
            entity_type="adset",
            payload={"current_budget": 100, "new_budget": 110, "frequency": 4.0},
            trace_id="t5",
        )
    )
    assert any(v.rule_name == "ExcessiveFrequencyWarningRule" for v in r5.violations)


if __name__ == "__main__":
    set_trace_id("cp5-manual-run")
    e = PolicyEngine()

    # Test 1: Approved change
    req = ActionRequest(
        action_type="budget_change",
        entity_id="adset_demo",
        entity_type="adset",
        payload={"current_budget": 100, "new_budget": 115},
        trace_id="demo-trace",
    )
    res = e.validate(req)
    print(f"Request: {req.action_type} on {req.entity_id}")
    print(f"Approved: {res.approved}")
    print(f"Lock acquired: {res.lock_acquired}")
    print(f"Cooldown until: {res.cooldown_until}")
    print(f"Violations: {len(res.violations)}")
    for v in res.violations:
        print(f"  [{v.severity.upper()}] {v.rule_name}: {v.message}")
