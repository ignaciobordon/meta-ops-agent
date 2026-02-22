"""
Sprint -- Async Creatives Endpoint Tests.
Tests the POST /api/creatives/generate endpoint which returns 202 with a queued job.
5 tests covering 202 response, job run creation, usage gate, missing ad account, payload correctness.
"""
import os
import pytest
from uuid import UUID, uuid4
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PG_UUID BEFORE any model imports so SQLite can handle UUID columns.
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.main import app
from backend.src.database.models import Base, Organization, MetaConnection, AdAccount
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user


# ── Constants ─────────────────────────────────────────────────────────────────

ORG_ID = "00000000-0000-0000-0000-000000000001"
CONNECTION_ID = "00000000-0000-0000-0000-000000000002"
AD_ACCOUNT_ID = "00000000-0000-0000-0000-000000000003"

GENERATE_PAYLOAD = {
    "angle_id": "test_angle",
    "brand_map_id": "demo",
    "n_variants": 1,
}


# ── Fixtures ──────────────────────────────────────────────────────────────────


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
def client(db_engine):
    """TestClient with get_db and get_current_user overridden."""
    SessionLocal = sessionmaker(bind=db_engine)

    def _override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def fake_user():
        return {
            "id": "test-user-id",
            "email": "test@test.com",
            "role": "admin",
            "org_id": ORG_ID,
        }

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = fake_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _seed_ad_account(db_session):
    """Create Organization -> MetaConnection -> AdAccount chain in the DB."""
    org = Organization(
        id=UUID(ORG_ID),
        name="Test Org",
        slug="test-org",
    )
    db_session.add(org)
    db_session.flush()

    conn = MetaConnection(
        id=UUID(CONNECTION_ID),
        org_id=UUID(ORG_ID),
        access_token_encrypted="encrypted-token-placeholder",
        status="active",
    )
    db_session.add(conn)
    db_session.flush()

    account = AdAccount(
        id=UUID(AD_ACCOUNT_ID),
        connection_id=UUID(CONNECTION_ID),
        meta_ad_account_id="act_123456",
        name="Test Ad Account",
        currency="USD",
    )
    db_session.add(account)
    db_session.commit()
    return account


# ── 1. test_creatives_returns_202 ─────────────────────────────────────────────


class TestCreativesReturns202:

    @patch("backend.src.api.creatives.UsageService")
    @patch("backend.src.jobs.queue.enqueue", return_value="fake-job-id")
    def test_creatives_returns_202(
        self, mock_enqueue, mock_usage_cls, client, db_session
    ):
        """POST /api/creatives/generate returns 202 with job_id and status."""
        _seed_ad_account(db_session)

        mock_usage_instance = MagicMock()
        mock_usage_cls.return_value = mock_usage_instance

        resp = client.post("/api/creatives/generate", json=GENERATE_PAYLOAD)
        assert resp.status_code == 202

        data = resp.json()
        assert "job_id" in data
        assert data["job_id"] == "fake-job-id"
        assert data["status"] == "queued"


# ── 2. test_creatives_creates_job_run ─────────────────────────────────────────


class TestCreativesCreatesJobRun:

    @patch("backend.src.api.creatives.UsageService")
    @patch("backend.src.jobs.queue.enqueue", return_value="fake-job-id")
    def test_creatives_creates_job_run(
        self, mock_enqueue, mock_usage_cls, client, db_session
    ):
        """Verify enqueue was called with task_name='creatives_generate'."""
        _seed_ad_account(db_session)

        mock_usage_instance = MagicMock()
        mock_usage_cls.return_value = mock_usage_instance

        resp = client.post("/api/creatives/generate", json=GENERATE_PAYLOAD)
        assert resp.status_code == 202

        mock_enqueue.assert_called_once()
        call_kwargs = mock_enqueue.call_args
        assert call_kwargs.kwargs.get("task_name") or call_kwargs[0][0] == "creatives_generate"


# ── 3. test_creatives_usage_gate ──────────────────────────────────────────────


class TestCreativesUsageGate:

    @patch("backend.src.api.creatives.UsageService")
    @patch("backend.src.jobs.queue.enqueue", return_value="fake-job-id")
    def test_creatives_usage_gate(
        self, mock_enqueue, mock_usage_cls, client, db_session
    ):
        """When UsageService.check_limit raises HTTPException(429), endpoint returns 429."""
        _seed_ad_account(db_session)

        mock_usage_instance = MagicMock()
        mock_usage_instance.check_limit.side_effect = HTTPException(
            status_code=429, detail="Usage limit exceeded"
        )
        mock_usage_cls.return_value = mock_usage_instance

        resp = client.post("/api/creatives/generate", json=GENERATE_PAYLOAD)
        assert resp.status_code == 429


# ── 4. test_creatives_no_ad_account_400 ───────────────────────────────────────


class TestCreativesNoAdAccount400:

    @patch("backend.src.api.creatives.UsageService")
    @patch("backend.src.jobs.queue.enqueue", return_value="fake-job-id")
    def test_creatives_no_ad_account_auto_creates(
        self, mock_enqueue, mock_usage_cls, client, db_session
    ):
        """Without any AdAccount in DB, endpoint auto-creates a demo account and returns 202."""
        # Seed the organization so _get_or_create_demo_account can create a connection
        org = Organization(id=UUID(ORG_ID), name="Test Org", slug="test-org")
        db_session.add(org)
        db_session.commit()

        mock_usage_instance = MagicMock()
        mock_usage_cls.return_value = mock_usage_instance

        resp = client.post("/api/creatives/generate", json=GENERATE_PAYLOAD)
        assert resp.status_code == 202
        assert "job_id" in resp.json()


# ── 5. test_creatives_payload_correctness ─────────────────────────────────────


class TestCreativesPayloadCorrectness:

    @patch("backend.src.api.creatives.UsageService")
    @patch("backend.src.jobs.queue.enqueue", return_value="fake-job-id")
    def test_creatives_payload_correctness(
        self, mock_enqueue, mock_usage_cls, client, db_session
    ):
        """Verify the payload dict passed to enqueue contains all expected keys."""
        _seed_ad_account(db_session)

        mock_usage_instance = MagicMock()
        mock_usage_cls.return_value = mock_usage_instance

        resp = client.post("/api/creatives/generate", json=GENERATE_PAYLOAD)
        assert resp.status_code == 202

        mock_enqueue.assert_called_once()
        call_kwargs = mock_enqueue.call_args

        # Extract the payload argument (positional or keyword)
        if call_kwargs.kwargs.get("payload"):
            payload = call_kwargs.kwargs["payload"]
        else:
            payload = call_kwargs[0][1]  # second positional arg

        assert payload["angle_id"] == "test_angle"
        assert payload["brand_map_id"] == "demo"
        assert payload["n_variants"] == 1
        assert "ad_account_id" in payload
        assert payload["ad_account_id"] == AD_ACCOUNT_ID
