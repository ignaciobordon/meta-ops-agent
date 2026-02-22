"""
Test Creatives Runtime Path — endpoint → enqueue → handler → correct method calls.
Verifies the full chain uses canonical interfaces (not legacy names).
"""
import os

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

import pytest
from uuid import UUID, uuid4
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

from fastapi.testclient import TestClient
from backend.main import app
from backend.src.database.models import Base, Organization, MetaConnection, AdAccount
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user


ORG_ID = "00000000-0000-0000-0000-000000000001"
CONNECTION_ID = "00000000-0000-0000-0000-000000000002"
AD_ACCOUNT_ID = "00000000-0000-0000-0000-000000000003"


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


def _seed_ad_account(db_session):
    org = Organization(id=UUID(ORG_ID), name="Test Org", slug="test-org")
    db_session.add(org)
    db_session.flush()
    conn = MetaConnection(
        id=UUID(CONNECTION_ID),
        org_id=UUID(ORG_ID),
        access_token_encrypted="encrypted-token",
        status="active",
    )
    db_session.add(conn)
    db_session.flush()
    account = AdAccount(
        id=UUID(AD_ACCOUNT_ID),
        connection_id=UUID(CONNECTION_ID),
        meta_ad_account_id="act_runtime_test",
        name="Test Ad Account",
        currency="USD",
    )
    db_session.add(account)
    db_session.commit()


class TestCreativesEndpointEnqueuesCorrectJob:

    @patch("backend.src.api.creatives.UsageService")
    @patch("backend.src.jobs.queue.enqueue", return_value="fake-job-id")
    def test_endpoint_enqueues_creatives_generate(
        self, mock_enqueue, mock_usage_cls, client, db_session
    ):
        """POST /api/creatives/generate enqueues 'creatives_generate' task."""
        _seed_ad_account(db_session)
        mock_usage_cls.return_value = MagicMock()

        resp = client.post("/api/creatives/generate", json={
            "angle_id": "test_angle",
            "brand_map_id": "demo",
            "n_variants": 1,
        })
        assert resp.status_code == 202

        mock_enqueue.assert_called_once()
        call_kwargs = mock_enqueue.call_args
        assert call_kwargs.kwargs.get("task_name") == "creatives_generate" or \
               call_kwargs[0][0] == "creatives_generate"


class TestCreativesHandlerCallsCorrectMethods:

    def test_handler_calls_generate_scripts_not_generate_script(self):
        """The creatives_generate handler in task_runner calls
        factory.generate_scripts() (plural), NOT factory.generate_script() (singular)."""
        from pathlib import Path
        task_runner_path = Path(__file__).parent.parent / "backend" / "src" / "jobs" / "task_runner.py"
        source = task_runner_path.read_text(encoding="utf-8")

        assert "factory.generate_scripts(" in source, (
            "task_runner.py should call factory.generate_scripts() (plural)"
        )
        # Ensure singular form is NOT present (exclude comments)
        lines = source.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "factory.generate_script(" in line and "factory.generate_scripts(" not in line:
                assert False, (
                    f"Legacy factory.generate_script() (singular) found at line {i}"
                )


class TestCreativesHandlerUsesEvaluateNotScore:

    def test_task_runner_source_has_evaluate(self):
        """Verify task_runner.py source code calls scorer.evaluate(), not scorer.score()."""
        from pathlib import Path
        task_runner_path = Path(__file__).parent.parent / "backend" / "src" / "jobs" / "task_runner.py"
        source = task_runner_path.read_text(encoding="utf-8")

        assert "scorer.evaluate(" in source, (
            "task_runner.py should call scorer.evaluate(), not scorer.score()"
        )
        assert "scorer.score(" not in source, (
            "task_runner.py still has legacy scorer.score() call"
        )
