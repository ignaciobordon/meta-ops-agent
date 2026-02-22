"""
Sprint 5 – Outcome System Tests
Tests OutcomeCollector (capture_before, capture_after) and OutcomeLabeler.
8 scenarios covering horizons, scheduling, delta computation, idempotency, and labeling.
"""
import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PostgreSQL UUID type for SQLite compatibility
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

from backend.src.database.models import (
    Base,
    Organization,
    User,
    MetaConnection,
    AdAccount,
    DecisionPack,
    DecisionState,
    ActionType,
    DecisionOutcome,
    OutcomeLabel,
    EntityMemory,
    ScheduledJob,
)
from backend.src.services.outcome_service import OutcomeCollector, OutcomeLabeler
from backend.src.providers.metrics_provider import MetricsSnapshot


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    org_id = uuid4()
    user_id = uuid4()
    connection_id = uuid4()
    ad_account_id = uuid4()
    decision_id = uuid4()
    executed_at = datetime.utcnow()

    # Create test organization
    org = Organization(
        id=org_id,
        name="Test Org",
        slug="test-org-outcome",
        operator_armed=True,
        created_at=datetime.utcnow(),
    )
    session.add(org)

    # Create test user
    user = User(
        id=user_id,
        email="test@outcome.com",
        name="Test User",
        password_hash="hashed",
        created_at=datetime.utcnow(),
    )
    session.add(user)

    # Create test Meta connection
    connection = MetaConnection(
        id=connection_id,
        org_id=org_id,
        access_token_encrypted="enc_test_token",
        status="active",
        connected_at=datetime.utcnow(),
    )
    session.add(connection)

    # Create test ad account
    ad_account = AdAccount(
        id=ad_account_id,
        connection_id=connection_id,
        meta_ad_account_id="act_outcome_test",
        name="Test Ad Account",
        currency="USD",
        synced_at=datetime.utcnow(),
    )
    session.add(ad_account)

    # Create an EXECUTED decision pack
    decision = DecisionPack(
        id=decision_id,
        ad_account_id=ad_account_id,
        created_by_user_id=user_id,
        state=DecisionState.EXECUTED,
        trace_id=f"trace-outcome-{uuid4().hex[:8]}",
        action_type=ActionType.BUDGET_CHANGE,
        entity_type="adset",
        entity_id="adset_outcome_1",
        entity_name="Outcome Test Adset",
        action_request={"current_budget": 100.0, "new_budget": 120.0},
        rationale="Budget increase for outcome test",
        executed_at=executed_at,
    )
    session.add(decision)

    session.commit()

    yield session

    session.close()


def _make_snapshot(entity_type="adset", entity_id="adset_outcome_1", metrics=None):
    """Helper to build a MetricsSnapshot for mocking."""
    return MetricsSnapshot(
        entity_type=entity_type,
        entity_id=entity_id,
        timestamp=datetime.utcnow(),
        provider="mock",
        metrics=metrics or {"spend": 100.0, "ctr": 0.05, "cpa": 10.0, "roas": 3.0},
        available=True,
    )


# ── Tests: OutcomeCollector.capture_before ────────────────────────────────────


