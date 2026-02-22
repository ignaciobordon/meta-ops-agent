"""
Sprint 5 – MemoryUpdater Tests
Tests entity memory (EMA baselines, trust score) and feature memory (win_rate,
action_type tracking) produced by MemoryUpdater.update_from_outcome().
"""
import pytest
from datetime import datetime
from uuid import uuid4

from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PostgreSQL UUID type for SQLite compatibility
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

from backend.src.database.models import (
    Base,
    ActionType,
    DecisionOutcome,
    DecisionPack,
    DecisionState,
    EntityMemory,
    FeatureMemory,
    FeatureType,
    MetaConnection,
    AdAccount,
    Organization,
    OutcomeLabel,
    User,
    UserOrgRole,
    RoleEnum,
)
from backend.src.services.memory_service import MemoryUpdater


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

    # Seed minimal org + user + connection + ad_account + decision_pack
    org_id = uuid4()
    user_id = uuid4()
    connection_id = uuid4()
    ad_account_id = uuid4()
    decision_id = uuid4()

    org = Organization(
        id=org_id,
        name="Memory Test Org",
        slug="memory-test",
        operator_armed=True,
        created_at=datetime.utcnow(),
    )
    session.add(org)

    user = User(
        id=user_id,
        email="mem@test.com",
        name="Memory Tester",
        password_hash="hashed",
        created_at=datetime.utcnow(),
    )
    session.add(user)

    role = UserOrgRole(
        id=uuid4(),
        user_id=user_id,
        org_id=org_id,
        role=RoleEnum.ADMIN,
        assigned_at=datetime.utcnow(),
    )
    session.add(role)

    connection = MetaConnection(
        id=connection_id,
        org_id=org_id,
        access_token_encrypted="enc_test_token",
        status="active",
        connected_at=datetime.utcnow(),
    )
    session.add(connection)

    ad_account = AdAccount(
        id=ad_account_id,
        connection_id=connection_id,
        meta_ad_account_id="act_mem_001",
        name="Memory Test Ad Account",
        currency="USD",
        synced_at=datetime.utcnow(),
    )
    session.add(ad_account)

    # A DecisionPack is required as FK target for DecisionOutcome.decision_id
    decision_pack = DecisionPack(
        id=decision_id,
        ad_account_id=ad_account_id,
        created_by_user_id=user_id,
        state=DecisionState.EXECUTED,
        trace_id="trace-mem-test",
        action_type=ActionType.BUDGET_CHANGE,
        entity_type="adset",
        entity_id="adset_mem_001",
        entity_name="Memory Test Adset",
        action_request={"test": True},
        created_at=datetime.utcnow(),
    )
    session.add(decision_pack)

    session.commit()

    # Attach IDs for easy access in tests
    session._test_org_id = org_id
    session._test_decision_id = decision_id

    yield session

    session.close()


def _make_outcome(
    session,
    outcome_label: OutcomeLabel,
    action_type: ActionType = ActionType.BUDGET_CHANGE,
    entity_type: str = "adset",
    entity_id: str = "adset_mem_001",
    after_metrics_json: dict = None,
    delta_metrics_json: dict = None,
) -> DecisionOutcome:
    """Helper: create and persist a DecisionOutcome row."""
    outcome = DecisionOutcome(
        id=uuid4(),
        org_id=session._test_org_id,
        decision_id=session._test_decision_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action_type=action_type,
        executed_at=datetime.utcnow(),
        horizon_minutes=1440,
        before_metrics_json={"metrics": {}},
        after_metrics_json=after_metrics_json or {"metrics": {}},
        delta_metrics_json=delta_metrics_json or {},
        outcome_label=outcome_label,
        confidence=0.8,
    )
    session.add(outcome)
    session.commit()
    return outcome


# ── Tests ────────────────────────────────────────────────────────────────────


class TestEntityMemoryCreation:
    """Test 1: Entity memory created on first outcome."""

    def test_entity_memory_created_on_first_outcome(self, db_session):
        """First outcome for an entity inserts a new EntityMemory row."""
        # No entity memory should exist yet
        count_before = db_session.query(EntityMemory).count()
        assert count_before == 0

        outcome = _make_outcome(
            db_session,
            outcome_label=OutcomeLabel.WIN,
            after_metrics_json={"metrics": {"spend": 100.0}},
        )

        updater = MemoryUpdater(db_session)
        updater.update_from_outcome(outcome)
        db_session.commit()

        mem = db_session.query(EntityMemory).filter(
            EntityMemory.org_id == db_session._test_org_id,
            EntityMemory.entity_type == "adset",
            EntityMemory.entity_id == "adset_mem_001",
        ).first()

        assert mem is not None
        assert mem.trust_score is not None
        assert mem.baseline_ema_json is not None
        assert mem.last_outcome_label == OutcomeLabel.WIN


