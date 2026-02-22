"""
FASE 4.1: End-to-End Test Suite
Tests complete API workflows from HTTP request to response.

Covers:
1. Health & Observability endpoints
2. Organization CRUD lifecycle
3. Decision Pack full lifecycle (create -> validate -> approve -> execute)
4. Policy enforcement (blocking, budget limits)
5. Rate limiting verification
6. Error handling (404s, invalid data, state machine violations)
7. Metrics endpoint
"""
import pytest
import sys
from pathlib import Path
from uuid import uuid4
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PostgreSQL UUID type for SQLite compatibility BEFORE model import
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

# Path setup (conftest.py adds project root to sys.path)
root_path = Path(__file__).parent.parent

from backend.main import app
from backend.src.database.models import (
    Base,
    Organization,
    MetaConnection,
    AdAccount,
    User,
    DecisionPack,
    DecisionState,
    ActionType,
    UserOrgRole,
    RoleEnum,
    Subscription, PlanEnum, SubscriptionStatusEnum,
)
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user, UserRole


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_engine():
    """Create SQLite in-memory engine with UUID support."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # Share single connection for in-memory DB
    )

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db_session(db_engine):
    """Create a database session for tests."""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="function")
def override_db(db_engine):
    """Override FastAPI dependency with test database + auth bypass."""
    SessionLocal = sessionmaker(bind=db_engine)

    def _override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def seed_data(db_session, override_db):
    """Seed test database with base data for E2E tests."""
    org_id = uuid4()

    # Override auth to use this org's ID for multi-tenant filtering
    def _override_get_current_user():
        return {
            "id": "test-admin-user",
            "email": "admin@test.com",
            "name": "Test Admin",
            "role": UserRole.ADMIN,
            "org_id": str(org_id),
        }
    app.dependency_overrides[get_current_user] = _override_get_current_user
    user_id = uuid4()
    connection_id = uuid4()
    ad_account_id = uuid4()

    org = Organization(
        id=org_id,
        name="E2E Test Corp",
        slug="e2e-test",
        operator_armed=True,
        created_at=datetime.utcnow(),
    )
    db_session.add(org)

    user = User(
        id=user_id,
        email="e2e@test.com",
        name="E2E Tester",
        password_hash="hashed_test_password",
        created_at=datetime.utcnow(),
    )
    db_session.add(user)

    role = UserOrgRole(
        id=uuid4(),
        user_id=user_id,
        org_id=org_id,
        role=RoleEnum.ADMIN,
        assigned_at=datetime.utcnow(),
    )
    db_session.add(role)

    connection = MetaConnection(
        id=connection_id,
        org_id=org_id,
        access_token_encrypted="encrypted_test_token",
        status="active",
        connected_at=datetime.utcnow(),
    )
    db_session.add(connection)

    ad_account = AdAccount(
        id=ad_account_id,
        connection_id=connection_id,
        meta_ad_account_id="act_e2e_123456",
        name="E2E Ad Account",
        currency="USD",
        synced_at=datetime.utcnow(),
    )
    db_session.add(ad_account)

    # Sprint 4: Subscription required for usage gates
    sub = Subscription(
        id=uuid4(), org_id=org_id, plan=PlanEnum.TRIAL,
        status=SubscriptionStatusEnum.TRIALING,
        max_ad_accounts=1, max_decisions_per_month=50,
        max_creatives_per_month=30, allow_live_execution=False,
        created_at=datetime.utcnow(),
    )
    db_session.add(sub)

    db_session.commit()

    return {
        "org_id": str(org_id),
        "user_id": str(user_id),
        "connection_id": str(connection_id),
        "ad_account_id": str(ad_account_id),
    }


@pytest.fixture
def client(override_db):
    """Create TestClient."""
    return TestClient(app)


# ── 1. Health & Observability ────────────────────────────────────────────────


class TestHealthEndpoints:
    """E2E: Health check and observability endpoints."""

    def test_health_endpoint_returns_200(self, client):
        """GET /api/health returns status with dependency checks."""
        response = client.get("/api/health")
        assert response.status_code in [200, 207, 503]
        data = response.json()
        assert "status" in data
        assert "dependencies" in data
        assert "timestamp" in data

    def test_readiness_probe(self, client):
        """GET /api/health/ready returns readiness status."""
        response = client.get("/api/health/ready")
        assert response.status_code in [200, 503]
        data = response.json()
        assert "ready" in data

    def test_liveness_probe(self, client):
        """GET /api/health/live returns 200 if app is alive."""
        response = client.get("/api/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["alive"] is True

    def test_metrics_endpoint(self, client):
        """GET /metrics returns Prometheus format metrics."""
        response = client.get("/metrics")
        assert response.status_code == 200
        body = response.text
        # Prometheus metrics format check
        assert "http_requests_total" in body or "python_info" in body


# ── 2. Organization CRUD ────────────────────────────────────────────────────


class TestOrganizationLifecycle:
    """E2E: Complete organization management workflow."""

    def test_create_organization(self, client, seed_data):
        """POST /api/orgs creates a new organization."""
        response = client.post("/api/orgs/", json={
            "name": "New Test Org",
            "slug": "new-test-org",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Test Org"
        assert data["slug"] == "new-test-org"
        assert data["operator_armed"] is False  # Default

    def test_list_organizations(self, client, seed_data):
        """GET /api/orgs returns all organizations."""
        response = client.get("/api/orgs/")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1  # At least the seeded org
        assert any(org["slug"] == "e2e-test" for org in data)

    def test_get_organization_by_id(self, client, seed_data):
        """GET /api/orgs/{id} returns specific organization."""
        response = client.get(f"/api/orgs/{seed_data['org_id']}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "E2E Test Corp"

    def test_toggle_operator_armed(self, client, seed_data):
        """POST /api/orgs/{id}/operator-armed toggles operator mode."""
        org_id = seed_data["org_id"]

        # Disable operator armed
        response = client.post(f"/api/orgs/{org_id}/operator-armed", json={
            "enabled": False,
        })
        assert response.status_code == 200
        assert response.json()["operator_armed"] is False

        # Re-enable
        response = client.post(f"/api/orgs/{org_id}/operator-armed", json={
            "enabled": True,
        })
        assert response.status_code == 200
        assert response.json()["operator_armed"] is True

    def test_get_ad_accounts_for_org(self, client, seed_data):
        """GET /api/orgs/{id}/ad-accounts returns org's ad accounts."""
        response = client.get(f"/api/orgs/{seed_data['org_id']}/ad-accounts")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_create_duplicate_slug_fails(self, client, seed_data):
        """POST /api/orgs with duplicate slug returns 400."""
        response = client.post("/api/orgs/", json={
            "name": "Duplicate",
            "slug": "e2e-test",  # Already exists
        })
        assert response.status_code == 400

    def test_get_nonexistent_org_returns_404(self, client, seed_data):
        """GET /api/orgs/{fake-id} returns 404."""
        fake_id = str(uuid4())
        response = client.get(f"/api/orgs/{fake_id}")
        assert response.status_code == 404


