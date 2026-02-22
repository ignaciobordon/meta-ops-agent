"""
Unit tests for DecisionService (Backend state machine).
Tests all 8 state transitions and validation logic.
"""
import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PostgreSQL UUID type for SQLite compatibility
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

from backend.src.database.models import (
    Base, DecisionState, Organization, MetaConnection, AdAccount, User,
    UserOrgRole, RoleEnum,
)
from backend.src.services.decision_service import DecisionService


# Test database setup
@pytest.fixture(scope="function")
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    org_id = uuid4()
    user_id = uuid4()
    connection_id = uuid4()

    # Create test organization
    org = Organization(
        id=org_id,
        name="Test Org",
        slug="test-org-svc",
        operator_armed=True,
        created_at=datetime.utcnow(),
    )
    session.add(org)

    # Create test user
    user = User(
        id=user_id,
        email="test@example.com",
        name="Test User",
        password_hash="hashed",
        created_at=datetime.utcnow(),
    )
    session.add(user)

    # User role
    role = UserOrgRole(
        id=uuid4(),
        user_id=user_id,
        org_id=org_id,
        role=RoleEnum.ADMIN,
        assigned_at=datetime.utcnow(),
    )
    session.add(role)

    # Create test Meta connection
    connection = MetaConnection(
        id=connection_id,
        org_id=org_id,
        access_token_encrypted="enc_test_token",
        status="active",
        connected_at=datetime.utcnow(),
    )
    session.add(connection)

    # Create test ad account
    ad_account = AdAccount(
        id=uuid4(),
        connection_id=connection_id,
        meta_ad_account_id="act_123456",
        name="Test Ad Account",
        currency="USD",
        synced_at=datetime.utcnow(),
    )
    session.add(ad_account)

    session.commit()

    yield session

    session.close()


class TestDecisionLifecycle:
    """Test complete decision lifecycle (happy path)."""

    def test_full_lifecycle_draft_to_executed(self, db_session):
        """Test complete flow: DRAFT → VALIDATING → READY → PENDING → APPROVED → EXECUTING → EXECUTED"""
        service = DecisionService(db_session)

        # Get test data
        ad_account = db_session.query(AdAccount).first()
        user = db_session.query(User).first()

        # Step 1: Create DRAFT
        decision = service.create_draft(
            ad_account_id=ad_account.id,
            user_id=user.id,
            action_type="budget_change",
            entity_type="adset",
            entity_id="adset_123",
            entity_name="Test Adset",
            payload={"current_budget": 100.0, "new_budget": 110.0},  # 10% increase
            rationale="Test budget increase",
            source="pytest"
        )

        assert decision.state == DecisionState.DRAFT
        assert decision.id is not None

        # Step 2: Validate → READY
        decision = service.validate_decision(decision.id)
        assert decision.state == DecisionState.READY
        assert decision.validated_at is not None
        assert decision.policy_result is not None

        # Step 3: Request Approval → PENDING_APPROVAL
        decision = service.request_approval(decision.id)
        assert decision.state == DecisionState.PENDING_APPROVAL
        assert decision.expires_at is not None

        # Step 4: Approve → APPROVED
        approver = db_session.query(User).first()
        decision = service.approve_decision(decision.id, approver.id)
        assert decision.state == DecisionState.APPROVED
        assert decision.approved_by_user_id == approver.id
        assert decision.approved_at is not None

        # Step 5: Execute → EXECUTED
        decision = service.execute_decision(decision.id, operator_armed=True, dry_run=True)
        assert decision.state == DecisionState.EXECUTED
        assert decision.executed_at is not None
        assert decision.execution_result["success"] is True


