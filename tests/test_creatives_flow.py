"""
Sprint 2 – BLOQUE 2: Creatives Engine Flow Tests
Tests that generated creatives are persisted to the Creative DB table
and retrievable via GET /creatives/.
"""
import os
import pytest
from uuid import uuid4, UUID as PyUUID
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.main import app
from backend.src.database.models import (
    Base, Organization, User, UserOrgRole, RoleEnum,
    MetaConnection, AdAccount, Creative,
    Subscription, PlanEnum, SubscriptionStatusEnum,
)
from backend.src.database.session import get_db
from backend.src.middleware.auth import create_access_token, hash_password


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
    """Seed org + admin user + ad account for creative tests."""
    org_id = uuid4()
    org = Organization(
        id=org_id, name="Creative Test Corp", slug="creative-test",
        operator_armed=True, created_at=datetime.utcnow(),
    )
    db_session.add(org)

    user_id = uuid4()
    user = User(
        id=user_id,
        email="admin@creative.test",
        name="Test Admin",
        password_hash=hash_password("test-pass-123"),
        created_at=datetime.utcnow(),
    )
    db_session.add(user)

    role = UserOrgRole(
        id=uuid4(), user_id=user_id, org_id=org_id,
        role=RoleEnum.ADMIN, assigned_at=datetime.utcnow(),
    )
    db_session.add(role)

    conn_id = uuid4()
    conn = MetaConnection(
        id=conn_id, org_id=org_id,
        access_token_encrypted="enc_test", status="active",
        connected_at=datetime.utcnow(),
    )
    db_session.add(conn)

    ad_account_id = uuid4()
    ad_account = AdAccount(
        id=ad_account_id, connection_id=conn_id,
        meta_ad_account_id="act_creative_test", name="Creative Account",
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

    token = create_access_token(
        user_id=str(user_id),
        email="admin@creative.test",
        role="admin",
        org_id=str(org_id),
    )

    return {
        "org_id": str(org_id),
        "user_id": str(user_id),
        "ad_account_id": str(ad_account_id),
        "ad_account_uuid": ad_account_id,  # Keep UUID for direct DB inserts
        "token": token,
    }


@pytest.fixture
def client(override_db):
    return TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_creative(ad_account_uuid, name="Test Angle", script="Test script.", score=7.5, angle_id="test_angle"):
    """Helper to create a Creative record with proper UUID types."""
    return Creative(
        id=uuid4(),
        ad_account_id=ad_account_uuid,
        name=name,
        ad_copy=script,
        tags=[{"l1": "angle", "l2": angle_id, "confidence": 1.0, "source": "factory"}],
        overall_score=score,
        meta_ad_id=f"gen-{uuid4().hex[:16]}",
        created_at=datetime.utcnow(),
    )


# ── Tests: DB Persistence ────────────────────────────────────────────────────


class TestCreativePersistence:

    def test_creative_persisted_to_db_is_listed(self, client, seed_data, db_session):
        """Manually inserting a Creative to DB should be retrievable via GET /."""
        creative = _make_creative(
            seed_data["ad_account_uuid"],
            name="Test Angle",
            script="This is a test creative script for testing persistence.",
            score=7.5,
        )
        db_session.add(creative)
        db_session.commit()

        resp = client.get("/api/creatives/", headers=_auth(seed_data["token"]))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

        found = [c for c in data if c["script"] == "This is a test creative script for testing persistence."]
        assert len(found) == 1
        assert found[0]["score"] == 0.75  # 7.5 / 10.0 normalized to 0-1
        assert found[0]["angle_name"] == "Test Angle"

    def test_list_creatives_empty_when_no_data(self, client, seed_data):
        """GET / returns empty list when no creatives exist."""
        resp = client.get("/api/creatives/", headers=_auth(seed_data["token"]))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_creative_has_tags_from_db(self, client, seed_data, db_session):
        """Creative tags JSON should be used for angle_id extraction."""
        creative = Creative(
            id=uuid4(),
            ad_account_id=seed_data["ad_account_uuid"],
            name="Custom Angle Name",
            ad_copy="Script with custom angle.",
            tags=[{"l1": "angle", "l2": "urgency_based", "confidence": 0.95, "source": "tagger"}],
            overall_score=8.2,
            meta_ad_id=f"gen-{uuid4().hex[:16]}",
            created_at=datetime.utcnow(),
        )
        db_session.add(creative)
        db_session.commit()

        resp = client.get("/api/creatives/", headers=_auth(seed_data["token"]))
        data = resp.json()
        assert len(data) == 1
        assert data[0]["angle_id"] == "urgency_based"
        assert data[0]["angle_name"] == "Custom Angle Name"

    def test_multiple_creatives_listed(self, client, seed_data, db_session):
        """Multiple creatives in DB should all be returned."""
        for i in range(3):
            creative = _make_creative(
                seed_data["ad_account_uuid"],
                name=f"Angle {i}",
                script=f"Script variant {i}",
                score=5.0 + i,
                angle_id=f"angle_{i}",
            )
            db_session.add(creative)
        db_session.commit()

        resp = client.get("/api/creatives/", headers=_auth(seed_data["token"]))
        data = resp.json()
        assert len(data) == 3

    def test_creative_score_is_real_number(self, client, seed_data, db_session):
        """Creative score should be a real number, not zero or random."""
        creative = Creative(
            id=uuid4(),
            ad_account_id=seed_data["ad_account_uuid"],
            name="Scored Creative",
            ad_copy="A well-scored creative for the campaign.",
            tags=[{"l1": "angle", "l2": "performance", "confidence": 1.0, "source": "factory"}],
            overall_score=6.8,
            evaluation_score={
                "clarity": {"score": 7.0, "reasoning": "Clear message"},
                "hook_strength": {"score": 6.5, "reasoning": "Decent hook"},
                "overall_reasoning": "Good creative",
            },
            meta_ad_id=f"gen-{uuid4().hex[:16]}",
            scored_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
        )
        db_session.add(creative)
        db_session.commit()

        resp = client.get("/api/creatives/", headers=_auth(seed_data["token"]))
        data = resp.json()
        assert len(data) == 1
        assert abs(data[0]["score"] - 0.68) < 0.01  # 6.8 / 10.0 normalized to 0-1
        assert data[0]["score"] > 0


class TestGenerateEndpointValidation:

    def test_generate_auto_creates_ad_account(self, client, seed_data, db_session):
        """Generate auto-creates a demo ad account when none exist, returns 202."""
        # Remove all ad accounts (cascade-safe: delete creatives first)
        db_session.query(Creative).delete()
        db_session.query(AdAccount).delete()
        db_session.commit()

        resp = client.post("/api/creatives/generate", json={
            "angle_id": "test",
            "brand_map_id": "demo",
        }, headers=_auth(seed_data["token"]))
        assert resp.status_code == 202
        assert "job_id" in resp.json()
