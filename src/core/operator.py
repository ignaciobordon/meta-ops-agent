"""
CP7 — Operator
The execution layer that validates decisions via PolicyEngine,
executes approved actions via Meta API, and maintains DecisionMemory audit trail.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.adapters.meta_api import MetaAPIClient
from src.core.policy_engine import PolicyEngine
from src.schemas.operator import (
    ActionResult,
    DecisionMemoryEntry,
    DecisionPack,
    ExecutionLog,
)
from src.schemas.policy import ActionRequest
from src.utils.logging_config import get_trace_id, logger


class KillSwitchActive(Exception):
    """Raised when kill switch is triggered."""

    pass


class Operator:
    """
    Orchestrates execution of decisions:
    1. Validates via PolicyEngine
    2. Executes via MetaAPIClient
    3. Logs to DecisionMemory

    Supports DRY_RUN mode (default) and kill switch for emergency stop.
    """

    def __init__(
        self,
        policy_engine: Optional[PolicyEngine] = None,
        meta_client: Optional[MetaAPIClient] = None,
        dry_run: bool = True,
        decision_memory_path: str = "./decision_memory.jsonl",
    ):
        self.policy_engine = policy_engine or PolicyEngine()
        self.meta_client = meta_client or MetaAPIClient(dry_run=dry_run)
        self.dry_run = dry_run
        self.decision_memory_path = Path(decision_memory_path)
        self._kill_switch_active = False

        logger.info(
            f"OPERATOR_INITIALIZED | dry_run={dry_run} "
            f"| memory={self.decision_memory_path}"
        )

    # ── Execution ─────────────────────────────────────────────────────────────

    def execute(self, decision_pack: DecisionPack, bypass_policy: bool = False) -> ExecutionLog:
        """
        Execute a decision pack:
        1. Validate with PolicyEngine (unless bypass_policy=True)
        2. If approved, execute via Meta API
        3. Log to DecisionMemory
        4. Return ExecutionLog

        Args:
            decision_pack: The action to execute
            bypass_policy: If True, skip policy validation (used for rollbacks)

        Raises:
            KillSwitchActive: If kill switch is engaged
        """
        if self._kill_switch_active:
            raise KillSwitchActive("Kill switch is active. All executions blocked.")

        trace_id = get_trace_id()
        logger.info(
            f"OPERATOR_EXEC_STARTED | trace_id={trace_id} "
            f"| action={decision_pack.action_request.action_type} "
            f"| entity={decision_pack.action_request.entity_id}"
            f"{' | bypass_policy=True' if bypass_policy else ''}"
        )

        # Step 1: Policy validation (unless bypassed for rollback)
        if bypass_policy:
            from src.schemas.policy import ValidationResult
            policy_result = ValidationResult(
                approved=True,
                action_request=decision_pack.action_request,
                violations=[],
                lock_acquired=False,
            )
            logger.info("OPERATOR_POLICY_BYPASSED | reason=rollback_operation")
        else:
            policy_result = self.policy_engine.validate(decision_pack.action_request)

        action_result: Optional[ActionResult] = None

        if not policy_result.approved:
            logger.warning(
                f"OPERATOR_POLICY_BLOCKED | violations={len(policy_result.blocking_violations())}"
            )
        else:
            # Step 2: Execute action
            action_result = self._execute_action(decision_pack.action_request)

        # Step 3: Create execution log
        exec_log = ExecutionLog(
            decision_pack=decision_pack,
            policy_result=policy_result,
            action_result=action_result,
            trace_id=trace_id,
            killed=self._kill_switch_active,
        )

        # Step 4: Store in decision memory
        self._store_in_memory(exec_log)

        logger.info(
            f"OPERATOR_EXEC_DONE | approved={policy_result.approved} "
            f"| executed={action_result is not None} "
            f"| success={action_result.success if action_result else False}"
        )

        return exec_log

    def _execute_action(self, request) -> ActionResult:
        """Route action to appropriate Meta API method."""
        try:
            if request.action_type == "budget_change":
                response = self.meta_client.update_adset_budget(
                    adset_id=request.entity_id,
                    new_budget=request.payload["new_budget"],
                    current_budget=request.payload["current_budget"],
                )
                return ActionResult(
                    success=True, api_response=response, dry_run=self.dry_run
                )

            elif request.action_type == "adset_pause":
                response = self.meta_client.pause_adset(adset_id=request.entity_id)
                return ActionResult(
                    success=True, api_response=response, dry_run=self.dry_run
                )

            elif request.action_type == "creative_swap":
                # Duplicate ad (per NoDirectEditActiveAdRule)
                response = self.meta_client.duplicate_ad(
                    ad_id=request.entity_id,
                    new_name=request.payload.get("new_name", f"{request.entity_id}_v2"),
                )
                return ActionResult(
                    success=True, api_response=response, dry_run=self.dry_run
                )

            else:
                return ActionResult(
                    success=False,
                    error_message=f"Unsupported action_type: {request.action_type}",
                    dry_run=self.dry_run,
                )

        except Exception as e:
            logger.error(f"OPERATOR_EXEC_ERROR | error={str(e)}")
            return ActionResult(success=False, error_message=str(e), dry_run=self.dry_run)

    # ── Decision Memory ───────────────────────────────────────────────────────

    def _store_in_memory(self, exec_log: ExecutionLog):
        """Append execution log to decision memory JSONL file."""
        entry = DecisionMemoryEntry(
            log_id=f"log-{uuid.uuid4().hex[:8]}", execution_log=exec_log
        )

        # Append to JSONL
        with open(self.decision_memory_path, "a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

        logger.info(f"OPERATOR_MEMORY_STORED | log_id={entry.log_id}")

    def get_decision_history(self, limit: int = 50) -> List[DecisionMemoryEntry]:
        """Retrieve recent decision history from memory."""
        if not self.decision_memory_path.exists():
            return []

        entries = []
        with open(self.decision_memory_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entries.append(DecisionMemoryEntry.model_validate_json(line))

        return entries[-limit:]  # Most recent N entries

    # ── Kill Switch ───────────────────────────────────────────────────────────

    def activate_kill_switch(self):
        """Emergency stop: block all future executions."""
        self._kill_switch_active = True
        logger.critical("OPERATOR_KILL_SWITCH_ACTIVATED | all executions blocked")

    def deactivate_kill_switch(self):
        """Re-enable executions after kill switch."""
        self._kill_switch_active = False
        logger.info("OPERATOR_KILL_SWITCH_DEACTIVATED | executions resumed")

    def is_kill_switch_active(self) -> bool:
        """Check kill switch status."""
        return self._kill_switch_active

    # ── Rollback ──────────────────────────────────────────────────────────────

    def rollback_last(self) -> ExecutionLog:
        """
        Rollback the last executed action by reversing it.
        E.g., if last action was budget increase, restore previous budget.
        """
        history = self.get_decision_history(limit=1)
        if not history:
            raise ValueError("No execution history to rollback.")

        last_entry = history[-1]
        last_log = last_entry.execution_log

        if not last_log.action_result or not last_log.action_result.success:
            raise ValueError("Last action did not succeed, nothing to rollback.")

        original_request = last_log.decision_pack.action_request

        # Construct reverse action
        if original_request.action_type == "budget_change":
            rollback_request = ActionRequest(
                action_type="budget_change",
                entity_id=original_request.entity_id,
                entity_type=original_request.entity_type,
                payload={
                    "current_budget": original_request.payload["new_budget"],
                    "new_budget": original_request.payload["current_budget"],
                },
                trace_id=f"rollback-{get_trace_id()}",
            )
            rollback_pack = DecisionPack(
                action_request=rollback_request,
                rationale=f"Rollback of {last_entry.log_id}",
                source="Operator.rollback",
            )
            return self.execute(rollback_pack, bypass_policy=True)

        else:
            raise NotImplementedError(
                f"Rollback not implemented for {original_request.action_type}"
            )