class TestStateTransitions:
    """Test individual state transitions."""

    def test_create_draft(self, db_session):
        """Test DRAFT creation."""
        service = DecisionService(db_session)
        ad_account = db_session.query(AdAccount).first()
        user = db_session.query(User).first()

        decision = service.create_draft(
            ad_account_id=ad_account.id,
            user_id=user.id,
            action_type="adset_pause",
            entity_type="adset",
            entity_id="adset_pause",
            entity_name="Pause Test",
            payload={},
            rationale="Test pause",
        )

        assert decision.state == DecisionState.DRAFT
        assert decision.action_type == "adset_pause"
        assert decision.trace_id.startswith("draft-")

    def test_validate_blocks_invalid_action(self, db_session):
        """Test validation blocks policy-violating actions."""
        service = DecisionService(db_session)
        ad_account = db_session.query(AdAccount).first()
        user = db_session.query(User).first()

        # Create decision with extreme budget change (>20%)
        decision = service.create_draft(
            ad_account_id=ad_account.id,
            user_id=user.id,
            action_type="budget_change",
            entity_type="adset",
            entity_id="adset_extreme",
            entity_name="Extreme Budget",
            payload={"current_budget": 100.0, "new_budget": 500.0},  # 400% increase!
            rationale="Test policy block",
        )

        # Validate should block this
        decision = service.validate_decision(decision.id)
        assert decision.state == DecisionState.BLOCKED
        assert len(decision.policy_checks) > 0

    def test_validate_approves_valid_action(self, db_session):
        """Test validation approves policy-compliant actions."""
        service = DecisionService(db_session)
        ad_account = db_session.query(AdAccount).first()
        user = db_session.query(User).first()

        # Create decision with small budget change (<20%)
        decision = service.create_draft(
            ad_account_id=ad_account.id,
            user_id=user.id,
            action_type="budget_change",
            entity_type="adset",
            entity_id="adset_valid",
            entity_name="Valid Budget",
            payload={"current_budget": 100.0, "new_budget": 115.0},  # 15% increase
            rationale="Test policy approval",
        )

        # Validate should approve this
        decision = service.validate_decision(decision.id)
        assert decision.state == DecisionState.READY
        assert decision.validated_at is not None

    def test_request_approval_sets_expiry(self, db_session):
        """Test that approval requests set 24h expiry."""
        service = DecisionService(db_session)
        ad_account = db_session.query(AdAccount).first()
        user = db_session.query(User).first()

        # Create and validate
        decision = service.create_draft(
            ad_account_id=ad_account.id,
            user_id=user.id,
            action_type="budget_change",
            entity_type="adset",
            entity_id="adset_expiry",
            entity_name="Expiry Test",
            payload={"current_budget": 100.0, "new_budget": 110.0},
            rationale="Test expiry",
        )
        decision = service.validate_decision(decision.id)

        # Request approval
        before_request = datetime.utcnow()
        decision = service.request_approval(decision.id)

        # Should expire in ~24 hours
        assert decision.expires_at is not None
        time_diff = decision.expires_at - before_request
        assert 23 <= time_diff.total_seconds() / 3600 <= 25  # 23-25 hours

    def test_reject_decision(self, db_session):
        """Test decision rejection."""
        service = DecisionService(db_session)
        ad_account = db_session.query(AdAccount).first()
        user = db_session.query(User).first()

        # Create, validate, request approval
        decision = service.create_draft(
            ad_account_id=ad_account.id,
            user_id=user.id,
            action_type="budget_change",
            entity_type="adset",
            entity_id="adset_reject",
            entity_name="Reject Test",
            payload={"current_budget": 100.0, "new_budget": 110.0},
            rationale="Test rejection",
        )
        decision = service.validate_decision(decision.id)
        decision = service.request_approval(decision.id)

        # Reject
        decision = service.reject_decision(decision.id, "Not needed")
        assert decision.state == DecisionState.REJECTED
        assert decision.rejected_at is not None
        assert "rejected_reason" in decision.execution_result


