"""
Decision Pack service - orchestrates the decision lifecycle.
"""
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from src.core.operator import Operator
from src.core.policy_engine import PolicyEngine
from backend.src.database.models import AdAccount, DecisionPack, DecisionState, MetaConnection, User
from src.schemas.operator import DecisionPack as CoreDecisionPack
from src.schemas.policy import ActionRequest
from src.utils.logging_config import get_trace_id, logger, set_trace_id


class DecisionService:
    """Manages decision pack lifecycle and state transitions."""

    def __init__(self, db: Session):
        self.db = db
        self.policy_engine = PolicyEngine()

    def create_draft(
        self,
        ad_account_id: UUID,
        user_id: UUID,
        action_type: str,
        entity_type: str,
        entity_id: str,
        entity_name: str,
        payload: dict,
        rationale: str,
        source: str = "Manual",
    ) -> DecisionPack:
        """Create a new draft decision."""
        trace_id = f"draft-{uuid4().hex[:12]}"
        set_trace_id(trace_id)

        # Build action request
        action_request = ActionRequest(
            action_type=action_type,
            entity_id=entity_id,
            entity_type=entity_type,
            payload=payload,
            trace_id=trace_id,
        )

        # Create decision pack
        decision = DecisionPack(
            ad_account_id=ad_account_id,
            created_by_user_id=user_id,
            state=DecisionState.DRAFT,
            trace_id=trace_id,
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            action_request=action_request.model_dump(mode="json"),
            rationale=rationale,
            source=source,
            before_snapshot=payload.get("before", {}),
            after_proposal=payload.get("after", {}),
        )

        self.db.add(decision)
        self.db.commit()
        self.db.refresh(decision)

        logger.info(
            f"DECISION_DRAFT_CREATED | decision_id={decision.id} | trace_id={trace_id}"
        )
        return decision

    def validate_decision(self, decision_id: UUID) -> DecisionPack:
        """Run policy validation on a draft."""
        decision = self.db.query(DecisionPack).filter(DecisionPack.id == decision_id).first()
        if not decision:
            raise ValueError(f"Decision {decision_id} not found")

        if decision.state != DecisionState.DRAFT:
            raise ValueError(f"Can only validate DRAFT decisions, current state: {decision.state}")

        set_trace_id(decision.trace_id)
        decision.state = DecisionState.VALIDATING
        self.db.commit()

        # Build ActionRequest from stored data
        action_request = ActionRequest.model_validate(decision.action_request)

        # Sprint 5: Build PolicyContext from entity memory (if exists)
        context = None
        try:
            from backend.src.database.models import EntityMemory
            from src.core.policy_engine import PolicyContext
            entity_mem = self.db.query(EntityMemory).filter(
                EntityMemory.entity_type == decision.entity_type,
                EntityMemory.entity_id == decision.entity_id,
            ).first()
            if entity_mem:
                context = PolicyContext(
                    trust_score=entity_mem.trust_score or 50.0,
                    volatility=entity_mem.volatility_json or {},
                    recent_outcomes=[entity_mem.last_outcome_label.value] if entity_mem.last_outcome_label else [],
                )
        except Exception:
            pass  # Graceful fallback: no context = default thresholds

        # Run policy validation
        policy_result = self.policy_engine.validate(action_request, context=context)

        # Store result
        decision.policy_result = policy_result.model_dump(mode="json")
        decision.policy_checks = [
            {
                "rule_name": v.rule_name,
                "passed": False,
                "severity": v.severity,
                "message": v.message,
            }
            for v in policy_result.violations
        ]

        # Update state
        if policy_result.approved:
            decision.state = DecisionState.READY
        else:
            decision.state = DecisionState.BLOCKED

        decision.validated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(decision)

        logger.info(
            f"DECISION_VALIDATED | decision_id={decision_id} | approved={policy_result.approved}"
        )
        return decision

    def request_approval(self, decision_id: UUID) -> DecisionPack:
        """Submit a READY decision for approval."""
        decision = self.db.query(DecisionPack).filter(DecisionPack.id == decision_id).first()
        if not decision:
            raise ValueError(f"Decision {decision_id} not found")

        if decision.state != DecisionState.READY:
            raise ValueError(f"Can only request approval for READY decisions, current state: {decision.state}")

        decision.state = DecisionState.PENDING_APPROVAL
        decision.expires_at = datetime.utcnow() + timedelta(hours=24)
        self.db.commit()
        self.db.refresh(decision)

        logger.info(f"DECISION_APPROVAL_REQUESTED | decision_id={decision_id}")
        return decision

    def approve_decision(self, decision_id: UUID, approver_user_id: UUID) -> DecisionPack:
        """Approve a pending decision."""
        decision = self.db.query(DecisionPack).filter(DecisionPack.id == decision_id).first()
        if not decision:
            raise ValueError(f"Decision {decision_id} not found")

        if decision.state != DecisionState.PENDING_APPROVAL:
            raise ValueError(f"Can only approve PENDING decisions, current state: {decision.state}")

        decision.state = DecisionState.APPROVED
        decision.approved_by_user_id = approver_user_id
        decision.approved_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(decision)

        logger.info(
            f"DECISION_APPROVED | decision_id={decision_id} | approver={approver_user_id}"
        )
        return decision

    def reject_decision(self, decision_id: UUID, reason: str) -> DecisionPack:
        """Reject a pending decision."""
        decision = self.db.query(DecisionPack).filter(DecisionPack.id == decision_id).first()
        if not decision:
            raise ValueError(f"Decision {decision_id} not found")

        if decision.state != DecisionState.PENDING_APPROVAL:
            raise ValueError(f"Can only reject PENDING decisions, current state: {decision.state}")

        decision.state = DecisionState.REJECTED
        decision.rejected_at = datetime.utcnow()
        decision.execution_result = {"rejected_reason": reason}
        self.db.commit()
        self.db.refresh(decision)

        logger.info(f"DECISION_REJECTED | decision_id={decision_id} | reason={reason}")
        return decision

    def execute_decision(
        self,
        decision_id: UUID,
        operator_armed: bool,
        dry_run: bool = False
    ) -> DecisionPack:
        """Execute an approved decision via Operator."""
        decision = self.db.query(DecisionPack).filter(DecisionPack.id == decision_id).first()
        if not decision:
            raise ValueError(f"Decision {decision_id} not found")

        if decision.state != DecisionState.APPROVED:
            raise ValueError(f"Can only execute APPROVED decisions, current state: {decision.state}")

        if not operator_armed and not dry_run:
            raise ValueError("Operator Armed must be ON to execute live changes")

        set_trace_id(decision.trace_id)

        # Update state
        decision.state = DecisionState.EXECUTING
        self.db.commit()

        try:
            # Build CoreDecisionPack for Operator
            action_request = ActionRequest.model_validate(decision.action_request)
            core_pack = CoreDecisionPack(
                action_request=action_request,
                rationale=decision.rationale or "",
                source=decision.source or "UI",
            )

            # Execute via Operator
            operator = Operator(dry_run=dry_run)
            exec_log = operator.execute(core_pack)

            # Store execution result
            decision.execution_result = {
                "success": exec_log.action_result.success if exec_log.action_result else False,
                "api_response": exec_log.action_result.api_response if exec_log.action_result else {},
                "error_message": exec_log.action_result.error_message if exec_log.action_result else "",
                "dry_run": dry_run,
            }

            # Update state
            if exec_log.action_result and exec_log.action_result.success:
                decision.state = DecisionState.EXECUTED
            else:
                decision.state = DecisionState.FAILED

            decision.executed_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(decision)

            # Sprint 5: Capture outcome baselines + schedule after-capture
            if decision.state == DecisionState.EXECUTED:
                try:
                    from backend.src.services.outcome_service import OutcomeCollector
                    ad_account = self.db.query(AdAccount).filter(
                        AdAccount.id == decision.ad_account_id
                    ).first()
                    connection = self.db.query(MetaConnection).filter(
                        MetaConnection.id == ad_account.connection_id
                    ).first() if ad_account else None
                    if connection:
                        OutcomeCollector(self.db).capture_before(
                            decision, connection.org_id, dry_run=dry_run
                        )
                        self.db.commit()
                except Exception as e:
                    logger.warning(
                        f"OUTCOME_CAPTURE_BEFORE_FAILED | {decision_id} | {e}"
                    )

            logger.info(
                f"DECISION_EXECUTED | decision_id={decision_id} | success={decision.state == DecisionState.EXECUTED} | dry_run={dry_run}"
            )
            return decision

        except Exception as e:
            decision.state = DecisionState.FAILED
            decision.execution_result = {"error": str(e)}
            self.db.commit()
            logger.error(f"DECISION_EXECUTION_FAILED | decision_id={decision_id} | error={str(e)}")
            raise

    def get_decision(self, decision_id: UUID) -> Optional[DecisionPack]:
        """Get a decision by ID."""
        return self.db.query(DecisionPack).filter(DecisionPack.id == decision_id).first()

    def list_decisions(
        self,
        ad_account_id: Optional[UUID] = None,
        state: Optional[DecisionState] = None,
        limit: int = 50,
        org_ad_account_ids: Optional[List[UUID]] = None,
    ) -> List[DecisionPack]:
        """List decisions with filters. Scoped to org via org_ad_account_ids."""
        query = self.db.query(DecisionPack)

        # Multi-tenant: scope to org's ad accounts
        if org_ad_account_ids is not None:
            if not org_ad_account_ids:
                return []  # Org has no accounts → no decisions
            query = query.filter(DecisionPack.ad_account_id.in_(org_ad_account_ids))

        if ad_account_id:
            query = query.filter(DecisionPack.ad_account_id == ad_account_id)
        if state:
            query = query.filter(DecisionPack.state == state)

        return query.order_by(DecisionPack.created_at.desc()).limit(limit).all()