class TestCaptureBefore:

    def test_capture_before_creates_three_outcome_rows(self, db_session):
        """capture_before creates 3 DecisionOutcome rows (one per horizon: 60, 1440, 4320)."""
        decision = db_session.query(DecisionPack).first()
        org = db_session.query(Organization).first()

        mock_snapshot = _make_snapshot()

        with patch(
            "backend.src.services.outcome_service.MetricsProviderFactory"
        ) as mock_factory:
            mock_provider = MagicMock()
            mock_provider.get_snapshot.return_value = mock_snapshot
            mock_factory.get_provider.return_value = mock_provider

            collector = OutcomeCollector(db_session)
            outcomes = collector.capture_before(decision, org.id)

        db_session.commit()

        assert len(outcomes) == 3
        horizons = sorted([o.horizon_minutes for o in outcomes])
        assert horizons == [60, 1440, 4320]

        # Verify all rows persisted
        persisted = db_session.query(DecisionOutcome).filter(
            DecisionOutcome.decision_id == decision.id
        ).all()
        assert len(persisted) == 3

        # Verify common fields
        for o in persisted:
            assert o.org_id == org.id
            assert o.entity_type == "adset"
            assert o.entity_id == "adset_outcome_1"
            assert o.action_type == ActionType.BUDGET_CHANGE
            assert o.before_metrics_json is not None
            assert o.before_metrics_json["provider"] == "mock"
            assert o.before_metrics_json["available"] is True

    def test_capture_before_creates_three_scheduled_jobs(self, db_session):
        """capture_before creates 3 ScheduledJob rows with correct scheduled_for times."""
        decision = db_session.query(DecisionPack).first()
        org = db_session.query(Organization).first()

        mock_snapshot = _make_snapshot()

        with patch(
            "backend.src.services.outcome_service.MetricsProviderFactory"
        ) as mock_factory:
            mock_provider = MagicMock()
            mock_provider.get_snapshot.return_value = mock_snapshot
            mock_factory.get_provider.return_value = mock_provider

            collector = OutcomeCollector(db_session)
            outcomes = collector.capture_before(decision, org.id)

        db_session.commit()

        jobs = db_session.query(ScheduledJob).filter(
            ScheduledJob.org_id == org.id,
            ScheduledJob.job_type == "outcome_capture",
        ).all()

        assert len(jobs) == 3

        # Build a map of outcome_id -> horizon_minutes for easy lookup
        outcome_map = {o.id: o for o in outcomes}

        for job in jobs:
            assert job.completed_at is None
            # reference_id should point to a valid DecisionOutcome
            assert job.reference_id in outcome_map
            outcome = outcome_map[job.reference_id]
            expected_time = outcome.executed_at + timedelta(minutes=outcome.horizon_minutes)
            # Allow a 1-second tolerance for timestamp comparison
            assert abs((job.scheduled_for - expected_time).total_seconds()) < 1


# ── Tests: OutcomeCollector.capture_after ─────────────────────────────────────


