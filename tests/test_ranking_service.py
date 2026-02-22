"""
Unit tests for DecisionRanker (Sprint 5 – Decision Ranking Engine).
Tests scoring formula: Total = Impact * Confidence * Freshness - Risk
covering 6 scenarios: sorted output, high win_rate impact, neutral defaults,
freshness penalty, policy risk, and re-ranking version increment.
"""
import pytest
from datetime import datetime, timedelta
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
    DecisionRanking,
    DecisionState,
    EntityMemory,
    FeatureMemory,
    FeatureType,
    Organization,
    User,
    MetaConnection,
    AdAccount,
    OutcomeLabel,
)
from backend.src.services.ranking_service import DecisionRanker


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

    # Create test organization
    org = Organization(
        id=org_id,
        name="Test Org",
        slug="test-org-ranking",
        operator_armed=True,
        created_at=datetime.utcnow(),
    )
    session.add(org)

    # Create test user
    user = User(
        id=user_id,
        email="ranker@example.com",
        name="Ranker User",
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
        meta_ad_account_id="act_rank_001",
        name="Ranking Test Ad Account",
        currency="USD",
        synced_at=datetime.utcnow(),
    )
    session.add(ad_account)

    # Create two DecisionPack records in PENDING_APPROVAL state
    decision_a = DecisionPack(
        id=uuid4(),
        ad_account_id=ad_account_id,
        created_by_user_id=user_id,
        state=DecisionState.PENDING_APPROVAL,
        trace_id=f"trace-rank-a-{uuid4().hex[:8]}",
        action_type=ActionType.BUDGET_CHANGE,
        entity_type="adset",
        entity_id="adset_100",
        entity_name="Test Adset A",
        action_request={"current_budget": 100.0, "new_budget": 110.0},
        risk_score=0.0,
        policy_checks=[],
        created_at=datetime.utcnow(),
    )
    session.add(decision_a)

    decision_b = DecisionPack(
        id=uuid4(),
        ad_account_id=ad_account_id,
        created_by_user_id=user_id,
        state=DecisionState.PENDING_APPROVAL,
        trace_id=f"trace-rank-b-{uuid4().hex[:8]}",
        action_type=ActionType.BUDGET_CHANGE,
        entity_type="adset",
        entity_id="adset_200",
        entity_name="Test Adset B",
        action_request={"current_budget": 200.0, "new_budget": 220.0},
        risk_score=0.0,
        policy_checks=[],
        created_at=datetime.utcnow(),
    )
    session.add(decision_b)

    session.commit()

    yield session

    session.close()


# ── Helper ───────────────────────────────────────────────────────────────────


def _make_decision(session, ad_account_id, user_id, **overrides):
    """Create a DecisionPack with sensible defaults, allowing overrides."""
    defaults = dict(
        id=uuid4(),
        ad_account_id=ad_account_id,
        created_by_user_id=user_id,
        state=DecisionState.PENDING_APPROVAL,
        trace_id=f"trace-{uuid4().hex[:12]}",
        action_type=ActionType.BUDGET_CHANGE,
        entity_type="adset",
        entity_id="adset_999",
        entity_name="Helper Decision",
        action_request={"current_budget": 100.0, "new_budget": 110.0},
        risk_score=0.0,
        policy_checks=[],
        created_at=datetime.utcnow(),
    )
    defaults.update(overrides)
    decision = DecisionPack(**defaults)
    session.add(decision)
    session.flush()
    return decision


# ── Tests ────────────────────────────────────────────────────────────────────