class TestEMAFormula:
    """Test 2: EMA formula correct — new_ema = 0.3 * new_value + 0.7 * old_ema."""

    def test_ema_formula_correct(self, db_session):
        """Second outcome applies EMA: 0.3 * new + 0.7 * old."""
        # First outcome seeds the EMA with the raw value
        outcome1 = _make_outcome(
            db_session,
            outcome_label=OutcomeLabel.WIN,
            after_metrics_json={"metrics": {"spend": 100.0}},
        )
        updater = MemoryUpdater(db_session)
        updater.update_from_outcome(outcome1)
        db_session.commit()

        mem = db_session.query(EntityMemory).first()
        assert mem.baseline_ema_json["spend"] == 100.0  # First observation = value

        # Second outcome: EMA = 0.3 * 200 + 0.7 * 100 = 60 + 70 = 130
        outcome2 = _make_outcome(
            db_session,
            outcome_label=OutcomeLabel.WIN,
            after_metrics_json={"metrics": {"spend": 200.0}},
        )
        updater.update_from_outcome(outcome2)
        db_session.commit()

        db_session.refresh(mem)
        expected_ema = 0.3 * 200.0 + 0.7 * 100.0  # 130.0
        assert mem.baseline_ema_json["spend"] == pytest.approx(expected_ema, abs=1e-4)


class TestTrustIncrease:
    """Test 3: Trust increases on WIN (+5, starting from 50 -> 55)."""

    def test_trust_increases_on_win(self, db_session):
        """WIN outcome increases trust by +5 from initial 50."""
        outcome = _make_outcome(
            db_session,
            outcome_label=OutcomeLabel.WIN,
            after_metrics_json={"metrics": {"ctr": 0.05}},
        )

        updater = MemoryUpdater(db_session)
        updater.update_from_outcome(outcome)
        db_session.commit()

        mem = db_session.query(EntityMemory).first()
        assert mem.trust_score == pytest.approx(55.0)


class TestTrustDecrease:
    """Test 4: Trust decreases on LOSS (-10, starting from 50 -> 40)."""

    def test_trust_decreases_on_loss(self, db_session):
        """LOSS outcome decreases trust by -10 from initial 50."""
        outcome = _make_outcome(
            db_session,
            outcome_label=OutcomeLabel.LOSS,
            after_metrics_json={"metrics": {"ctr": 0.01}},
        )

        updater = MemoryUpdater(db_session)
        updater.update_from_outcome(outcome)
        db_session.commit()

        mem = db_session.query(EntityMemory).first()
        assert mem.trust_score == pytest.approx(40.0)


class TestTrustClamping:
    """Test 5: Trust clamped to 0-100 range."""

    def test_trust_clamped_to_zero_on_loss(self, db_session):
        """Trust=5 + LOSS(-10) should clamp to 0, not go negative."""
        # First outcome to create entity memory (trust starts at 50)
        outcome1 = _make_outcome(
            db_session,
            outcome_label=OutcomeLabel.LOSS,
            after_metrics_json={"metrics": {"spend": 10.0}},
        )
        updater = MemoryUpdater(db_session)
        updater.update_from_outcome(outcome1)
        db_session.commit()

        # Manually set trust_score to 5 to test clamping
        mem = db_session.query(EntityMemory).first()
        mem.trust_score = 5.0
        db_session.commit()

        # Another LOSS: 5 + (-10) = -5 -> clamped to 0
        outcome2 = _make_outcome(
            db_session,
            outcome_label=OutcomeLabel.LOSS,
            after_metrics_json={"metrics": {"spend": 10.0}},
        )
        updater.update_from_outcome(outcome2)
        db_session.commit()

        db_session.refresh(mem)
        assert mem.trust_score == pytest.approx(0.0)

    def test_trust_clamped_to_100_on_win(self, db_session):
        """Trust=98 + WIN(+5) should clamp to 100, not exceed 100."""
        # First outcome to create entity memory
        outcome1 = _make_outcome(
            db_session,
            outcome_label=OutcomeLabel.WIN,
            after_metrics_json={"metrics": {"spend": 10.0}},
        )
        updater = MemoryUpdater(db_session)
        updater.update_from_outcome(outcome1)
        db_session.commit()

        # Manually set trust_score to 98
        mem = db_session.query(EntityMemory).first()
        mem.trust_score = 98.0
        db_session.commit()

        # Another WIN: 98 + 5 = 103 -> clamped to 100
        outcome2 = _make_outcome(
            db_session,
            outcome_label=OutcomeLabel.WIN,
            after_metrics_json={"metrics": {"spend": 10.0}},
        )
        updater.update_from_outcome(outcome2)
        db_session.commit()

        db_session.refresh(mem)
        assert mem.trust_score == pytest.approx(100.0)