class TestValidationRules:
    """Test state transition validation rules."""

    def test_cannot_validate_non_draft(self, db_session):
        """Test that only DRAFT decisions can be validated."""
        service = DecisionService(db_session)
        ad_account = db_session.query(AdAccount).first()
        user = db_session.query(User).first()

        # Create and validate
        decision = service.create_draft(
            ad_account_id=ad_account.id,
            user_id=user.id,
            action_type="budget_change",
            entity_type="adset",
            entity_id="adset_123",
            entity_name="Test",
            payload={"current_budget": 100.0, "new_budget": 110.0},
            rationale="Test",
        )
        decision = service.validate_decision(decision.id)  # Now READY

        # Try to validate again
        with pytest.raises(ValueError, match="Can only validate DRAFT"):
            service.validate_decision(decision.id)

    def test_cannot_approve_non_pending(self, db_session):
        """Test that only PENDING_APPROVAL decisions can be approved."""
        service = DecisionService(db_session)
        ad_account = db_session.query(AdAccount).first()
        user = db_session.query(User).first()

        # Create and validate (READY state)
        decision = service.create_draft(
            ad_account_id=ad_account.id,
            user_id=user.id,
            action_type="budget_change",
            entity_type="adset",
            entity_id="adset_123",
            entity_name="Test",
            payload={"current_budget": 100.0, "new_budget": 110.0},
            rationale="Test",
        )
        decision = service.validate_decision(decision.id)

        # Try to approve without requesting approval first
        with pytest.raises(ValueError, match="Can only approve PENDING"):
            service.approve_decision(decision.id, user.id)

    def test_cannot_execute_non_approved(self, db_session):
        """Test that only APPROVED decisions can be executed."""
        service = DecisionService(db_session)
        ad_account = db_session.query(AdAccount).first()
        user = db_session.query(User).first()

        # Create and validate (READY state)
        decision = service.create_draft(
            ad_account_id=ad_account.id,
            user_id=user.id,
            action_type="budget_change",
            entity_type="adset",
            entity_id="adset_123",
            entity_name="Test",
            payload={"current_budget": 100.0, "new_budget": 110.0},
            rationale="Test",
        )
        decision = service.validate_decision(decision.id)

        # Try to execute without approval
        with pytest.raises(ValueError, match="Can only execute APPROVED"):
            service.execute_decision(decision.id, operator_armed=True, dry_run=True)

    def test_cannot_execute_live_without_operator_armed(self, db_session):
        """Test that live execution requires Operator Armed."""
        service = DecisionService(db_session)
        ad_account = db_session.query(AdAccount).first()
        user = db_session.query(User).first()

        # Create, validate, approve
        decision = service.create_draft(
            ad_account_id=ad_account.id,
            user_id=user.id,
            action_type="budget_change",
            entity_type="adset",
            entity_id="adset_123",
            entity_name="Test",
            payload={"current_budget": 100.0, "new_budget": 110.0},
            rationale="Test",
        )
        decision = service.validate_decision(decision.id)
        decision = service.request_approval(decision.id)
        decision = service.approve_decision(decision.id, user.id)

        # Try to execute live without operator_armed
        with pytest.raises(ValueError, match="Operator Armed must be ON"):
            service.execute_decision(decision.id, operator_armed=False, dry_run=False)


class TestQueryMethods:
    """Test decision retrieval methods."""

    def test_get_decision(self, db_session):
        """Test get_decision returns correct decision."""
        service = DecisionService(db_session)
        ad_account = db_session.query(AdAccount).first()
        user = db_session.query(User).first()

        decision = service.create_draft(
            ad_account_id=ad_account.id,
            user_id=user.id,
            action_type="budget_change",
            entity_type="adset",
            entity_id="adset_get",
            entity_name="Get Test",
            payload={"current_budget": 100.0, "new_budget": 110.0},
            rationale="Test get",
        )

        # Retrieve
        fetched = service.get_decision(decision.id)
        assert fetched is not None
        assert fetched.id == decision.id
        assert fetched.entity_id == "adset_get"

    def test_list_decisions_with_filters(self, db_session):
        """Test list_decisions filters correctly."""
        service = DecisionService(db_session)
        ad_account = db_session.query(AdAccount).first()
        user = db_session.query(User).first()

        # Create multiple decisions
        for i in range(5):
            decision = service.create_draft(
                ad_account_id=ad_account.id,
                user_id=user.id,
                action_type="budget_change",
                entity_type="adset",
                entity_id=f"adset_{i}",
                entity_name=f"Test {i}",
                payload={"current_budget": 100.0, "new_budget": 110.0},
                rationale=f"Test {i}",
            )
            # Validate some
            if i % 2 == 0:
                service.validate_decision(decision.id)

        # List all
        all_decisions = service.list_decisions()
        assert len(all_decisions) == 5

        # List by state
        ready_decisions = service.list_decisions(state=DecisionState.READY)
        assert len(ready_decisions) == 3  # 0, 2, 4

        draft_decisions = service.list_decisions(state=DecisionState.DRAFT)
        assert len(draft_decisions) == 2  # 1, 3

    def test_list_decisions_respects_limit(self, db_session):
        """Test list_decisions respects limit parameter."""
        service = DecisionService(db_session)
        ad_account = db_session.query(AdAccount).first()
        user = db_session.query(User).first()

        # Create 10 decisions
        for i in range(10):
            service.create_draft(
                ad_account_id=ad_account.id,
                user_id=user.id,
                action_type="budget_change",
                entity_type="adset",
                entity_id=f"adset_{i}",
                entity_name=f"Test {i}",
                payload={"current_budget": 100.0, "new_budget": 110.0},
                rationale=f"Test {i}",
            )

        # List with limit
        decisions = service.list_decisions(limit=5)
        assert len(decisions) == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
