"""
Sprint 8 — Product Events Tests
Tests event tracking, listing with filters, and funnel analytics.
~8 tests covering POST /api/events/track, GET /api/events/,
and GET /api/events/funnel endpoints.
"""
import os
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.main import app
from backend.src.database.models import Base, Organization, ProductEvent
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
def mock_user():
    org_id = uuid4()
    user_id = uuid4()
    return {
        "id": str(user_id),
        "user_id": str(user_id),
        "org_id": str(org_id),
        "role": "admin",
        "email": "admin@events-test.com",
        "_org_uuid": org_id,
    }


@pytest.fixture(scope="function")
def client(override_db, db_session, mock_user):
    """TestClient with get_db, get_current_user, and require_admin overridden."""
    org_uuid = mock_user["_org_uuid"]

    # Seed the organization so FK constraints are satisfied
    org = Organization(id=org_uuid, name="Test Org", slug="test-org")
    db_session.add(org)
    db_session.commit()

    def fake_user():
        return mock_user

    def fake_admin():
        return None

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[require_admin] = fake_admin

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Tests ────────────────────────────────────────────────────────────────────


class TestProductEvents:

    def test_track_event(self, client):
        """POST /api/events/track with event_name creates a ProductEvent."""
        resp = client.post(
            "/api/events/track",
            json={"event_name": "onboarding_started"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        data = resp.json()
        assert "id" in data
        assert data["event_name"] == "onboarding_started"

    def test_track_event_with_properties(self, client):
        """POST /api/events/track with properties stores them correctly."""
        props = {"source": "dashboard", "variant": "B", "step": 3}
        resp = client.post(
            "/api/events/track",
            json={"event_name": "template_chosen", "properties": props},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["event_name"] == "template_chosen"
        event_id = data["id"]

        # Verify via the list endpoint that properties were persisted
        list_resp = client.get("/api/events/")
        assert list_resp.status_code == 200

        events = list_resp.json()
        matched = [e for e in events if e["id"] == event_id]
        assert len(matched) == 1
        assert matched[0]["properties"]["source"] == "dashboard"
        assert matched[0]["properties"]["variant"] == "B"
        assert matched[0]["properties"]["step"] == 3

    def test_track_event_missing_name(self, client):
        """POST /api/events/track without event_name returns 422."""
        resp = client.post(
            "/api/events/track",
            json={},
        )
        assert resp.status_code == 422

    def test_list_events_empty(self, client):
        """GET /api/events/ with no tracked events returns an empty list."""
        resp = client.get("/api/events/")
        assert resp.status_code == 200

        data = resp.json()
        assert data == []

    def test_list_events_with_data(self, client):
        """Track 3 events, then GET /api/events/ returns all 3."""
        event_names = ["onboarding_started", "meta_connected", "account_selected"]
        for name in event_names:
            track_resp = client.post(
                "/api/events/track",
                json={"event_name": name},
            )
            assert track_resp.status_code == 200

        resp = client.get("/api/events/")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 3

        returned_names = {e["event_name"] for e in data}
        assert returned_names == set(event_names)

    def test_list_events_filter_by_name(self, client):
        """GET /api/events/?event_name=onboarding_started returns only matching events."""
        # Track several different events
        for name in ["onboarding_started", "meta_connected", "onboarding_started"]:
            client.post("/api/events/track", json={"event_name": name})

        resp = client.get("/api/events/?event_name=onboarding_started")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 2
        assert all(e["event_name"] == "onboarding_started" for e in data)

    def test_get_funnel_empty(self, client):
        """GET /api/events/funnel with no events returns all funnel steps with zero counts."""
        resp = client.get("/api/events/funnel")
        assert resp.status_code == 200

        data = resp.json()
        # All funnel event names should be present with count 0
        expected_steps = [
            "onboarding_started",
            "meta_connected",
            "account_selected",
            "template_chosen",
            "onboarding_completed",
            "first_sync_complete",
            "first_alert_seen",
            "first_decision_created",
            "first_analytics_viewed",
        ]
        for step in expected_steps:
            assert step in data, f"Missing funnel step: {step}"
            assert data[step] == 0

    def test_get_funnel_with_data(self, client):
        """Track several funnel events, then verify counts in GET /api/events/funnel."""
        # Track events at different funnel stages
        funnel_events = [
            "onboarding_started",
            "meta_connected",
            "account_selected",
            "template_chosen",
            "onboarding_completed",
        ]
        for name in funnel_events:
            resp = client.post("/api/events/track", json={"event_name": name})
            assert resp.status_code == 200

        resp = client.get("/api/events/funnel")
        assert resp.status_code == 200

        data = resp.json()

        # Tracked events should have count >= 1
        for name in funnel_events:
            assert data[name] >= 1, f"Expected {name} count >= 1, got {data[name]}"

        # Non-tracked funnel events should remain at 0
        assert data["first_sync_complete"] == 0
        assert data["first_alert_seen"] == 0
        assert data["first_decision_created"] == 0
        assert data["first_analytics_viewed"] == 0