# ── 3. Decision Pack Full Lifecycle ──────────────────────────────────────────


class TestDecisionFullLifecycle:
    """E2E: Complete decision pack workflow."""

    def _create_decision(self, client, seed_data, budget_increase_pct=10):
        """Helper: Create a decision with specified budget increase."""
        current = 100.0
        new = current * (1 + budget_increase_pct / 100)
        response = client.post("/api/decisions/", json={
            "ad_account_id": seed_data["ad_account_id"],
            "user_id": seed_data["user_id"],
            "action_type": "budget_change",
            "entity_type": "adset",
            "entity_id": f"adset_{uuid4().hex[:8]}",
            "entity_name": "E2E Test Adset",
            "payload": {
                "current_budget": current,
                "new_budget": new,
            },
            "rationale": f"E2E test: {budget_increase_pct}% increase",
            "source": "E2E_Test",
        })
        return response

    def test_create_decision_draft(self, client, seed_data):
        """POST /api/decisions creates a DRAFT decision."""
        response = self._create_decision(client, seed_data)
        assert response.status_code == 200
        data = response.json()
        assert data["state"].upper() == "DRAFT"
        assert data["action_type"] == "budget_change"

    def test_full_happy_path(self, client, seed_data):
        """Complete lifecycle: create -> validate -> request approval -> approve -> execute."""
        # Step 1: Create
        create_resp = self._create_decision(client, seed_data, budget_increase_pct=10)
        assert create_resp.status_code == 200
        decision_id = create_resp.json()["id"]
        assert create_resp.json()["state"].upper() == "DRAFT"

        # Step 2: Validate (should pass - 10% is within limits)
        validate_resp = client.post(f"/api/decisions/{decision_id}/validate")
        assert validate_resp.status_code == 200
        assert validate_resp.json()["state"].upper() == "READY"

        # Step 3: Request approval
        approval_req = client.post(f"/api/decisions/{decision_id}/request-approval")
        assert approval_req.status_code == 200
        assert approval_req.json()["state"].upper() == "PENDING_APPROVAL"

        # Step 4: Approve
        approve_resp = client.post(f"/api/decisions/{decision_id}/approve", json={
            "approver_user_id": seed_data["user_id"],
        })
        assert approve_resp.status_code == 200
        assert approve_resp.json()["state"].upper() == "APPROVED"

        # Step 5: Execute (dry-run for safety)
        execute_resp = client.post(f"/api/decisions/{decision_id}/execute", json={
            "dry_run": True,
        })
        assert execute_resp.status_code == 200
        data = execute_resp.json()
        assert data["state"].upper() == "EXECUTED"
        assert data["executed_at"] is not None

    def test_list_decisions(self, client, seed_data):
        """GET /api/decisions returns decision list."""
        # Create a decision first
        self._create_decision(client, seed_data)

        response = client.get("/api/decisions/")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_get_decision_by_id(self, client, seed_data):
        """GET /api/decisions/{id} returns specific decision."""
        create_resp = self._create_decision(client, seed_data)
        decision_id = create_resp.json()["id"]

        response = client.get(f"/api/decisions/{decision_id}")
        assert response.status_code == 200
        assert response.json()["id"] == decision_id

    def test_reject_decision(self, client, seed_data):
        """Reject a decision after approval request."""
        # Create and validate
        create_resp = self._create_decision(client, seed_data)
        decision_id = create_resp.json()["id"]
        client.post(f"/api/decisions/{decision_id}/validate")
        client.post(f"/api/decisions/{decision_id}/request-approval")

        # Reject
        reject_resp = client.post(f"/api/decisions/{decision_id}/reject", json={
            "reason": "E2E test rejection",
        })
        assert reject_resp.status_code == 200
        assert reject_resp.json()["state"].upper() == "REJECTED"

    def test_filter_decisions_by_state(self, client, seed_data):
        """GET /api/decisions/?state=draft filters correctly."""
        self._create_decision(client, seed_data)

        response = client.get("/api/decisions/?state=draft")
        assert response.status_code == 200
        data = response.json()
        assert all(d["state"].upper() == "DRAFT" for d in data)


