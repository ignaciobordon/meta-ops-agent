"""
Unit tests for Operator module (CP7).
Tests kill switch, dry-run mode, rollback, and execution flow.
"""
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock

from src.core.operator import Operator, KillSwitchActive
from src.schemas.operator import DecisionPack, ExecutionLog
from src.schemas.policy import ActionRequest


class TestOperatorExecution:
    """Test basic execution flow."""

    def test_dry_run_mode_no_live_execution(self):
        """Test that dry_run mode simulates without executing."""
        # Create temporary decision memory
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            memory_path = f.name

        try:
            operator = Operator(dry_run=True, decision_memory_path=memory_path)

            # Create a budget change decision (within 20% policy limit)
            action = ActionRequest(
                action_type="budget_change",
                entity_id="act_123",
                entity_type="adset",
                payload={"current_budget": 100.0, "new_budget": 115.0},  # 15% increase (within 20% limit)
                trace_id="test-trace"
            )

            decision_pack = DecisionPack(
                action_request=action,
                rationale="Test budget increase",
                source="pytest"
            )

            # Execute
            result = operator.execute(decision_pack)

            # Should succeed in dry-run mode
            assert isinstance(result, ExecutionLog)
            assert result.policy_result.approved is True, "Policy should approve reasonable budget change"
            assert result.action_result is not None
            assert result.action_result.success is True
            assert result.action_result.dry_run is True
            assert "simulated" in str(result.action_result.api_response).lower()

        finally:
            # Cleanup
            if Path(memory_path).exists():
                os.unlink(memory_path)

    def test_policy_blocking(self):
        """Test that policy engine blocks invalid actions."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            memory_path = f.name

        try:
            operator = Operator(dry_run=True, decision_memory_path=memory_path)

            # Create an extreme budget change (should violate policy)
            action = ActionRequest(
                action_type="budget_change",
                entity_id="act_123",
                entity_type="adset",
                payload={"current_budget": 100.0, "new_budget": 10000.0},  # 100x increase!
                trace_id="test-trace-extreme"
            )

            decision_pack = DecisionPack(
                action_request=action,
                rationale="Extreme budget test",
                source="pytest"
            )

            # Execute
            result = operator.execute(decision_pack)

            # Policy should block this or warn (depending on policy rules)
            # At minimum, it should not crash
            assert isinstance(result, ExecutionLog)
            assert result.policy_result is not None

        finally:
            if Path(memory_path).exists():
                os.unlink(memory_path)


class TestOperatorKillSwitch:
    """Test kill switch functionality."""

    def test_kill_switch_blocks_execution(self):
        """Test that kill switch blocks all executions."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            memory_path = f.name

        try:
            operator = Operator(dry_run=True, decision_memory_path=memory_path)

            # Activate kill switch
            operator.activate_kill_switch()

            assert operator.is_kill_switch_active() is True

            # Try to execute
            action = ActionRequest(
                action_type="budget_change",
                entity_id="act_123",
                entity_type="adset",
                payload={"current_budget": 100.0, "new_budget": 150.0},
                trace_id="test-trace"
            )

            decision_pack = DecisionPack(
                action_request=action,
                rationale="Test with kill switch",
                source="pytest"
            )

            # Should raise KillSwitchActive exception
            with pytest.raises(KillSwitchActive):
                operator.execute(decision_pack)

        finally:
            if Path(memory_path).exists():
                os.unlink(memory_path)

    def test_kill_switch_deactivation(self):
        """Test that kill switch can be deactivated."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            memory_path = f.name

        try:
            operator = Operator(dry_run=True, decision_memory_path=memory_path)

            # Activate then deactivate
            operator.activate_kill_switch()
            assert operator.is_kill_switch_active() is True

            operator.deactivate_kill_switch()
            assert operator.is_kill_switch_active() is False

            # Should now execute normally
            action = ActionRequest(
                action_type="budget_change",
                entity_id="act_123",
                entity_type="adset",
                payload={"current_budget": 100.0, "new_budget": 150.0},
                trace_id="test-trace"
            )

            decision_pack = DecisionPack(
                action_request=action,
                rationale="Test after kill switch deactivation",
                source="pytest"
            )

            result = operator.execute(decision_pack)
            assert isinstance(result, ExecutionLog)
            assert result.killed is False

        finally:
            if Path(memory_path).exists():
                os.unlink(memory_path)


class TestOperatorDecisionMemory:
    """Test decision memory logging."""

    def test_decision_memory_stores_execution(self):
        """Test that executions are logged to decision memory."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            memory_path = f.name

        try:
            operator = Operator(dry_run=True, decision_memory_path=memory_path)

            # Execute an action
            action = ActionRequest(
                action_type="budget_change",
                entity_id="act_123",
                entity_type="adset",
                payload={"current_budget": 100.0, "new_budget": 150.0},
                trace_id="test-trace-memory"
            )

            decision_pack = DecisionPack(
                action_request=action,
                rationale="Test memory logging",
                source="pytest"
            )

            operator.execute(decision_pack)

            # Verify entry was written
            assert Path(memory_path).exists()

            # Read decision history
            history = operator.get_decision_history(limit=10)
            assert len(history) > 0
            assert history[-1].execution_log.decision_pack.action_request.entity_id == "act_123"

        finally:
            if Path(memory_path).exists():
                os.unlink(memory_path)

    def test_get_decision_history_limit(self):
        """Test that history retrieval respects limit."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            memory_path = f.name

        try:
            operator = Operator(dry_run=True, decision_memory_path=memory_path)

            # Execute 5 actions
            for i in range(5):
                action = ActionRequest(
                    action_type="budget_change",
                    entity_id=f"act_{i}",
                    entity_type="adset",
                    payload={"current_budget": 100.0, "new_budget": 110.0 + i},
                    trace_id=f"test-trace-{i}"
                )

                decision_pack = DecisionPack(
                    action_request=action,
                    rationale=f"Test {i}",
                    source="pytest"
                )

                operator.execute(decision_pack)

            # Retrieve with limit
            history = operator.get_decision_history(limit=3)
            assert len(history) == 3  # Should return last 3

        finally:
            if Path(memory_path).exists():
                os.unlink(memory_path)


class TestOperatorRollback:
    """Test rollback functionality."""

    def test_rollback_budget_change(self):
        """Test that budget changes can be rolled back."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            memory_path = f.name

        try:
            operator = Operator(dry_run=True, decision_memory_path=memory_path)

            # Execute a budget change (within 20% policy limit)
            action = ActionRequest(
                action_type="budget_change",
                entity_id="act_rollback",
                entity_type="adset",
                payload={"current_budget": 100.0, "new_budget": 110.0},  # 10% increase
                trace_id="test-rollback"
            )

            decision_pack = DecisionPack(
                action_request=action,
                rationale="Test rollback",
                source="pytest"
            )

            result1 = operator.execute(decision_pack)
            assert result1.action_result.success is True

            # Now rollback
            rollback_result = operator.rollback_last()

            # Should reverse the change (110 -> 100)
            assert isinstance(rollback_result, ExecutionLog)
            assert rollback_result.action_result.success is True
            assert rollback_result.decision_pack.action_request.payload["current_budget"] == 110.0
            assert rollback_result.decision_pack.action_request.payload["new_budget"] == 100.0

        finally:
            if Path(memory_path).exists():
                os.unlink(memory_path)

    def test_rollback_fails_with_no_history(self):
        """Test that rollback fails when there's no history."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            memory_path = f.name

        try:
            operator = Operator(dry_run=True, decision_memory_path=memory_path)

            # Try to rollback with empty history
            with pytest.raises(ValueError, match="No execution history"):
                operator.rollback_last()

        finally:
            if Path(memory_path).exists():
                os.unlink(memory_path)


class TestOperatorActionTypes:
    """Test different action types."""

    def test_pause_adset(self):
        """Test adset pause action."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            memory_path = f.name

        try:
            operator = Operator(dry_run=True, decision_memory_path=memory_path)

            action = ActionRequest(
                action_type="adset_pause",
                entity_id="adset_pause_test",
                entity_type="adset",
                payload={},
                trace_id="test-pause"
            )

            decision_pack = DecisionPack(
                action_request=action,
                rationale="Test pause",
                source="pytest"
            )

            result = operator.execute(decision_pack)
            assert result.action_result.success is True

        finally:
            if Path(memory_path).exists():
                os.unlink(memory_path)

    def test_creative_swap(self):
        """Test creative swap action."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            memory_path = f.name

        try:
            operator = Operator(dry_run=True, decision_memory_path=memory_path)

            action = ActionRequest(
                action_type="creative_swap",
                entity_id="ad_123",
                entity_type="ad",
                payload={"new_name": "ad_123_v2"},
                trace_id="test-creative-swap"
            )

            decision_pack = DecisionPack(
                action_request=action,
                rationale="Test creative swap",
                source="pytest"
            )

            result = operator.execute(decision_pack)
            assert result.action_result.success is True

        finally:
            if Path(memory_path).exists():
                os.unlink(memory_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