class TestRankedOutputSorting:
    """1. Ranked output is sorted by score_total descending."""

    def test_ranked_output_sorted_by_score_total_desc(self, db_session):
        """Create 2+ decisions, rank them, verify the returned list is
        sorted by score_total in descending order."""
        org = db_session.query(Organization).first()
        ad_account = db_session.query(AdAccount).first()
        user = db_session.query(User).first()

        # Create a third decision with a different action_type so it gets
        # a different score through the feature memory lookup path.
        decision_c = _make_decision(
            db_session,
            ad_account.id,
            user.id,
            action_type=ActionType.ADSET_PAUSE,
            entity_id="adset_300",
            entity_name="Test Adset C",
        )

        decisions = db_session.query(DecisionPack).filter(
            DecisionPack.state == DecisionState.PENDING_APPROVAL,
        ).all()
        assert len(decisions) >= 3

        ranker = DecisionRanker()
        rankings = ranker.rank_decisions(org.id, decisions, db_session)

        assert len(rankings) == len(decisions)

        # Verify descending order
        for i in range(len(rankings) - 1):
            assert rankings[i].score_total >= rankings[i + 1].score_total, (
                f"Ranking at index {i} (score={rankings[i].score_total}) should be "
                f">= ranking at index {i+1} (score={rankings[i+1].score_total})"
            )


class TestHighWinRateImpact:
    """2. High win_rate in FeatureMemory leads to higher impact score."""

    def test_high_win_rate_produces_higher_impact(self, db_session):
        """Create a FeatureMemory with high win_rate for BUDGET_CHANGE,
        rank a decision, verify score_impact is higher than the default 0.4."""
        org = db_session.query(Organization).first()
        ad_account = db_session.query(AdAccount).first()
        user = db_session.query(User).first()

        # Insert FeatureMemory with high win_rate and enough samples
        feature = FeatureMemory(
            id=uuid4(),
            org_id=org.id,
            feature_type=FeatureType.ACTION_TYPE,
            feature_key=ActionType.BUDGET_CHANGE.value,
            win_rate=0.85,
            samples=20,
            updated_at=datetime.utcnow(),
        )
        db_session.add(feature)
        db_session.flush()

        decision = _make_decision(
            db_session,
            ad_account.id,
            user.id,
            action_type=ActionType.BUDGET_CHANGE,
            entity_id="adset_high_wr",
            entity_name="High WinRate Decision",
        )

        ranker = DecisionRanker()
        rankings = ranker.rank_decisions(org.id, [decision], db_session)

        assert len(rankings) == 1
        ranking = rankings[0]

        # With win_rate=0.85 and samples=20 the exploration bonus is 0.0,
        # so impact should be 0.85 -- well above the default 0.4
        assert ranking.score_impact > 0.4, (
            f"Impact {ranking.score_impact} should exceed default 0.4 "
            f"when win_rate is 0.85"
        )
        assert ranking.score_impact == pytest.approx(0.85, abs=0.01)


class TestNoMemoryNeutralDefaults:
    """3. No memory records lead to neutral default scores."""

    def test_no_memory_gives_neutral_defaults(self, db_session):
        """With no FeatureMemory or EntityMemory, impact and confidence
        should fall in the 0.3-0.5 neutral range."""
        org = db_session.query(Organization).first()
        ad_account = db_session.query(AdAccount).first()
        user = db_session.query(User).first()

        # Use a unique action_type with no FeatureMemory record
        decision = _make_decision(
            db_session,
            ad_account.id,
            user.id,
            action_type=ActionType.CREATIVE_SWAP,
            entity_id="adset_no_mem",
            entity_name="No Memory Decision",
        )

        ranker = DecisionRanker()
        rankings = ranker.rank_decisions(org.id, [decision], db_session)

        assert len(rankings) == 1
        ranking = rankings[0]

        # Impact default is 0.4
        assert 0.3 <= ranking.score_impact <= 0.5, (
            f"Default impact {ranking.score_impact} should be in [0.3, 0.5]"
        )

        # Confidence with no entity memory: trust=0.5, sample_factor=0.1
        # confidence = 0.5 * 0.6 + 0.1 * 0.4 = 0.34
        assert 0.3 <= ranking.score_confidence <= 0.5, (
            f"Default confidence {ranking.score_confidence} should be in [0.3, 0.5]"
        )