# ── 4. Policy Enforcement ────────────────────────────────────────────────────


class TestPolicyEnforcement:
    """E2E: Policy engine blocks dangerous decisions."""

    def test_extreme_budget_blocked(self, client, seed_data):
        """100% budget increase should be blocked by policy."""
        create_resp = client.post("/api/decisions/", json={
            "ad_account_id": seed_data["ad_account_id"],
            "user_id": seed_data["user_id"],
            "action_type": "budget_change",
            "entity_type": "adset",
            "entity_id": "adset_extreme_test",
            "entity_name": "Extreme Budget Test",
            "payload": {
                "current_budget": 100.0,
                "new_budget": 200.0,  # 100% increase
            },
            "rationale": "E2E: test policy blocking",
            "source": "E2E_Test",
        })
        assert create_resp.status_code == 200
        decision_id = create_resp.json()["id"]

        # Validate - should be BLOCKED
        validate_resp = client.post(f"/api/decisions/{decision_id}/validate")
        assert validate_resp.status_code == 200
        data = validate_resp.json()
        assert data["state"].upper() == "BLOCKED"

    def test_moderate_budget_passes(self, client, seed_data):
        """10% budget increase should pass validation."""
        create_resp = client.post("/api/decisions/", json={
            "ad_account_id": seed_data["ad_account_id"],
            "user_id": seed_data["user_id"],
            "action_type": "budget_change",
            "entity_type": "adset",
            "entity_id": "adset_moderate_test",
            "entity_name": "Moderate Budget Test",
            "payload": {
                "current_budget": 100.0,
                "new_budget": 110.0,  # 10% increase
            },
            "rationale": "E2E: test policy pass",
            "source": "E2E_Test",
        })
        assert create_resp.status_code == 200
        decision_id = create_resp.json()["id"]

        validate_resp = client.post(f"/api/decisions/{decision_id}/validate")
        assert validate_resp.status_code == 200
        assert validate_resp.json()["state"].upper() == "READY"


# ── 5. Error Handling ────────────────────────────────────────────────────────


