"""
Integration tests for Decision Pack API endpoints.
Tests the full stack: API → DecisionService → Operator → PolicyEngine.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import datetime
from uuid import uuid4

# Patch PostgreSQL UUID type for SQLite compatibility
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

from backend.main import app
from backend.src.database.models import (
    Base, Organization, MetaConnection, AdAccount, User, UserOrgRole, RoleEnum,
    Subscription, PlanEnum, SubscriptionStatusEnum,
)
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user, UserRole


# Test database setup
@pytest.fixture(scope="function")
def test_db():
    """Create test database."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    # Create test data
    db = SessionLocal()

    org_id = uuid4()

    def override_get_current_user():
        return {
            "id": "test-admin-user",
            "email": "admin@test.com",
            "name": "Test Admin",
            "role": UserRole.ADMIN,
            "org_id": str(org_id),
        }

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    user_id = uuid4()
    connection_id = uuid4()
    ad_account_id = uuid4()

    # Organization
    org = Organization(
        id=org_id,
        name="Test Org",
        slug="test-org-api",
        operator_armed=True,
        created_at=datetime.utcnow(),
    )
    db.add(org)

    # User
    user = User(
        id=user_id,
        email="test@example.com",
        name="Test User",
        password_hash="hashed",
        created_at=datetime.utcnow(),
    )
    db.add(user)

    # User role
    role = UserOrgRole(
        id=uuid4(),
        user_id=user_id,
        org_id=org_id,
        role=RoleEnum.ADMIN,
        assigned_at=datetime.utcnow(),
    )
    db.add(role)

    # Meta Connection
    connection = MetaConnection(
        id=connection_id,
        org_id=org_id,
        access_token_encrypted="enc_test_token",
        status="active",
        connected_at=datetime.utcnow(),
    )
    db.add(connection)

    # Ad Account
    ad_account = AdAccount(
        id=ad_account_id,
        connection_id=connection_id,
        meta_ad_account_id="act_123456",
        name="Test Ad Account",
        currency="USD",
        synced_at=datetime.utcnow(),
    )
    db.add(ad_account)

    # Sprint 4: Subscription required for usage gates
    sub = Subscription(
        id=uuid4(), org_id=org_id, plan=PlanEnum.TRIAL,
        status=SubscriptionStatusEnum.TRIALING,
        max_ad_accounts=1, max_decisions_per_month=50,
        max_creatives_per_month=30, allow_live_execution=False,
        created_at=datetime.utcnow(),
    )
    db.add(sub)

    db.commit()

    yield {
        "ad_account_id": str(ad_account_id),
        "user_id": str(user_id),
        "db": db
    }

    db.close()
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestDecisionAPILifecycle:
    """Test complete decision lifecycle via API."""

    def test_create_decision(self, client, test_db):
        """Test POST /api/decisions - Create draft decision."""
        response = client.post("/api/decisions/", json={
            "ad_account_id": test_db["ad_account_id"],
            "user_id": test_db["user_id"],
            "action_type": "budget_change",
            "entity_type": "adset",
            "entity_id": "adset_123",
            "entity_name": "Test Adset",
            "payload": {
                "current_budget": 100.0,
                "new_budget": 110.0
            },
            "rationale": "Test budget increase",
            "source": "API Test"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "draft"
        assert data["action_type"] == "budget_change"
        assert data["entity_id"] == "adset_123"

        return data["id"]  # For chaining tests

    def test_full_lifecycle(self, client, test_db):
        """Test complete flow: create → validate → request approval → approve → execute."""
        # Step 1: Create draft
        create_response = client.post("/api/decisions/", json={
            "ad_account_id": test_db["ad_account_id"],
            "user_id": test_db["user_id"],
            "action_type": "budget_change",
            "entity_type": "adset",
            "entity_id": "adset_lifecycle",
            "entity_name": "Lifecycle Test",
            "payload": {
                "current_budget": 100.0,
                "new_budget": 110.0  # 10% increase (within policy)
            },
            "rationale": "Test lifecycle",
            "source": "API Test"
        })

        assert create_response.status_code == 200
        decision_id = create_response.json()["id"]

        # Step 2: Validate
        validate_response = client.post(f"/api/decisions/{decision_id}/validate")
        assert validate_response.status_code == 200
        assert validate_response.json()["state"] == "ready"

        # Step 3: Request approval
        approval_request = client.post(f"/api/decisions/{decision_id}/request-approval")
        assert approval_request.status_code == 200
        assert approval_request.json()["state"] == "pending_approval"

        # Step 4: Approve
        approve_response = client.post(f"/api/decisions/{decision_id}/approve", json={
            "approver_user_id": test_db["user_id"]
        })
        assert approve_response.status_code == 200
        assert approve_response.json()["state"] == "approved"

        # Step 5: Execute (dry-run)
        execute_response = client.post(f"/api/decisions/{decision_id}/execute", json={
            "dry_run": True
        })
        assert execute_response.status_code == 200
        data = execute_response.json()
        assert data["state"] == "executed"
        assert data["executed_at"] is not None


class TestDecisionAPIPolicyBlocking:
    """Test policy enforcement via API."""

    def test_policy_blocks_extreme_budget_change(self, client, test_db):
        """Test that extreme budget changes are blocked by policy."""
        # Create decision with 100% budget increase (exceeds 20% limit)
        create_response = client.post("/api/decisions/", json={
            "ad_account_id": test_db["ad_account_id"],
            "user_id": test_db["user_id"],
            "action_type": "budget_change",
            "entity_type": "adset",
            "entity_id": "adset_extreme",
            "entity_name": "Extreme Test",
            "payload": {
                "current_budget": 100.0,
                "new_budget": 200.0  # 100% increase!
            },
            "rationale": "Test policy block",
            "source": "API Test"
        })

        assert create_response.status_code == 200
        decision_id = create_response.json()["id"]

        # Validate - should be blocked
        validate_response = client.post(f"/api/decisions/{decision_id}/validate")
        assert validate_response.status_code == 200
        data = validate_response.json()
        assert data["state"] == "blocked"
        assert len(data["policy_checks"]) > 0


class TestDecisionAPIQueryMethods:
    """Test decision retrieval endpoints."""

    def test_list_decisions(self, client, test_db):
        """Test GET /api/decisions - List decisions."""
        # Create a decision first
        client.post("/api/decisions/", json={
            "ad_account_id": test_db["ad_account_id"],
            "user_id": test_db["user_id"],
            "action_type": "budget_change",
            "entity_type": "adset",
            "entity_id": "adset_list",
            "entity_name": "List Test",
            "payload": {"current_budget": 100.0, "new_budget": 110.0},
            "rationale": "Test",
        })

        # List all
        response = client.get("/api/decisions/")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_get_decision_by_id(self, client, test_db):
        """Test GET /api/decisions/{id} - Get specific decision."""
        # Create decision
        create_response = client.post("/api/decisions/", json={
            "ad_account_id": test_db["ad_account_id"],
            "user_id": test_db["user_id"],
            "action_type": "budget_change",
            "entity_type": "adset",
            "entity_id": "adset_get",
            "entity_name": "Get Test",
            "payload": {"current_budget": 100.0, "new_budget": 110.0},
            "rationale": "Test",
        })
        decision_id = create_response.json()["id"]

        # Get by ID
        response = client.get(f"/api/decisions/{decision_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == decision_id
        assert data["entity_id"] == "adset_get"

    def test_list_decisions_by_state(self, client, test_db):
        """Test filtering decisions by state."""
        # Create and validate one decision
        create_response = client.post("/api/decisions/", json={
            "ad_account_id": test_db["ad_account_id"],
            "user_id": test_db["user_id"],
            "action_type": "budget_change",
            "entity_type": "adset",
            "entity_id": "adset_filter",
            "entity_name": "Filter Test",
            "payload": {"current_budget": 100.0, "new_budget": 110.0},
            "rationale": "Test",
        })
        decision_id = create_response.json()["id"]
        client.post(f"/api/decisions/{decision_id}/validate")

        # Filter by READY state
        response = client.get("/api/decisions/?state=ready")
        assert response.status_code == 200
        data = response.json()
        assert all(d["state"] == "ready" for d in data)


class TestDecisionAPIErrors:
    """Test error handling."""

    def test_get_nonexistent_decision(self, client, test_db):
        """Test getting non-existent decision returns 404."""
        fake_id = str(uuid4())
        response = client.get(f"/api/decisions/{fake_id}")
        assert response.status_code == 404

    def test_validate_nonexistent_decision(self, client, test_db):
        """Test validating non-existent decision returns 400."""
        fake_id = str(uuid4())
        response = client.post(f"/api/decisions/{fake_id}/validate")
        assert response.status_code == 400


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
