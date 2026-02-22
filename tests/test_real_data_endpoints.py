"""
FASE 5.2: Real Data Integration Tests
Verifies that policies, audit, dashboard, and creatives endpoints
return REAL data from the database — no mocks, no hardcoded values.

Every assertion checks for dynamic data derived from DB state.
Uses API calls (not direct DB inserts) to match production behavior.
"""
import pytest
from uuid import uuid4
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PostgreSQL UUID type for SQLite compatibility
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

from backend.main import app
from backend.src.database.models import (
    Base, Organization, MetaConnection, AdAccount, User, DecisionPack,
    DecisionState, ActionType, UserOrgRole, RoleEnum, Creative,
    Subscription, PlanEnum, SubscriptionStatusEnum,
)
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user, UserRole


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db_session(db_engine):
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="function")
def override_db(db_engine):
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
    """Seed test database with realistic data."""
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
        id=org_id, name="Real Data Test Corp", slug="real-data-test",
        operator_armed=True, created_at=datetime.utcnow(),
    )
    db_session.add(org)

    user = User(
        id=user_id, email="real-user@test.com", name="Real User",
        password_hash="hashed", created_at=datetime.utcnow(),
    )
    db_session.add(user)

    role = UserOrgRole(
        id=uuid4(), user_id=user_id, org_id=org_id,
        role=RoleEnum.ADMIN, assigned_at=datetime.utcnow(),
    )
    db_session.add(role)

    connection = MetaConnection(
        id=connection_id, org_id=org_id,
        access_token_encrypted="enc_test_token",
        status="active", connected_at=datetime.utcnow(),
    )
    db_session.add(connection)

    ad_account = AdAccount(
        id=ad_account_id, connection_id=connection_id,
        meta_ad_account_id="act_test_real_data", name="Test Ad Account",
        currency="USD", synced_at=datetime.utcnow(),
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
        "ad_account_id": str(ad_account_id),
    }


@pytest.fixture(scope="function")
def client():
    return TestClient(app)


def _create_decision_via_api(client, seed_data, budget_pct=10):
    """Create a decision through the API (matches production flow)."""
    current = 100.0
    new = current * (1 + budget_pct / 100)
    return client.post("/api/decisions/", json={
        "ad_account_id": seed_data["ad_account_id"],
        "user_id": seed_data["user_id"],
        "action_type": "budget_change",
        "entity_type": "adset",
        "entity_id": f"adset_{uuid4().hex[:8]}",
        "entity_name": "Test Adset",
        "payload": {
            "current_budget": current,
            "new_budget": new,
            "before": {"daily_budget": current},
            "after": {"daily_budget": new},
        },
        "rationale": f"Test: {budget_pct}% increase",
        "source": "RealDataTest",
    })


# ── Test: Policy Rules (Real from DEFAULT_RULES) ─────────────────────────────

class TestPolicyRulesRealData:

    def test_rules_from_real_registry(self, client, seed_data):
        """Rules must come from DEFAULT_RULES, not hardcoded dicts."""
        res = client.get("/api/policies/rules")
        assert res.status_code == 200

        rules = res.json()
        assert len(rules) >= 5  # 5 DEFAULT_RULES + kill_switch

        rule_ids = [r["rule_id"] for r in rules]
        assert "budget_delta" in rule_ids
        assert "cooldown_lock" in rule_ids
        assert "learning_phase_protection" in rule_ids
        assert "no_direct_edits" in rule_ids
        assert "excessive_frequency" in rule_ids
        assert "kill_switch" in rule_ids

    def test_violations_empty_when_no_blocked(self, client, seed_data):
        """Violations must be empty when no decisions are blocked."""
        res = client.get("/api/policies/violations")
        assert res.status_code == 200
        assert res.json() == []

    def test_violations_populated_after_block(self, client, seed_data):
        """Violations appear when a decision is BLOCKED by policy."""
        # Create a decision with 50% budget increase (exceeds 20% limit)
        create_resp = _create_decision_via_api(client, seed_data, budget_pct=50)
        assert create_resp.status_code == 200
        decision_id = create_resp.json()["id"]

        # Validate — should be BLOCKED
        validate_resp = client.post(f"/api/decisions/{decision_id}/validate")
        assert validate_resp.status_code == 200
        assert validate_resp.json()["state"] == "blocked"

        # Now violations should show the real policy check
        res = client.get("/api/policies/violations")
        assert res.status_code == 200
        violations = res.json()
        assert len(violations) >= 1
        assert violations[0]["rule_name"] == "BudgetDeltaRule"

    def test_violation_count_reflects_db(self, client, seed_data):
        """Rule violation_count must match real blocked decisions."""
        # Create 2 blocked decisions
        for _ in range(2):
            create_resp = _create_decision_via_api(client, seed_data, budget_pct=50)
            decision_id = create_resp.json()["id"]
            client.post(f"/api/decisions/{decision_id}/validate")

        res = client.get("/api/policies/rules")
        rules = res.json()
        budget_rule = next(r for r in rules if r["rule_id"] == "budget_delta")
        assert budget_rule["violations_count"] == 2  # Real count from DB

    def test_rule_by_id(self, client, seed_data):
        """Get individual rule by ID."""
        res = client.get("/api/policies/rules/budget_delta")
        assert res.status_code == 200
        assert res.json()["rule_id"] == "budget_delta"
        assert res.json()["name"] == "Budget Change Limits"

    def test_rule_not_found(self, client, seed_data):
        """Non-existent rule returns 404."""
        res = client.get("/api/policies/rules/nonexistent_rule")
        assert res.status_code == 404