class TestFeatureMemoryActionType:
    """Test 6: Feature memory tracks by action_type."""

    def test_feature_memory_created_with_action_type(self, db_session):
        """FeatureMemory row created with feature_type=ACTION_TYPE for the outcome's action_type."""
        outcome = _make_outcome(
            db_session,
            outcome_label=OutcomeLabel.WIN,
            action_type=ActionType.BUDGET_CHANGE,
            after_metrics_json={"metrics": {"spend": 50.0}},
            delta_metrics_json={"spend": 5.0},
        )

        updater = MemoryUpdater(db_session)
        updater.update_from_outcome(outcome)
        db_session.commit()

        feat = db_session.query(FeatureMemory).filter(
            FeatureMemory.org_id == db_session._test_org_id,
            FeatureMemory.feature_type == FeatureType.ACTION_TYPE,
            FeatureMemory.feature_key == ActionType.BUDGET_CHANGE.value,
        ).first()

        assert feat is not None
        assert feat.samples == 1
        assert feat.win_rate == pytest.approx(1.0)  # WIN -> is_win = 1.0
        assert feat.avg_delta_json["spend"] == pytest.approx(5.0)


class TestWinRateRunningAverage:
    """Test 7: Win rate running average correct."""

    def test_win_rate_running_average(self, db_session):
        """2 outcomes (1 WIN + 1 LOSS) -> win_rate = 0.5."""
        updater = MemoryUpdater(db_session)

        # First outcome: WIN (win_rate = 1.0, samples = 1)
        outcome_win = _make_outcome(
            db_session,
            outcome_label=OutcomeLabel.WIN,
            action_type=ActionType.ADSET_PAUSE,
            after_metrics_json={"metrics": {"ctr": 0.05}},
            delta_metrics_json={"ctr": 0.01},
        )
        updater.update_from_outcome(outcome_win)
        db_session.commit()

        feat = db_session.query(FeatureMemory).filter(
            FeatureMemory.feature_type == FeatureType.ACTION_TYPE,
            FeatureMemory.feature_key == ActionType.ADSET_PAUSE.value,
        ).first()
        assert feat is not None
        assert feat.win_rate == pytest.approx(1.0)
        assert feat.samples == 1

        # Second outcome: LOSS (win_rate = (1.0*1 + 0.0) / 2 = 0.5, samples = 2)
        outcome_loss = _make_outcome(
            db_session,
            outcome_label=OutcomeLabel.LOSS,
            action_type=ActionType.ADSET_PAUSE,
            after_metrics_json={"metrics": {"ctr": 0.02}},
            delta_metrics_json={"ctr": -0.01},
        )
        updater.update_from_outcome(outcome_loss)
        db_session.commit()

        db_session.refresh(feat)
        assert feat.win_rate == pytest.approx(0.5)
        assert feat.samples == 2


class TestUnknownOutcomeSkipped:
    """Edge case: UNKNOWN outcomes are skipped entirely."""

    def test_unknown_outcome_skipped(self, db_session):
        """UNKNOWN outcome does not create entity or feature memory."""
        outcome = _make_outcome(
            db_session,
            outcome_label=OutcomeLabel.UNKNOWN,
            after_metrics_json={"metrics": {"spend": 100.0}},
        )

        updater = MemoryUpdater(db_session)
        updater.update_from_outcome(outcome)
        db_session.commit()

        entity_count = db_session.query(EntityMemory).count()
        feature_count = db_session.query(FeatureMemory).count()
        assert entity_count == 0
        assert feature_count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