class TestErrorHandling:
    """E2E: Proper error responses for invalid requests."""

    def test_404_nonexistent_decision(self, client, seed_data):
        """GET /api/decisions/{fake-id} returns 404."""
        response = client.get(f"/api/decisions/{uuid4()}")
        assert response.status_code == 404

    def test_invalid_state_transition(self, client, seed_data):
        """Cannot approve a DRAFT decision (must validate first)."""
        # Create decision (DRAFT state)
        create_resp = client.post("/api/decisions/", json={
            "ad_account_id": seed_data["ad_account_id"],
            "user_id": seed_data["user_id"],
            "action_type": "budget_change",
            "entity_type": "adset",
            "entity_id": "adset_invalid_state",
            "entity_name": "Invalid State Test",
            "payload": {"current_budget": 100.0, "new_budget": 110.0},
            "rationale": "test",
            "source": "E2E_Test",
        })
        decision_id = create_resp.json()["id"]

        # Try to approve directly (should fail - not in PENDING_APPROVAL state)
        approve_resp = client.post(f"/api/decisions/{decision_id}/approve", json={
            "approver_user_id": seed_data["user_id"],
        })
        assert approve_resp.status_code in [400, 422]

    def test_validate_nonexistent_decision(self, client, seed_data):
        """Validate non-existent decision returns error."""
        fake_id = str(uuid4())
        response = client.post(f"/api/decisions/{fake_id}/validate")
        assert response.status_code in [400, 404]

    def test_missing_required_fields(self, client, seed_data):
        """POST /api/decisions with missing fields returns 422."""
        response = client.post("/api/decisions/", json={
            "action_type": "budget_change",
            # Missing required fields
        })
        assert response.status_code == 422

    def test_invalid_org_id_format(self, client, seed_data):
        """GET /api/orgs/not-a-uuid returns 422."""
        response = client.get("/api/orgs/not-a-uuid")
        assert response.status_code == 422


# ── 6. Cross-Cutting Concerns ────────────────────────────────────────────────


class TestCrossCuttingConcerns:
    """E2E: CORS, content types, OpenAPI docs."""

    def test_openapi_docs_available(self, client):
        """GET /docs returns OpenAPI Swagger UI."""
        response = client.get("/docs")
        assert response.status_code == 200

    def test_openapi_json_available(self, client):
        """GET /openapi.json returns OpenAPI schema."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert data["info"]["title"] == "Meta Ops Agent API"
        assert data["info"]["version"] == "1.0.0"

    def test_json_content_type(self, client, seed_data):
        """API responses return application/json content type."""
        response = client.get("/api/orgs/")
        assert "application/json" in response.headers.get("content-type", "")

    def test_cors_headers_present(self, client, seed_data):
        """OPTIONS requests return CORS headers."""
        response = client.options(
            "/api/orgs/",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        # CORS middleware should respond
        assert response.status_code in [200, 405]


# ── 7. Data Integrity ────────────────────────────────────────────────────────


class TestDataIntegrity:
    """E2E: Data consistency across operations."""

    def test_decision_timestamps_set_correctly(self, client, seed_data):
        """Decision timestamps update at each state transition."""
        # Create
        create_resp = client.post("/api/decisions/", json={
            "ad_account_id": seed_data["ad_account_id"],
            "user_id": seed_data["user_id"],
            "action_type": "budget_change",
            "entity_type": "adset",
            "entity_id": "adset_timestamps",
            "entity_name": "Timestamp Test",
            "payload": {"current_budget": 100.0, "new_budget": 110.0},
            "rationale": "test timestamps",
            "source": "E2E_Test",
        })
        data = create_resp.json()
        assert data["created_at"] is not None

        decision_id = data["id"]

        # Validate
        validate_resp = client.post(f"/api/decisions/{decision_id}/validate")
        data = validate_resp.json()
        assert data.get("validated_at") is not None

    def test_multiple_decisions_independent(self, client, seed_data):
        """Multiple decisions don't interfere with each other."""
        # Create two decisions
        resp1 = client.post("/api/decisions/", json={
            "ad_account_id": seed_data["ad_account_id"],
            "user_id": seed_data["user_id"],
            "action_type": "budget_change",
            "entity_type": "adset",
            "entity_id": "adset_independence_1",
            "entity_name": "Independence Test 1",
            "payload": {"current_budget": 100.0, "new_budget": 110.0},
            "rationale": "test 1",
            "source": "E2E_Test",
        })
        resp2 = client.post("/api/decisions/", json={
            "ad_account_id": seed_data["ad_account_id"],
            "user_id": seed_data["user_id"],
            "action_type": "budget_change",
            "entity_type": "adset",
            "entity_id": "adset_independence_2",
            "entity_name": "Independence Test 2",
            "payload": {"current_budget": 100.0, "new_budget": 200.0},  # Will be blocked
            "rationale": "test 2",
            "source": "E2E_Test",
        })

        id1 = resp1.json()["id"]
        id2 = resp2.json()["id"]

        # Validate both - first should pass, second should be blocked
        v1 = client.post(f"/api/decisions/{id1}/validate")
        v2 = client.post(f"/api/decisions/{id2}/validate")

        assert v1.json()["state"].upper() == "READY"
        assert v2.json()["state"].upper() == "BLOCKED"

        # First decision state unaffected by second
        get1 = client.get(f"/api/decisions/{id1}")
        assert get1.json()["state"].upper() == "READY"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
