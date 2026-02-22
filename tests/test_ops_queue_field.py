"""
Tests for the `queue` field on JobRunResponse in the Ops Console API.
Verifies that _to_response() correctly maps job_type -> queue via QUEUE_ROUTING.
4 tests: io queue, llm queue, default queue, and list endpoint includes queue key.
"""
import os
import pytest
from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PG_UUID BEFORE any model imports so SQLite can handle UUID columns.
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.main import app
from backend.src.database.models import (
    Base,
    JobRun,
    JobRunStatus,
    Organization,
)
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user, require_admin


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
    """Override get_db to use the in-memory SQLite engine."""
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
def org_id(db_session):
    """Create an Organization row and return its id."""
    _org_id = uuid4()
    org = Organization(
        id=_org_id,
        name="Queue Field Test Org",
        slug=f"queue-test-{_org_id.hex[:8]}",
        created_at=datetime.utcnow(),
    )
    db_session.add(org)
    db_session.commit()
    return _org_id


@pytest.fixture(scope="function")
def user_id():
    """Return a fake user id for the overridden auth dependency."""
    return uuid4()


@pytest.fixture(scope="function")
def client(override_db, db_session, org_id, user_id):
    """TestClient with get_current_user and require_admin overridden."""

    def fake_user():
        return {"user_id": str(user_id), "org_id": str(org_id), "role": "admin"}

    def fake_admin():
        return None

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[require_admin] = fake_admin
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Seed helpers ─────────────────────────────────────────────────────────────


def _make_job(org_id, **overrides):
    """Create a JobRun with sensible defaults; caller can override any field."""
    defaults = {
        "org_id": org_id,
        "job_type": "meta_sync_assets",
        "status": JobRunStatus.QUEUED,
        "payload_json": {"account_id": "act_123"},
    }
    defaults.update(overrides)
    return JobRun(**defaults)


# ── 1. test_job_response_has_queue_field ─────────────────────────────────────


class TestJobResponseHasQueueField:

    def test_job_response_has_queue_field(self, client, db_session, org_id):
        """GET /api/ops/jobs/{id} for a meta_sync_assets job returns queue='io'."""
        job = _make_job(org_id, job_type="meta_sync_assets")
        db_session.add(job)
        db_session.commit()
        job_id = str(job.id)

        resp = client.get(f"/api/ops/jobs/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "queue" in data
        assert data["queue"] == "io"


# ── 2. test_job_response_queue_llm ──────────────────────────────────────────


class TestJobResponseQueueLlm:

    def test_job_response_queue_llm(self, client, db_session, org_id):
        """GET /api/ops/jobs/{id} for a creatives_generate job returns queue='llm'."""
        job = _make_job(org_id, job_type="creatives_generate")
        db_session.add(job)
        db_session.commit()
        job_id = str(job.id)

        resp = client.get(f"/api/ops/jobs/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["queue"] == "llm"


# ── 3. test_job_response_queue_default ──────────────────────────────────────


class TestJobResponseQueueDefault:

    def test_job_response_queue_default(self, client, db_session, org_id):
        """GET /api/ops/jobs/{id} for a decision_execute job returns queue='default'."""
        job = _make_job(org_id, job_type="decision_execute")
        db_session.add(job)
        db_session.commit()
        job_id = str(job.id)

        resp = client.get(f"/api/ops/jobs/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["queue"] == "default"


# ── 4. test_job_list_includes_queue ─────────────────────────────────────────


class TestJobListIncludesQueue:

    def test_job_list_includes_queue(self, client, db_session, org_id):
        """GET /api/ops/jobs returns list where all items have a 'queue' key."""
        jobs = [
            _make_job(org_id, job_type="meta_sync_assets"),
            _make_job(org_id, job_type="creatives_generate"),
            _make_job(org_id, job_type="decision_execute"),
        ]
        db_session.add_all(jobs)
        db_session.commit()

        resp = client.get("/api/ops/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 3
        for item in data:
            assert "queue" in item, f"Job {item['id']} is missing the 'queue' field"
