"""
CP7 Test Suite — Operator
DoD:
  - execute() returns an ExecutionLog
  - Policy-blocked actions are NOT executed
  - Approved actions are executed (dry-run mode)
  - Decision memory is persisted
  - Kill switch blocks all executions
  - Rollback reverses last action
"""
import os
import tempfile
import pytest
from src.utils.logging_config import setup_logging, set_trace_id
from src.core.operator import Operator, KillSwitchActive
from src.schemas.operator import DecisionPack, ExecutionLog
from src.schemas.policy import ActionRequest

setup_logging()


@pytest.fixture
def temp_memory_file():
    """Temporary decision memory file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".jsonl") as f:
        path = f.name
    yield path
    # Cleanup
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def operator(temp_memory_file):
    """Operator in DRY_RUN mode with isolated decision memory."""
    return Operator(dry_run=True, decision_memory_path=temp_memory_file)


def test_returns_execution_log(operator):
    """execute() must return an ExecutionLog instance."""
    set_trace_id("cp7-test-type")
    decision_pack = DecisionPack(
        action_request=ActionRequest(
            action_type="budget_change",
            entity_id="adset_test",
            entity_type="adset",
            payload={"current_budget": 100, "new_budget": 110},
            trace_id="test-trace",
        ),
        rationale="Test execution",
        source="test",
    )
    result = operator.execute(decision_pack)
    assert isinstance(result, ExecutionLog)


def test_policy_blocked_not_executed(operator):
    """Actions blocked by policy should NOT be executed."""
    set_trace_id("cp7-test-policy-block")
    # Request with >20% budget change (will be blocked by BudgetDeltaRule)
    decision_pack = DecisionPack(
        action_request=ActionRequest(
            action_type="budget_change",
            entity_id="adset_blocked",
            entity_type="adset",
            payload={"current_budget": 100, "new_budget": 200},  # 100% increase
            trace_id="test-blocked",
        ),
        rationale="Excessive budget increase",
        source="test",
    )
    result = operator.execute(decision_pack)

    # Should be blocked by policy
    assert result.policy_result.approved is False
    assert len(result.policy_result.blocking_violations()) > 0
    # Should NOT have action result (not executed)
    assert result.action_result is None


def test_approved_action_executed_dry_run(operator):
    """Approved actions should be executed in dry-run mode."""
    set_trace_id("cp7-test-approved")
    decision_pack = DecisionPack(
        action_request=ActionRequest(
            action_type="budget_change",
            entity_id="adset_approved",
            entity_type="adset",
            payload={"current_budget": 100, "new_budget": 115},  # 15% increase
            trace_id="test-approved",
        ),
        rationale="Safe budget optimization",
        source="SaturationEngine",
    )
    result = operator.execute(decision_pack)

    # Should be approved by policy
    assert result.policy_result.approved is True
    # Should have action result (executed)
    assert result.action_result is not None
    assert result.action_result.success is True
    assert result.action_result.dry_run is True  # In dry-run mode


def test_decision_memory_persisted(operator, temp_memory_file):
    """Execution logs should be persisted to decision memory."""
    set_trace_id("cp7-test-memory")
    decision_pack = DecisionPack(
        action_request=ActionRequest(
            action_type="adset_pause",
            entity_id="adset_pause_test",
            entity_type="adset",
            payload={},
            trace_id="test-memory",
        ),
        rationale="Pause saturated adset",
        source="test",
    )
    operator.execute(decision_pack)

    # Check memory file was created and has content
    assert os.path.exists(temp_memory_file)
    history = operator.get_decision_history(limit=10)
    assert len(history) >= 1
    assert history[-1].execution_log.decision_pack.action_request.entity_id == "adset_pause_test"


def test_kill_switch_blocks_execution(operator):
    """Kill switch should block all executions."""
    set_trace_id("cp7-test-kill-switch")
    operator.activate_kill_switch()
    assert operator.is_kill_switch_active() is True

    decision_pack = DecisionPack(
        action_request=ActionRequest(
            action_type="budget_change",
            entity_id="adset_kill",
            entity_type="adset",
            payload={"current_budget": 100, "new_budget": 110},
            trace_id="test-kill",
        ),
        rationale="Should be blocked by kill switch",
        source="test",
    )

    # Should raise KillSwitchActive exception
    with pytest.raises(KillSwitchActive):
        operator.execute(decision_pack)

    # Deactivate and try again
    operator.deactivate_kill_switch()
    assert operator.is_kill_switch_active() is False
    # Now should work
    result = operator.execute(decision_pack)
    assert result.policy_result.approved is True


def test_rollback_reverses_action(operator):
    """Rollback should reverse the last executed action."""
    set_trace_id("cp7-test-rollback")

    # Execute a budget change
    original_pack = DecisionPack(
        action_request=ActionRequest(
            action_type="budget_change",
            entity_id="adset_rollback",
            entity_type="adset",
            payload={"current_budget": 100, "new_budget": 120},
            trace_id="test-rollback-original",
        ),
        rationale="Test rollback",
        source="test",
    )
    original_result = operator.execute(original_pack)
    assert original_result.action_result.success is True

    # Rollback
    rollback_result = operator.rollback_last()
    assert rollback_result.action_result.success is True
    # Rollback should restore budget from 120 → 100
    assert rollback_result.decision_pack.action_request.payload["new_budget"] == 100


def test_multiple_executions_history(operator):
    """Multiple executions should be tracked in history."""
    set_trace_id("cp7-test-multi-exec")

    for i in range(5):
        decision_pack = DecisionPack(
            action_request=ActionRequest(
                action_type="budget_change",
                entity_id=f"adset_{i}",
                entity_type="adset",
                payload={"current_budget": 100, "new_budget": 110},
                trace_id=f"test-multi-{i}",
            ),
            rationale=f"Execution {i}",
            source="test",
        )
        operator.execute(decision_pack)

    history = operator.get_decision_history(limit=10)
    assert len(history) >= 5


if __name__ == "__main__":
    set_trace_id("cp7-manual-run")
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".jsonl") as f:
        temp_path = f.name

    op = Operator(dry_run=True, decision_memory_path=temp_path)

    # Test execution
    pack = DecisionPack(
        action_request=ActionRequest(
            action_type="budget_change",
            entity_id="adset_demo",
            entity_type="adset",
            payload={"current_budget": 50, "new_budget": 55},
            trace_id="demo",
        ),
        rationale="Scaling fresh creative identified by CP4",
        source="SaturationEngine",
    )

    result = op.execute(pack)
    print("\n=== EXECUTION LOG ===")
    print(f"Approved: {result.policy_result.approved}")
    print(f"Executed: {result.action_result is not None}")
    if result.action_result:
        print(f"Success: {result.action_result.success}")
        print(f"Dry Run: {result.action_result.dry_run}")
    print(f"Stored at: {result.executed_at}")
    print(f"\nDecision Memory: {op.decision_memory_path}")
    print(f"History entries: {len(op.get_decision_history())}")

    # Cleanup
    os.remove(temp_path)