class TestCaptureAfter:

    def test_capture_after_computes_delta(self, db_session):
        """capture_after computes delta = after - before per metric key."""
        decision = db_session.query(DecisionPack).first()
        org = db_session.query(Organization).first()

        # Pre-create a DecisionOutcome with before_metrics_json set
        outcome = DecisionOutcome(
            id=uuid4(),
            org_id=org.id,
            decision_id=decision.id,
            entity_type="adset",
            entity_id="adset_outcome_1",
            action_type=ActionType.BUDGET_CHANGE,
            executed_at=decision.executed_at,
            horizon_minutes=60,
            before_metrics_json={
                "provider": "mock",
                "available": True,
                "metrics": {"spend": 100.0, "ctr": 0.05, "cpa": 10.0, "roas": 3.0},
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
        db_session.add(outcome)
        db_session.commit()

        # Mock the after snapshot with changed metrics
        after_snapshot = _make_snapshot(
            metrics={"spend": 120.0, "ctr": 0.06, "cpa": 9.0, "roas": 3.5},
        )

        with patch(
            "backend.src.services.outcome_service.MetricsProviderFactory"
        ) as mock_factory:
            mock_provider = MagicMock()
            mock_provider.get_snapshot.return_value = after_snapshot
            mock_factory.get_provider.return_value = mock_provider

            # Patch MemoryUpdater to avoid circular import issues
            with patch(
                "backend.src.services.outcome_service.MemoryUpdater",
                create=True,
            ):
                collector = OutcomeCollector(db_session)
                result = collector.capture_after(outcome.id)

        db_session.commit()

        assert result is not None
        assert result.after_metrics_json is not None
        assert result.after_metrics_json["metrics"]["spend"] == 120.0

        # Verify delta computation: after - before
        delta = result.delta_metrics_json
        assert delta is not None
        assert delta["spend"] == pytest.approx(20.0, abs=0.001)
        assert delta["ctr"] == pytest.approx(0.01, abs=0.001)
        assert delta["cpa"] == pytest.approx(-1.0, abs=0.001)
        assert delta["roas"] == pytest.approx(0.5, abs=0.001)

        # Verify a label was assigned
        assert result.outcome_label is not None
        assert result.outcome_label != OutcomeLabel.UNKNOWN

    def test_capture_after_idempotent(self, db_session):
        """capture_after is idempotent (second call is a no-op when after_metrics already set)."""
        decision = db_session.query(DecisionPack).first()
        org = db_session.query(Organization).first()

        # Pre-create a DecisionOutcome that already has after_metrics_json set
        outcome = DecisionOutcome(
            id=uuid4(),
            org_id=org.id,
            decision_id=decision.id,
            entity_type="adset",
            entity_id="adset_outcome_1",
            action_type=ActionType.BUDGET_CHANGE,
            executed_at=decision.executed_at,
            horizon_minutes=1440,
            before_metrics_json={
                "provider": "mock",
                "available": True,
                "metrics": {"spend": 100.0, "cpa": 10.0, "roas": 3.0},
                "timestamp": datetime.utcnow().isoformat(),
            },
            after_metrics_json={
                "provider": "mock",
                "available": True,
                "metrics": {"spend": 110.0, "cpa": 9.5, "roas": 3.2},
                "timestamp": datetime.utcnow().isoformat(),
            },
            delta_metrics_json={"spend": 10.0, "cpa": -0.5, "roas": 0.2},
            outcome_label=OutcomeLabel.WIN,
            confidence=0.8,
        )
        db_session.add(outcome)
        db_session.commit()

        # capture_after should return the existing outcome without calling the provider
        with patch(
            "backend.src.services.outcome_service.MetricsProviderFactory"
        ) as mock_factory:
            mock_provider = MagicMock()
            mock_factory.get_provider.return_value = mock_provider

            collector = OutcomeCollector(db_session)
            result = collector.capture_after(outcome.id)

        # Provider should NOT have been called (idempotent)
        mock_provider.get_snapshot.assert_not_called()

        # Result should be the same outcome, unchanged
        assert result is not None
        assert result.id == outcome.id
        assert result.outcome_label == OutcomeLabel.WIN
        assert result.confidence == 0.8


# ── Tests: OutcomeLabeler ────────────────────────────────────────────────────


class TestOutcomeLabeler:

    def test_label_win_roas_up_cpa_down(self, db_session):
        """ROAS up beyond noise band + CPA down (within noise) -> WIN."""
        decision = db_session.query(DecisionPack).first()
        org = db_session.query(Organization).first()

        outcome = DecisionOutcome(
            id=uuid4(),
            org_id=org.id,
            decision_id=decision.id,
            entity_type="adset",
            entity_id="adset_outcome_1",
            action_type=ActionType.BUDGET_CHANGE,
            executed_at=datetime.utcnow(),
            horizon_minutes=60,
            before_metrics_json={
                "provider": "mock",
                "available": True,
                "metrics": {"roas": 3.0, "cpa": 10.0},
                "timestamp": datetime.utcnow().isoformat(),
            },
            after_metrics_json={
                "provider": "mock",
                "available": True,
                "metrics": {"roas": 3.2, "cpa": 9.5},
                "timestamp": datetime.utcnow().isoformat(),
            },
            # roas_delta = 0.2 (> default roas_noise 0.05)
            # cpa_delta = -0.5 (< default cpa_noise 0.1)
            delta_metrics_json={"roas": 0.2, "cpa": -0.5},
        )

        labeler = OutcomeLabeler()
        label, confidence = labeler.label(outcome)

        assert label == OutcomeLabel.WIN
        assert confidence > 0.0
        assert confidence <= 1.0

    def test_label_loss_cpa_up_hard(self, db_session):
        """CPA spike > cpa_noise * 1.5 -> LOSS."""
        decision = db_session.query(DecisionPack).first()
        org = db_session.query(Organization).first()

        outcome = DecisionOutcome(
            id=uuid4(),
            org_id=org.id,
            decision_id=decision.id,
            entity_type="adset",
            entity_id="adset_outcome_1",
            action_type=ActionType.BUDGET_CHANGE,
            executed_at=datetime.utcnow(),
            horizon_minutes=60,
            before_metrics_json={
                "provider": "mock",
                "available": True,
                "metrics": {"roas": 3.0, "cpa": 10.0},
                "timestamp": datetime.utcnow().isoformat(),
            },
            after_metrics_json={
                "provider": "mock",
                "available": True,
                "metrics": {"roas": 3.0, "cpa": 10.5},
                "timestamp": datetime.utcnow().isoformat(),
            },
            # cpa_delta = 0.5 (> default cpa_noise 0.1 * 1.5 = 0.15)
            # roas_delta = 0.0 (not enough for WIN)
            delta_metrics_json={"roas": 0.0, "cpa": 0.5},
        )

        labeler = OutcomeLabeler()
        label, confidence = labeler.label(outcome)

        assert label == OutcomeLabel.LOSS
        assert confidence > 0.0
        assert confidence <= 1.0

    def test_label_neutral_within_noise_band(self, db_session):
        """All deltas within noise band -> NEUTRAL."""
        decision = db_session.query(DecisionPack).first()
        org = db_session.query(Organization).first()

        outcome = DecisionOutcome(
            id=uuid4(),
            org_id=org.id,
            decision_id=decision.id,
            entity_type="adset",
            entity_id="adset_outcome_1",
            action_type=ActionType.BUDGET_CHANGE,
            executed_at=datetime.utcnow(),
            horizon_minutes=60,
            before_metrics_json={
                "provider": "mock",
                "available": True,
                "metrics": {"roas": 3.0, "cpa": 10.0, "ctr": 0.05},
                "timestamp": datetime.utcnow().isoformat(),
            },
            after_metrics_json={
                "provider": "mock",
                "available": True,
                "metrics": {"roas": 3.01, "cpa": 10.01, "ctr": 0.051},
                "timestamp": datetime.utcnow().isoformat(),
            },
            # All deltas are tiny, within default noise bands
            # roas_delta = 0.01 (< roas_noise 0.05 -> not WIN)
            # cpa_delta = 0.01 (< cpa_noise * 1.5 = 0.15 -> not LOSS)
            # roas_delta = 0.01 (> -roas_noise * 1.5 = -0.075 -> not LOSS)
            delta_metrics_json={"roas": 0.01, "cpa": 0.01, "ctr": 0.001},
        )

        labeler = OutcomeLabeler()
        label, confidence = labeler.label(outcome)

        assert label == OutcomeLabel.NEUTRAL
        assert confidence == 0.5

    def test_label_unknown_no_metrics(self, db_session):
        """No delta metrics -> UNKNOWN."""
        decision = db_session.query(DecisionPack).first()
        org = db_session.query(Organization).first()

        outcome = DecisionOutcome(
            id=uuid4(),
            org_id=org.id,
            decision_id=decision.id,
            entity_type="adset",
            entity_id="adset_outcome_1",
            action_type=ActionType.BUDGET_CHANGE,
            executed_at=datetime.utcnow(),
            horizon_minutes=60,
            before_metrics_json={},
            after_metrics_json={},
            delta_metrics_json={},
        )

        labeler = OutcomeLabeler()
        label, confidence = labeler.label(outcome)

        assert label == OutcomeLabel.UNKNOWN
        assert confidence == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
