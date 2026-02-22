"""
Sprint 5 -- End-to-End Learning Loop Tests
Tests the full outcome -> memory -> ranking -> policy feedback loop across
8 scenarios covering labeling, trust propagation, ranking, and dynamic policy.
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
    Creative,
    DecisionPack,
    DecisionState,
    ActionType,
    DecisionOutcome,
    DecisionRanking,
    EntityMemory,
    FeatureMemory,
    FeatureType,
    OutcomeLabel,
    ScheduledJob,
)
from backend.src.services.outcome_service import OutcomeCollector, OutcomeLabeler
from backend.src.services.memory_service import MemoryUpdater
from backend.src.services.ranking_service import DecisionRanker
from backend.src.providers.metrics_provider import MetricsSnapshot
from src.core.policy_engine import PolicyEngine, PolicyContext
from src.schemas.policy import ActionRequest


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_session():
    """Create an in-memory SQLite database with seeded test data."""
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

    # Organization
    org = Organization(
        id=org_id,
        name="E2E Loop Org",
        slug="e2e-loop-org",
        operator_armed=True,
        created_at=datetime.utcnow(),
    )
    session.add(org)

    # User
    user = User(
        id=user_id,
        email="e2e@loop.com",
        name="E2E Tester",
        password_hash="hashed",
        created_at=datetime.utcnow(),
    )
    session.add(user)

    # MetaConnection (active -- triggers MetaMetricsProvider in factory)
    connection = MetaConnection(
        id=connection_id,
        org_id=org_id,
        access_token_encrypted="enc_e2e_token",
        status="active",
        connected_at=datetime.utcnow(),
    )
    session.add(connection)

    # AdAccount
    ad_account = AdAccount(
        id=ad_account_id,
        connection_id=connection_id,
        meta_ad_account_id="act_e2e_001",
        name="E2E Ad Account",
        currency="USD",
        synced_at=datetime.utcnow(),
    )
    session.add(ad_account)

    # Creative with performance data (so CsvProvider would work for this entity)
    creative = Creative(
        id=uuid4(),
        ad_account_id=ad_account_id,
        meta_ad_id="adset_e2e_001",
        name="E2E Creative",
        impressions=10000,
        clicks=250,
        spend=500.0,
        conversions=25,
        created_at=datetime.utcnow(),
    )
    session.add(creative)

    session.commit()

    # Attach IDs for easy access in tests
    session._test_org_id = org_id
    session._test_user_id = user_id
    session._test_ad_account_id = ad_account_id

    yield session

    session.close()


def _make_decision(
    session,
    entity_id="adset_e2e_001",
    action_type=ActionType.BUDGET_CHANGE,
    entity_type="adset",
    state=DecisionState.EXECUTED,
    executed_at=None,
    risk_score=0.0,
    policy_checks=None,
) -> DecisionPack:
    """Helper: create and persist an EXECUTED DecisionPack."""
    decision = DecisionPack(
        id=uuid4(),
        ad_account_id=session._test_ad_account_id,
        created_by_user_id=session._test_user_id,
        state=state,
        trace_id=f"trace-e2e-{uuid4().hex[:8]}",
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=f"E2E {entity_id}",
        action_request={"test": True},
        rationale="E2E test decision",
        executed_at=executed_at or datetime.utcnow(),
        risk_score=risk_score,
        policy_checks=policy_checks or [],
        created_at=datetime.utcnow(),
    )
    session.add(decision)
    session.commit()
    return decision


def _make_snapshot(entity_type="adset", entity_id="adset_e2e_001", metrics=None):
    """Helper to build a MetricsSnapshot for mocking."""
    return MetricsSnapshot(
        entity_type=entity_type,
        entity_id=entity_id,
        timestamp=datetime.utcnow(),
        provider="mock",
        metrics=metrics or {"spend": 100.0, "ctr": 0.05, "cpa": 10.0, "roas": 3.0},
        available=True,
    )


def _make_outcome(
    session,
    decision,
    outcome_label,
    before_metrics=None,
    after_metrics=None,
    delta_metrics=None,
    entity_id=None,
    dry_run=False,
) -> DecisionOutcome:
    """Helper: create a fully labeled DecisionOutcome row."""
    eid = entity_id or decision.entity_id
    outcome = DecisionOutcome(
        id=uuid4(),
        org_id=session._test_org_id,
        decision_id=decision.id,
        entity_type=decision.entity_type or "adset",
        entity_id=eid,
        action_type=decision.action_type,
        executed_at=decision.executed_at or datetime.utcnow(),
        dry_run=dry_run,
        horizon_minutes=1440,
        before_metrics_json=before_metrics or {
            "provider": "mock",
            "available": True,
            "metrics": {"spend": 100.0, "ctr": 0.05, "cpa": 10.0, "roas": 3.0},
            "timestamp": datetime.utcnow().isoformat(),
        },
        after_metrics_json=after_metrics or {
            "provider": "mock",
            "available": True,
            "metrics": {"spend": 120.0, "ctr": 0.06, "cpa": 9.0, "roas": 3.5},
            "timestamp": datetime.utcnow().isoformat(),
        },
        delta_metrics_json=delta_metrics or {"spend": 20.0, "ctr": 0.01, "cpa": -1.0, "roas": 0.5},
        outcome_label=outcome_label,
        confidence=0.8,
    )
    session.add(outcome)
    session.commit()
    return outcome


# ── Scenario 1: Full Loop ────────────────────────────────────────────────────


class TestFullLoop:
    """Scenario 1: create decision -> capture_before -> simulate capture_after -> outcome labeled."""

    def test_full_loop_decision_to_labeled_outcome(self, db_session):
        """Full loop: EXECUTED decision -> capture_before -> after_metrics -> label assigned."""
        decision = _make_decision(db_session)

        mock_snapshot = _make_snapshot()

        with patch(
            "backend.src.services.outcome_service.MetricsProviderFactory"
        ) as mock_factory:
            mock_provider = MagicMock()
            mock_provider.get_snapshot.return_value = mock_snapshot
            mock_factory.get_provider.return_value = mock_provider

            collector = OutcomeCollector(db_session)
            outcomes = collector.capture_before(decision, db_session._test_org_id)

        db_session.commit()

        # We should have 3 outcomes (one per horizon)
        assert len(outcomes) == 3

        # Pick the 1h horizon outcome and simulate capture_after manually
        outcome = outcomes[0]

        # Manually set after_metrics and delta (simulating what capture_after does)
        outcome.after_metrics_json = {
            "provider": "mock",
            "available": True,
            "metrics": {"spend": 120.0, "ctr": 0.06, "cpa": 9.0, "roas": 3.5},
            "timestamp": datetime.utcnow().isoformat(),
        }

        before_metrics = outcome.before_metrics_json.get("metrics", {})
        after_metrics = outcome.after_metrics_json.get("metrics", {})
        delta = {}
        for key in set(list(before_metrics.keys()) + list(after_metrics.keys())):
            before_val = before_metrics.get(key, 0)
            after_val = after_metrics.get(key, 0)
            delta[key] = round(float(after_val) - float(before_val), 6)

        outcome.delta_metrics_json = delta

        # Label the outcome
        labeler = OutcomeLabeler()
        label, confidence = labeler.label(outcome)
        outcome.outcome_label = label
        outcome.confidence = confidence

        db_session.commit()

        # roas_delta = 0.5 > roas_noise(0.05) -> WIN
        assert outcome.outcome_label == OutcomeLabel.WIN
        assert outcome.confidence > 0.0
        assert outcome.delta_metrics_json["roas"] == pytest.approx(0.5, abs=0.001)

        # Update memory from outcome
        updater = MemoryUpdater(db_session)
        updater.update_from_outcome(outcome)
        db_session.commit()

        # Verify EntityMemory was created
        entity_mem = db_session.query(EntityMemory).filter(
            EntityMemory.org_id == db_session._test_org_id,
            EntityMemory.entity_id == "adset_e2e_001",
        ).first()
        assert entity_mem is not None
        assert entity_mem.trust_score == pytest.approx(55.0)  # 50 + 5 (WIN)
        assert entity_mem.last_outcome_label == OutcomeLabel.WIN

        # Verify FeatureMemory was created for action_type
        feature_mem = db_session.query(FeatureMemory).filter(
            FeatureMemory.org_id == db_session._test_org_id,
            FeatureMemory.feature_type == FeatureType.ACTION_TYPE,
            FeatureMemory.feature_key == ActionType.BUDGET_CHANGE.value,
        ).first()
        assert feature_mem is not None
        assert feature_mem.win_rate == pytest.approx(1.0)
        assert feature_mem.samples == 1


# ── Scenario 2: Two Wins Improve Ranking ─────────────────────────────────────


class TestTwoWinsImproveRanking:
    """Scenario 2: two WIN outcomes accumulate memory, boosting ranking score."""

    def test_accumulated_wins_boost_ranking(self, db_session):
        """Two WINs raise win_rate to 1.0 and trust to 60, so a new decision ranks higher."""
        updater = MemoryUpdater(db_session)
        ranker = DecisionRanker()

        # Create outcomes on a separate entity so freshness penalty doesn't
        # apply to the entity we actually rank.
        decision_source = _make_decision(db_session, entity_id="adset_outcome_src")

        # First WIN outcome (recorded on adset_outcome_src, action=BUDGET_CHANGE)
        outcome1 = _make_outcome(
            db_session, decision_source, OutcomeLabel.WIN,
            entity_id="adset_outcome_src",
        )
        updater.update_from_outcome(outcome1)
        db_session.commit()

        # Second WIN outcome
        outcome2 = _make_outcome(
            db_session, decision_source, OutcomeLabel.WIN,
            entity_id="adset_outcome_src",
        )
        updater.update_from_outcome(outcome2)
        db_session.commit()

        # Verify feature memory shows win_rate=1.0, samples=2
        feat = db_session.query(FeatureMemory).filter(
            FeatureMemory.org_id == db_session._test_org_id,
            FeatureMemory.feature_type == FeatureType.ACTION_TYPE,
            FeatureMemory.feature_key == ActionType.BUDGET_CHANGE.value,
        ).first()
        assert feat is not None
        assert feat.win_rate == pytest.approx(1.0)
        assert feat.samples == 2

        # Seed entity memory for the entity we will rank so it benefits from
        # the trust boost accumulated on the source entity.  Trust = 60 (50+5+5).
        entity_mem = EntityMemory(
            org_id=db_session._test_org_id,
            entity_type="adset",
            entity_id="adset_ranked",
            baseline_ema_json={},
            volatility_json={},
            trust_score=60.0,
        )
        db_session.add(entity_mem)
        db_session.commit()

        # Decision WITH accumulated feature memory + high-trust entity memory
        new_decision = _make_decision(
            db_session,
            entity_id="adset_ranked",
            action_type=ActionType.BUDGET_CHANGE,
        )

        # Baseline decision: different action_type with no feature memory,
        # and a different entity with no entity memory.
        baseline_decision = _make_decision(
            db_session,
            entity_id="adset_no_memory",
            action_type=ActionType.ADSET_PAUSE,
        )

        # Rank with memory
        rankings_with_memory = ranker.rank_decisions(
            db_session._test_org_id,
            [new_decision],
            db_session,
        )

        # Rank without memory
        rankings_no_memory = ranker.rank_decisions(
            db_session._test_org_id,
            [baseline_decision],
            db_session,
        )

        # Decision with accumulated memory should score higher
        assert rankings_with_memory[0].score_total > rankings_no_memory[0].score_total


# ── Scenario 3: Loss Decreases Trust and Increases Risk ───────────────────────


class TestLossDecreasesTrust:
    """Scenario 3: LOSS outcome drops trust and increases risk score for entity."""

    def test_loss_decreases_trust_increases_risk(self, db_session):
        """After a LOSS, entity trust drops, ranking risk score goes up."""
        updater = MemoryUpdater(db_session)
        ranker = DecisionRanker()

        decision = _make_decision(db_session, entity_id="adset_loss_001")

        # LOSS outcome with CPA spiking
        outcome = _make_outcome(
            db_session,
            decision,
            OutcomeLabel.LOSS,
            delta_metrics={"spend": 50.0, "ctr": -0.02, "cpa": 0.5, "roas": -0.3},
            entity_id="adset_loss_001",
        )
        updater.update_from_outcome(outcome)
        db_session.commit()

        # Trust should drop: 50 - 10 = 40
        entity_mem = db_session.query(EntityMemory).filter(
            EntityMemory.org_id == db_session._test_org_id,
            EntityMemory.entity_id == "adset_loss_001",
        ).first()
        assert entity_mem is not None
        assert entity_mem.trust_score == pytest.approx(40.0)
        assert entity_mem.last_outcome_label == OutcomeLabel.LOSS

        # Rank the entity -- lower trust means lower confidence factor
        new_decision = _make_decision(db_session, entity_id="adset_loss_001")
        rankings = ranker.rank_decisions(
            db_session._test_org_id,
            [new_decision],
            db_session,
        )

        # Confidence uses trust_factor = trust/100 = 0.4
        assert rankings[0].score_confidence < 0.5  # 0.4 * 0.6 + sample_factor * 0.4


# ── Scenario 4: Win Increases Trust and Impact ────────────────────────────────


class TestWinIncreasesTrustAndImpact:
    """Scenario 4: WIN outcome raises trust and raises impact score."""

    def test_win_increases_trust_and_impact(self, db_session):
        """After a WIN, entity trust goes up, impact (win_rate) goes up."""
        updater = MemoryUpdater(db_session)
        ranker = DecisionRanker()

        decision = _make_decision(db_session, entity_id="adset_win_001")

        # WIN outcome with ROAS improvement
        outcome = _make_outcome(
            db_session,
            decision,
            OutcomeLabel.WIN,
            delta_metrics={"spend": 10.0, "ctr": 0.01, "cpa": -1.0, "roas": 0.5},
            entity_id="adset_win_001",
        )
        updater.update_from_outcome(outcome)
        db_session.commit()

        # Trust should increase: 50 + 5 = 55
        entity_mem = db_session.query(EntityMemory).filter(
            EntityMemory.org_id == db_session._test_org_id,
            EntityMemory.entity_id == "adset_win_001",
        ).first()
        assert entity_mem is not None
        assert entity_mem.trust_score == pytest.approx(55.0)

        # Feature memory win_rate = 1.0 (100% wins)
        feat = db_session.query(FeatureMemory).filter(
            FeatureMemory.org_id == db_session._test_org_id,
            FeatureMemory.feature_type == FeatureType.ACTION_TYPE,
            FeatureMemory.feature_key == ActionType.BUDGET_CHANGE.value,
        ).first()
        assert feat is not None
        assert feat.win_rate == pytest.approx(1.0)

        # Rank the entity
        new_decision = _make_decision(db_session, entity_id="adset_win_001")
        rankings = ranker.rank_decisions(
            db_session._test_org_id,
            [new_decision],
            db_session,
        )

        # Impact should be >= 1.0 (win_rate 1.0 + exploration bonus)
        assert rankings[0].score_impact >= 1.0
        # Confidence trust factor = 55/100 = 0.55
        assert rankings[0].score_confidence > 0.3


# ── Scenario 5: Smart Ranking Differs from Creation Order ─────────────────────


class TestSmartOrderDiffersFromCreationOrder:
    """Scenario 5: ranked order is different from creation order."""

    def test_smart_order_differs_from_creation_order(self, db_session):
        """Decision with good memory ranks above one without, regardless of creation order."""
        updater = MemoryUpdater(db_session)
        ranker = DecisionRanker()

        # Decision 1 (created first): entity with NO memory
        decision1 = _make_decision(
            db_session,
            entity_id="adset_no_history",
            action_type=ActionType.ADSET_PAUSE,
        )

        # Decision 2 (created second): entity with good memory (WIN history)
        decision2_source = _make_decision(db_session, entity_id="adset_good_history")

        # Create a WIN outcome for decision2's entity + action_type = BUDGET_CHANGE
        outcome = _make_outcome(
            db_session,
            decision2_source,
            OutcomeLabel.WIN,
            delta_metrics={"spend": 10.0, "ctr": 0.01, "cpa": -1.0, "roas": 0.5},
            entity_id="adset_good_history",
        )
        updater.update_from_outcome(outcome)
        db_session.commit()

        # Now create the actual decision to rank (same entity, same action_type as memory)
        decision2 = _make_decision(
            db_session,
            entity_id="adset_good_history",
            action_type=ActionType.BUDGET_CHANGE,
        )

        # Creation order: [decision1, decision2]
        creation_order = [decision1.id, decision2.id]

        # Rank both together
        rankings = ranker.rank_decisions(
            db_session._test_org_id,
            [decision1, decision2],
            db_session,
        )

        ranked_order = [r.decision_id for r in rankings]

        # Decision2 (with WIN memory) should rank above decision1 (no memory)
        # Ranked order should differ from creation order
        assert ranked_order != creation_order
        assert ranked_order[0] == decision2.id


# ── Scenario 6: Dynamic Policy -- Trust 90 Relaxed Budget Cap 25% ─────────────


class TestDynamicPolicyRelaxed:
    """Scenario 6: trust=90 gets relaxed budget cap of 25%, so 22% change passes."""

    def test_trust_90_relaxed_budget_cap_allows_22_pct(self):
        """With trust=90, budget delta threshold is relaxed to 25%. A 22% change passes."""
        engine = PolicyEngine()
        request = ActionRequest(
            action_type="budget_change",
            entity_id="test_entity",
            entity_type="adset",
            payload={"current_budget": 100, "new_budget": 122},
            trace_id="test-trace-relaxed",
        )

        result = engine.validate(request, context=PolicyContext(trust_score=90))

        assert result.approved is True


# ── Scenario 7: Dynamic Policy -- Trust 20 Strict Budget Cap 15% ─────────────


class TestDynamicPolicyStrict:
    """Scenario 7: trust=20 gets strict budget cap of 15%, so 22% change is blocked."""

    def test_trust_20_strict_budget_cap_blocks_22_pct(self):
        """With trust=20, budget delta threshold is strict at 15%. A 22% change is blocked."""
        engine = PolicyEngine()
        request = ActionRequest(
            action_type="budget_change",
            entity_id="test_entity_strict",
            entity_type="adset",
            payload={"current_budget": 100, "new_budget": 122},
            trace_id="test-trace-strict",
        )

        result = engine.validate(request, context=PolicyContext(trust_score=20))

        assert result.approved is False
        blocking = result.blocking_violations()
        assert len(blocking) >= 1
        assert any("BudgetDeltaRule" in v.rule_name for v in blocking)


# ── Scenario 8: Dry Run Outcomes Still Tracked ────────────────────────────────


class TestDryRunOutcomesTracked:
    """Scenario 8: dry_run=True outcomes are still labeled and memory-updated."""

    def test_dry_run_outcome_labeled_and_tracked(self, db_session):
        """An outcome with dry_run=True gets labeled and updates memory."""
        updater = MemoryUpdater(db_session)

        decision = _make_decision(db_session, entity_id="adset_dry_run")

        # Create a dry_run outcome with WIN-worthy metrics
        outcome = _make_outcome(
            db_session,
            decision,
            OutcomeLabel.WIN,
            delta_metrics={"spend": 10.0, "ctr": 0.01, "cpa": -1.0, "roas": 0.5},
            entity_id="adset_dry_run",
            dry_run=True,
        )

        assert outcome.dry_run is True
        assert outcome.outcome_label == OutcomeLabel.WIN

        # Labeler can label dry_run outcomes the same way
        labeler = OutcomeLabeler()
        label, confidence = labeler.label(outcome)
        assert label == OutcomeLabel.WIN
        assert confidence > 0.0

        # Memory updater works on dry_run outcomes
        updater.update_from_outcome(outcome)
        db_session.commit()

        # Verify entity memory was created
        entity_mem = db_session.query(EntityMemory).filter(
            EntityMemory.org_id == db_session._test_org_id,
            EntityMemory.entity_id == "adset_dry_run",
        ).first()
        assert entity_mem is not None
        assert entity_mem.trust_score == pytest.approx(55.0)  # 50 + 5 (WIN)
        assert entity_mem.last_outcome_label == OutcomeLabel.WIN

        # Verify feature memory was created
        feat = db_session.query(FeatureMemory).filter(
            FeatureMemory.org_id == db_session._test_org_id,
            FeatureMemory.feature_type == FeatureType.ACTION_TYPE,
            FeatureMemory.feature_key == ActionType.BUDGET_CHANGE.value,
        ).first()
        assert feat is not None
        assert feat.samples == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