# ── Test: Audit (Real User Joins + Stats) ─────────────────────────────────────

class TestAuditRealData:

    def test_audit_empty_when_nothing_executed(self, client, seed_data):
        """Audit log must be empty when no decisions are executed."""
        res = client.get("/api/audit/")
        assert res.status_code == 200
        assert res.json() == []

    def test_audit_shows_real_user_email(self, client, seed_data):
        """Audit entries must show REAL user email, NOT 'demo@example.com'."""
        # Full lifecycle: create -> validate -> approve -> execute (dry_run)
        create_resp = _create_decision_via_api(client, seed_data, budget_pct=10)
        decision_id = create_resp.json()["id"]

        client.post(f"/api/decisions/{decision_id}/validate")
        client.post(f"/api/decisions/{decision_id}/request-approval")
        client.post(f"/api/decisions/{decision_id}/approve", json={
            "approver_user_id": seed_data["user_id"],
        })
        client.post(f"/api/decisions/{decision_id}/execute", json={"dry_run": True})

        res = client.get("/api/audit/")
        assert res.status_code == 200
        entries = res.json()
        assert len(entries) == 1
        # CRITICAL: Must be real email from User table, NOT "demo@example.com"
        assert entries[0]["user_email"] == "real-user@test.com"
        assert entries[0]["status"] == "dry_run"

    def test_audit_stats_real_calculation(self, client, seed_data):
        """Stats must be REAL calculations, not hardcoded zeros."""
        # Execute 2 dry-run decisions
        for _ in range(2):
            create_resp = _create_decision_via_api(client, seed_data, budget_pct=10)
            decision_id = create_resp.json()["id"]
            client.post(f"/api/decisions/{decision_id}/validate")
            client.post(f"/api/decisions/{decision_id}/request-approval")
            client.post(f"/api/decisions/{decision_id}/approve", json={
                "approver_user_id": seed_data["user_id"],
            })
            client.post(f"/api/decisions/{decision_id}/execute", json={"dry_run": True})

        res = client.get("/api/audit/stats/summary?days=7")
        assert res.status_code == 200
        stats = res.json()
        assert stats["total_executions"] == 2
        assert stats["dry_run"] == 2  # Real count, not hardcoded


# ── Test: Dashboard KPIs (Real from DB) ───────────────────────────────────────

class TestDashboardRealData:

    def test_kpis_from_database(self, client, seed_data):
        """Dashboard KPIs must come from real DB queries, not hardcoded values."""
        res = client.get("/api/dashboard/kpis?days=1")
        assert res.status_code == 200

        data = res.json()
        assert "kpis" in data
        assert "summary" in data

        kpi_labels = [k["label"] for k in data["kpis"]]
        assert "Pending Approvals" in kpi_labels
        assert "Executed Today" in kpi_labels

        # Verify we do NOT see hardcoded values like "$1,247.50"
        for kpi in data["kpis"]:
            assert "$1,247.50" not in kpi["value"]
            assert "$42.15" not in kpi["value"]

    def test_kpis_reflect_real_state(self, client, seed_data):
        """KPIs must change when DB state changes."""
        # Create decision and move to pending_approval
        create_resp = _create_decision_via_api(client, seed_data, budget_pct=10)
        decision_id = create_resp.json()["id"]
        client.post(f"/api/decisions/{decision_id}/validate")
        client.post(f"/api/decisions/{decision_id}/request-approval")

        res = client.get("/api/dashboard/kpis?days=1")
        data = res.json()

        pending_kpi = next(k for k in data["kpis"] if k["label"] == "Pending Approvals")
        assert pending_kpi["value"] == "1"  # Real count from DB


# ── Test: Creatives (Real from DB) ────────────────────────────────────────────

class TestCreativesRealData:

    def test_creatives_empty_when_no_data(self, client, seed_data):
        """Creatives list must be empty when no creatives in DB."""
        res = client.get("/api/creatives/")
        assert res.status_code == 200
        # Must NOT return hardcoded demo-1/demo-2 — must be empty
        assert res.json() == []
