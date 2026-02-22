"""
Sprint 8 -- Alert Center API Tests.
Tests the unified alert management endpoints: listing with filters,
detail retrieval, acknowledge/resolve/snooze actions, and stats aggregation.
10 tests covering GET /api/alerts/, GET /api/alerts/{id},
POST acknowledge/resolve/snooze, and GET /api/alerts/stats.
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
from backend.src.database.models import Base, Organization, MetaAlert, AlertSeverity, MetaAdAccount
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

    def _override():
        SessionLocal = sessionmaker(bind=db_engine)
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(scope="function")
def org_id(db_session):
    """Create an Organization row and return its id."""
    _org_id = uuid4()
    org = Organization(
        id=_org_id,
        name="Test Org",
        slug="test-org",
        created_at=datetime.utcnow(),
    )
    db_session.add(org)
    db_session.commit()
    return _org_id


@pytest.fixture(scope="function")
def mock_user(org_id):
    """Return a dict representing the authenticated admin user."""
    return {
        "id": str(uuid4()),
        "org_id": str(org_id),
        "role": "admin",
        "email": "admin@test-org.com",
    }


@pytest.fixture(scope="function")
def client(override_db, db_session, org_id, mock_user):
    """TestClient with get_db, get_current_user, and require_admin overridden."""

    def fake_user():
        return mock_user

    def fake_admin():
        return None

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[require_admin] = fake_admin
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _create_alert(
    db,
    org_id,
    alert_type="ctr_low",
    severity=AlertSeverity.MEDIUM,
    message="Test alert",
    status="active",
):
    alert = MetaAlert(
        id=uuid4(),
        org_id=org_id,
        alert_type=alert_type,
        severity=severity,
        message=message,
        status=status,
        detected_at=datetime.utcnow(),
    )
    db.add(alert)
    db.commit()
    return alert


# ── Tests ────────────────────────────────────────────────────────────────────


class TestListAlerts:

    def test_list_alerts_empty(self, client, org_id, db_session):
        """GET /api/alerts/ returns empty data list when no alerts exist."""
        resp = client.get("/api/alerts/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == []
        assert body["total"] == 0

    def test_list_alerts_with_data(self, client, org_id, db_session):
        """Create 3 alerts, GET /api/alerts/ returns all 3."""
        _create_alert(db_session, org_id, alert_type="ctr_low", message="Alert 1")
        _create_alert(db_session, org_id, alert_type="cpa_high", message="Alert 2")
        _create_alert(db_session, org_id, alert_type="spend_spike", message="Alert 3")

        resp = client.get("/api/alerts/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert len(body["data"]) == 3

    def test_list_alerts_filter_by_severity(self, client, org_id, db_session):
        """GET /api/alerts/?severity=critical returns only critical alerts."""
        _create_alert(db_session, org_id, severity=AlertSeverity.CRITICAL, message="Critical alert")
        _create_alert(db_session, org_id, severity=AlertSeverity.MEDIUM, message="Medium alert")
        _create_alert(db_session, org_id, severity=AlertSeverity.LOW, message="Low alert")

        resp = client.get("/api/alerts/?severity=critical")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert len(body["data"]) == 1
        assert body["data"][0]["severity"] == "critical"
        assert body["data"][0]["message"] == "Critical alert"

    def test_list_alerts_filter_by_status(self, client, org_id, db_session):
        """GET /api/alerts/?status=acknowledged returns only acknowledged alerts."""
        _create_alert(db_session, org_id, status="active", message="Active alert")
        _create_alert(db_session, org_id, status="acknowledged", message="Acked alert")
        _create_alert(db_session, org_id, status="resolved", message="Resolved alert")

        resp = client.get("/api/alerts/?status=acknowledged")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert len(body["data"]) == 1
        assert body["data"][0]["status"] == "acknowledged"
        assert body["data"][0]["message"] == "Acked alert"


class TestGetAlertDetail:

    def test_get_alert_detail(self, client, org_id, db_session):
        """GET /api/alerts/{id} returns the correct alert."""
        alert = _create_alert(
            db_session, org_id,
            alert_type="cpa_high",
            severity=AlertSeverity.HIGH,
            message="CPA is too high",
        )

        resp = client.get(f"/api/alerts/{alert.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == str(alert.id)
        assert body["alert_type"] == "cpa_high"
        assert body["severity"] == "high"
        assert body["message"] == "CPA is too high"
        assert body["status"] == "active"

    def test_get_alert_not_found(self, client, org_id):
        """GET /api/alerts/{random_id} returns 404."""
        random_id = uuid4()
        resp = client.get(f"/api/alerts/{random_id}")
        assert resp.status_code == 404


class TestAlertActions:

    def test_acknowledge_alert(self, client, org_id, db_session, mock_user):
        """POST /api/alerts/{id}/acknowledge sets status to acknowledged."""
        alert = _create_alert(db_session, org_id, message="Needs ack")

        resp = client.post(f"/api/alerts/{alert.id}/acknowledge")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "acknowledged"
        assert body["acknowledged_at"] is not None

        # Verify the DB was updated
        db_session.refresh(alert)
        assert alert.status == "acknowledged"
        assert alert.acknowledged_at is not None
        assert str(alert.acknowledged_by_user_id) == mock_user["id"]

    def test_resolve_alert(self, client, org_id, db_session):
        """POST /api/alerts/{id}/resolve sets status to resolved and resolved_at."""
        alert = _create_alert(db_session, org_id, message="Needs resolve")

        resp = client.post(f"/api/alerts/{alert.id}/resolve")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "resolved"
        assert body["resolved_at"] is not None

        # Verify the DB was updated
        db_session.refresh(alert)
        assert alert.status == "resolved"
        assert alert.resolved_at is not None

    def test_snooze_alert(self, client, org_id, db_session):
        """POST /api/alerts/{id}/snooze sets status to snoozed."""
        alert = _create_alert(db_session, org_id, message="Needs snooze")

        resp = client.post(f"/api/alerts/{alert.id}/snooze", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "snoozed"

        # Verify the DB was updated
        db_session.refresh(alert)
        assert alert.status == "snoozed"


class TestAlertStats:

    def test_get_alert_stats(self, client, org_id, db_session):
        """GET /api/alerts/stats returns correct counts by severity."""
        # Create a mix of alerts with different severities and statuses
        _create_alert(db_session, org_id, severity=AlertSeverity.CRITICAL, status="active")
        _create_alert(db_session, org_id, severity=AlertSeverity.CRITICAL, status="active")
        _create_alert(db_session, org_id, severity=AlertSeverity.HIGH, status="active")
        _create_alert(db_session, org_id, severity=AlertSeverity.MEDIUM, status="acknowledged")
        _create_alert(db_session, org_id, severity=AlertSeverity.LOW, status="active")
        # This resolved alert should NOT be counted in stats
        _create_alert(db_session, org_id, severity=AlertSeverity.CRITICAL, status="resolved")

        resp = client.get("/api/alerts/stats")
        assert resp.status_code == 200
        body = resp.json()

        assert body["total"] == 5  # excludes the resolved one
        assert body["by_severity"]["critical"] == 2
        assert body["by_severity"]["high"] == 1
        assert body["by_severity"]["medium"] == 1
        assert body["by_severity"]["low"] == 1
        assert body["by_severity"]["info"] == 0
        assert body["by_status"]["active"] == 4
        assert body["by_status"]["acknowledged"] == 1