class TestFreshnessPenalty:
    """4. Recent similar action penalizes freshness score."""

    def test_recent_similar_action_reduces_freshness(self, db_session):
        """Create a DecisionOutcome with recent executed_at for the same
        entity+action_type, verify freshness < 1.0."""
        org = db_session.query(Organization).first()
        ad_account = db_session.query(AdAccount).first()
        user = db_session.query(User).first()
        decisions = db_session.query(DecisionPack).filter(
            DecisionPack.state == DecisionState.PENDING_APPROVAL,
        ).all()
        # Use the first fixture decision as the reference for the outcome
        ref_decision = decisions[0]

        entity_id_shared = "adset_fresh_test"

        # Create a recent DecisionOutcome for the same entity + action_type
        outcome = DecisionOutcome(
            id=uuid4(),
            org_id=org.id,
            decision_id=ref_decision.id,
            entity_type="adset",
            entity_id=entity_id_shared,
            action_type=ActionType.BUDGET_CHANGE,
            executed_at=datetime.utcnow() - timedelta(hours=6),  # within 48h
            horizon_minutes=1440,
            outcome_label=OutcomeLabel.WIN,
            confidence=0.8,
        )
        db_session.add(outcome)
        db_session.flush()

        # Create the decision targeting the same entity + action_type
        decision = _make_decision(
            db_session,
            ad_account.id,
            user.id,
            action_type=ActionType.BUDGET_CHANGE,
            entity_id=entity_id_shared,
            entity_name="Freshness Test Decision",
        )

        ranker = DecisionRanker()
        rankings = ranker.rank_decisions(org.id, [decision], db_session)

        assert len(rankings) == 1
        ranking = rankings[0]

        # With 1 recent outcome: freshness = max(0.2, 1.0 - 0.3*1) = 0.7
        assert ranking.score_freshness < 1.0, (
            f"Freshness {ranking.score_freshness} should be < 1.0 "
            f"when a recent similar action exists"
        )
        assert ranking.score_freshness == pytest.approx(0.7, abs=0.05)


class TestPolicyViolationRisk:
    """5. Policy violations increase the risk score."""

    def test_blocking_violations_increase_risk(self, db_session):
        """Create a decision with policy_checks containing blocking violations,
        verify risk > 0."""
        org = db_session.query(Organization).first()
        ad_account = db_session.query(AdAccount).first()
        user = db_session.query(User).first()

        policy_checks = [
            {"rule": "max_budget_pct", "passed": False, "severity": "blocking"},
            {"rule": "min_spend_check", "passed": False, "severity": "warning"},
        ]

        decision = _make_decision(
            db_session,
            ad_account.id,
            user.id,
            entity_id="adset_risky",
            entity_name="Risky Decision",
            policy_checks=policy_checks,
        )

        ranker = DecisionRanker()
        rankings = ranker.rank_decisions(org.id, [decision], db_session)

        assert len(rankings) == 1
        ranking = rankings[0]

        # 1 blocking (+0.3) + 1 warning (+0.1) = 0.4 risk
        assert ranking.score_risk > 0, (
            f"Risk {ranking.score_risk} should be > 0 with policy violations"
        )
        assert ranking.score_risk == pytest.approx(0.4, abs=0.05)


class TestReRankingVersionIncrement:
    """6. Re-ranking the same decision increments rank_version."""

    def test_reranking_increments_rank_version(self, db_session):
        """Rank the same decision twice and verify rank_version goes from 1 to 2."""
        org = db_session.query(Organization).first()
        ad_account = db_session.query(AdAccount).first()
        user = db_session.query(User).first()

        decision = _make_decision(
            db_session,
            ad_account.id,
            user.id,
            entity_id="adset_rerank",
            entity_name="ReRank Decision",
        )

        ranker = DecisionRanker()

        # First ranking
        rankings_v1 = ranker.rank_decisions(org.id, [decision], db_session)
        assert len(rankings_v1) == 1
        assert rankings_v1[0].rank_version == 1

        # Second ranking (re-rank the same decision)
        rankings_v2 = ranker.rank_decisions(org.id, [decision], db_session)
        assert len(rankings_v2) == 1
        assert rankings_v2[0].rank_version == 2, (
            f"rank_version should be 2 after re-ranking, got {rankings_v2[0].rank_version}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
