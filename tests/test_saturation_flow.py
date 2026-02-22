"""
Sprint 2 – BLOQUE 5: Saturation Analyzer Flow Tests
Tests real SaturationEngine analysis with demo CSV and CSV upload.
No mock data — all analysis uses the real engine.
"""
import os
import io
import pytest
from uuid import uuid4
from datetime import datetime
from pathlib import Path

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
    MetaConnection, AdAccount,
)
from backend.src.database.session import get_db
from backend.src.middleware.auth import create_access_token, hash_password


# Path to demo CSV
DEMO_CSV_PATH = Path(__file__).parent.parent / "data" / "demo_ads_performance.csv"


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
    """Seed org + operator user for saturation tests."""
    org_id = uuid4()
    org = Organization(
        id=org_id, name="Saturation Test Corp", slug="saturation-test",
        operator_armed=True, created_at=datetime.utcnow(),
    )
    db_session.add(org)

    user_id = uuid4()
    user = User(
        id=user_id,
        email="operator@saturation.test",
        name="Test Operator",
        password_hash=hash_password("test-pass-123"),
        created_at=datetime.utcnow(),
    )
    db_session.add(user)

    role = UserOrgRole(
        id=uuid4(), user_id=user_id, org_id=org_id,
        role=RoleEnum.OPERATOR, assigned_at=datetime.utcnow(),
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
        meta_ad_account_id="act_saturation_test", name="Saturation Account",
        currency="USD", synced_at=datetime.utcnow(),
    )
    db_session.add(ad_account)

    db_session.commit()

    token = create_access_token(
        user_id=str(user_id),
        email="operator@saturation.test",
        role="operator",
        org_id=str(org_id),
    )

    return {
        "org_id": str(org_id),
        "user_id": str(user_id),
        "ad_account_id": str(ad_account_id),
        "token": token,
    }


@pytest.fixture
def client(override_db):
    return TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── Tests ────────────────────────────────────────────────────────────────────


class TestSaturationAnalysis:

    @pytest.mark.skipif(not DEMO_CSV_PATH.exists(), reason="Demo CSV not available")
    def test_analyze_saturation_with_demo_csv(self, client, seed_data):
        """GET /saturation/analyze returns metrics from real SaturationEngine."""
        resp = client.get("/api/saturation/analyze", headers=_auth(seed_data["token"]))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

        # Each metric should have required fields
        for metric in data:
            assert "angle_id" in metric
            assert "angle_name" in metric
            assert "saturation_score" in metric
            assert "status" in metric
            assert "ctr_trend" in metric
            assert "frequency" in metric
            assert "recommendation" in metric

    @pytest.mark.skipif(not DEMO_CSV_PATH.exists(), reason="Demo CSV not available")
    def test_saturation_metrics_have_valid_values(self, client, seed_data):
        """Saturation metrics should have realistic, non-random values."""
        resp = client.get("/api/saturation/analyze", headers=_auth(seed_data["token"]))
        data = resp.json()

        for metric in data:
            # Score should be 0-1 (normalized from 0-100)
            assert 0 <= metric["saturation_score"] <= 1.0
            # Status should be one of the expected values
            assert metric["status"] in ("fresh", "moderate", "saturated")
            # Frequency should be positive
            assert metric["frequency"] >= 0
            # Recommendation should be a non-empty string
            assert len(metric["recommendation"]) > 0

    @pytest.mark.skipif(not DEMO_CSV_PATH.exists(), reason="Demo CSV not available")
    def test_saturation_scores_are_deterministic(self, client, seed_data):
        """Same CSV should produce same scores (no randomness)."""
        resp1 = client.get("/api/saturation/analyze", headers=_auth(seed_data["token"]))
        resp2 = client.get("/api/saturation/analyze", headers=_auth(seed_data["token"]))

        data1 = resp1.json()
        data2 = resp2.json()

        assert len(data1) == len(data2)
        for m1, m2 in zip(data1, data2):
            assert m1["saturation_score"] == m2["saturation_score"]
            assert m1["status"] == m2["status"]
            assert m1["frequency"] == m2["frequency"]


class TestSaturationUpload:

    @pytest.mark.skipif(not DEMO_CSV_PATH.exists(), reason="Demo CSV not available")
    def test_upload_csv_and_analyze(self, client, seed_data):
        """POST /saturation/upload-csv with real CSV returns analyzed metrics."""
        csv_content = DEMO_CSV_PATH.read_bytes()

        resp = client.post(
            "/api/saturation/upload-csv",
            files={"file": ("ads_export.csv", csv_content, "text/csv")},
            headers=_auth(seed_data["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

        # Verify structure
        metric = data[0]
        assert "saturation_score" in metric
        assert "status" in metric
        assert "recommendation" in metric

    def test_upload_non_csv_rejected(self, client, seed_data):
        """POST /saturation/upload-csv with non-CSV file should return 400."""
        resp = client.post(
            "/api/saturation/upload-csv",
            files={"file": ("data.txt", b"not a csv file", "text/plain")},
            headers=_auth(seed_data["token"]),
        )
        assert resp.status_code == 400
        assert "csv" in resp.json()["detail"].lower()
