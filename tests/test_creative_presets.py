"""
Creative Presets Backend Fields Tests.
Tests that POST /api/creatives/generate accepts and passes through the new
preset fields: framework, hook_style, audience, objective, tone, format.
4 tests covering: framework field, hook_style field, full payload pass-through,
and default None for optional fields.
"""
import os

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

import pytest
from uuid import UUID, uuid4
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PG_UUID BEFORE any model imports so SQLite can handle UUID columns.
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

from fastapi.testclient import TestClient
from backend.main import app
from backend.src.database.models import Base, Organization, MetaConnection, AdAccount
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user


# ── Constants ────────────────────────────────────────────────────────────────

ORG_ID = "00000000-0000-0000-0000-000000000001"
CONNECTION_ID = "00000000-0000-0000-0000-000000000002"
AD_ACCOUNT_ID = "00000000-0000-0000-0000-000000000003"

BASE_PAYLOAD = {
    "angle_id": "test_angle",
    "brand_map_id": "demo",
    "n_variants": 1,
}


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


# ── Helpers ──────────────────────────────────────────────────────────────────


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
        meta_ad_account_id="act_preset_test",
        name="Test Ad Account",
        currency="USD",
    )
    db_session.add(account)
    db_session.commit()
    return account


def _extract_enqueue_payload(mock_enqueue):
    """Extract the payload dict from the enqueue mock call."""
    mock_enqueue.assert_called_once()
    call_kwargs = mock_enqueue.call_args
    if call_kwargs.kwargs.get("payload"):
        return call_kwargs.kwargs["payload"]
    return call_kwargs[0][1]  # second positional arg


# ── 1. test_generate_accepts_framework ────────────────────────────────────────


class TestGenerateAcceptsFramework:

    @patch("backend.src.api.creatives.UsageService")
    @patch("backend.src.jobs.queue.enqueue", return_value="fake-job-id")
    def test_generate_accepts_framework(
        self, mock_enqueue, mock_usage_cls, client, db_session
    ):
        """POST /api/creatives/generate with framework field returns 202."""
        _seed_ad_account(db_session)

        mock_usage_instance = MagicMock()
        mock_usage_cls.return_value = mock_usage_instance

        payload = {**BASE_PAYLOAD, "framework": "AIDA"}
        resp = client.post("/api/creatives/generate", json=payload)
        assert resp.status_code == 202


# ── 2. test_generate_accepts_hook_style ───────────────────────────────────────


class TestGenerateAcceptsHookStyle:

    @patch("backend.src.api.creatives.UsageService")
    @patch("backend.src.jobs.queue.enqueue", return_value="fake-job-id")
    def test_generate_accepts_hook_style(
        self, mock_enqueue, mock_usage_cls, client, db_session
    ):
        """POST /api/creatives/generate with hook_style field returns 202."""
        _seed_ad_account(db_session)

        mock_usage_instance = MagicMock()
        mock_usage_cls.return_value = mock_usage_instance

        payload = {**BASE_PAYLOAD, "hook_style": "question"}
        resp = client.post("/api/creatives/generate", json=payload)
        assert resp.status_code == 202


# ── 3. test_generate_payload_includes_new_fields ──────────────────────────────


class TestGeneratePayloadIncludesNewFields:

    @patch("backend.src.api.creatives.UsageService")
    @patch("backend.src.jobs.queue.enqueue", return_value="fake-job-id")
    def test_generate_payload_includes_new_fields(
        self, mock_enqueue, mock_usage_cls, client, db_session
    ):
        """Verify enqueue is called with payload containing all preset fields:
        framework, hook_style, audience, objective, tone, format."""
        _seed_ad_account(db_session)

        mock_usage_instance = MagicMock()
        mock_usage_cls.return_value = mock_usage_instance

        payload = {
            **BASE_PAYLOAD,
            "framework": "PAS",
            "hook_style": "statistic",
            "audience": "millennials",
            "objective": "conversions",
            "tone": "casual",
            "format": "video_script",
        }
        resp = client.post("/api/creatives/generate", json=payload)
        assert resp.status_code == 202

        enqueued_payload = _extract_enqueue_payload(mock_enqueue)

        assert enqueued_payload["framework"] == "PAS"
        assert enqueued_payload["hook_style"] == "statistic"
        assert enqueued_payload["audience"] == "millennials"
        assert enqueued_payload["objective"] == "conversions"
        assert enqueued_payload["tone"] == "casual"
        assert enqueued_payload["format"] == "video_script"


# ── 4. test_generate_optional_fields_default_none ─────────────────────────────


class TestGenerateOptionalFieldsDefaultNone:

    @patch("backend.src.api.creatives.UsageService")
    @patch("backend.src.jobs.queue.enqueue", return_value="fake-job-id")
    def test_generate_optional_fields_default_none(
        self, mock_enqueue, mock_usage_cls, client, db_session
    ):
        """When preset fields are omitted, their payload values are None."""
        _seed_ad_account(db_session)

        mock_usage_instance = MagicMock()
        mock_usage_cls.return_value = mock_usage_instance

        # Send only the base payload, no preset fields
        resp = client.post("/api/creatives/generate", json=BASE_PAYLOAD)
        assert resp.status_code == 202

        enqueued_payload = _extract_enqueue_payload(mock_enqueue)

        assert enqueued_payload.get("framework") is None, (
            f"Expected framework=None, got {enqueued_payload.get('framework')}"
        )
        assert enqueued_payload.get("hook_style") is None, (
            f"Expected hook_style=None, got {enqueued_payload.get('hook_style')}"
        )
        assert enqueued_payload.get("audience") is None, (
            f"Expected audience=None, got {enqueued_payload.get('audience')}"
        )
        assert enqueued_payload.get("objective") is None, (
            f"Expected objective=None, got {enqueued_payload.get('objective')}"
        )
        assert enqueued_payload.get("tone") is None, (
            f"Expected tone=None, got {enqueued_payload.get('tone')}"
        )
        assert enqueued_payload.get("format") is None, (
            f"Expected format=None, got {enqueued_payload.get('format')}"
        )
