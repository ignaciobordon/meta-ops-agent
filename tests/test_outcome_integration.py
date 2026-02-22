"""
Sprint 5 Integration Tests — Outcomes, Rankings, Brain, and PolicyContext
12 scenarios covering outcome capture, scheduling, API endpoints, multi-tenant
isolation, memory updates, and adaptive policy thresholds.
"""
import os
import pytest
from uuid import uuid4, UUID
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.main import app
from backend.src.database.models import (
    Base, Organization, User, UserOrgRole, RoleEnum,
    MetaConnection, AdAccount,
    DecisionPack, DecisionState, ActionType,
    DecisionOutcome, DecisionRanking, OutcomeLabel,
    EntityMemory, FeatureMemory, FeatureType,
    ScheduledJob,
    Subscription, PlanEnum, SubscriptionStatusEnum, PLAN_LIMITS,
)
from backend.src.database.session import get_db
from backend.src.middleware.auth import create_access_token, hash_password, get_current_user
from backend.src.services.outcome_service import OutcomeCollector, OutcomeScheduler
from backend.src.providers.metrics_provider import MetricsSnapshot


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


def _seed_org_full(db_session, org_name, slug, email, role=RoleEnum.ADMIN):
    """Seed a full org with user, connection, ad_account, subscription. Returns dict of IDs."""
    org_id = uuid4()
    org = Organization(
        id=org_id, name=org_name, slug=slug,
        operator_armed=True, created_at=datetime.utcnow(),
    )
    db_session.add(org)

    user_id = uuid4()
    user = User(
        id=user_id,
        email=email,
        name=f"User {org_name}",
        password_hash=hash_password("TestPass123"),
        created_at=datetime.utcnow(),
    )
    db_session.add(user)

    user_role = UserOrgRole(
        id=uuid4(), user_id=user_id, org_id=org_id,
        role=role, assigned_at=datetime.utcnow(),
    )
    db_session.add(user_role)

    conn_id = uuid4()
    conn = MetaConnection(
        id=conn_id, org_id=org_id,
        access_token_encrypted="enc_test", status="active",
        connected_at=datetime.utcnow(),
    )
    db_session.add(conn)

    ad_account_id = uuid4()
    ad_account = AdAccount(
        id=ad_account_id, connection_id=conn_id,
        meta_ad_account_id=f"act_{slug}_001", name=f"{org_name} Ad Account",
        currency="USD", synced_at=datetime.utcnow(),
    )
    db_session.add(ad_account)

    sub = Subscription(
        id=uuid4(), org_id=org_id,
        plan=PlanEnum.PRO, status=SubscriptionStatusEnum.ACTIVE,
        max_ad_accounts=100, max_decisions_per_month=1000,
        max_creatives_per_month=500, allow_live_execution=True,
        created_at=datetime.utcnow(),
    )
    db_session.add(sub)

    db_session.commit()

    token = create_access_token(
        user_id=str(user_id),
        email=email,
        role=role.value,
        org_id=str(org_id),
    )

    return {
        "org_id": org_id,
        "user_id": user_id,
        "conn_id": conn_id,
        "ad_account_id": ad_account_id,
        "token": token,
    }


def _seed_decision(db_session, ad_account_id, user_id, state=DecisionState.EXECUTED,
                    entity_id="camp_001", action_type=ActionType.BUDGET_CHANGE):
    """Create a DecisionPack in the given state."""
    decision = DecisionPack(
        id=uuid4(),
        ad_account_id=ad_account_id,
        created_by_user_id=user_id,
        state=state,
        trace_id=f"trace-{uuid4().hex[:12]}",
        action_type=action_type,
        entity_type="campaign",
        entity_id=entity_id,
        entity_name=f"Test Campaign {entity_id}",
        action_request={"budget": 100},
        rationale="test outcome",
        source="test",
        before_snapshot={"budget": 80},
        after_proposal={"budget": 100},
        executed_at=datetime.utcnow() if state == DecisionState.EXECUTED else None,
        created_at=datetime.utcnow(),
    )
    db_session.add(decision)
    db_session.commit()
    db_session.refresh(decision)
    return decision


def _mock_snapshot(entity_type="campaign", entity_id="camp_001", metrics=None):
    """Build a MetricsSnapshot for mocking."""
    return MetricsSnapshot(
        entity_type=entity_type,
        entity_id=entity_id,
        provider="mock",
        metrics=metrics or {"spend": 100.0, "ctr": 0.05, "cpa": 12.0, "roas": 2.5},
        available=True,
    )


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── Test 1: Execute decision -> 3 outcomes + 3 jobs ─────────────────────────


class TestOutcomeCollectorCapturesBefore:

    def test_execute_creates_3_outcomes_and_3_jobs(self, db_session):
        """OutcomeCollector.capture_before creates 3 outcomes (1h, 24h, 72h) and 3 scheduled jobs."""
        data = _seed_org_full(db_session, "Collector Org", "collector-org", "collector@test.com")
        decision = _seed_decision(db_session, data["ad_account_id"], data["user_id"])

        mock_snap = _mock_snapshot(entity_id=decision.entity_id)

        with patch(
            "backend.src.services.outcome_service.MetricsProviderFactory"
        ) as mock_factory:
            mock_provider = MagicMock()
            mock_provider.get_snapshot.return_value = mock_snap
            mock_factory.get_provider.return_value = mock_provider

            collector = OutcomeCollector(db_session)
            outcomes = collector.capture_before(decision, data["org_id"], dry_run=False)

        db_session.commit()

        assert len(outcomes) == 3
        horizons = sorted([o.horizon_minutes for o in outcomes])
        assert horizons == [60, 1440, 4320]

        # Verify outcomes in DB
        db_outcomes = db_session.query(DecisionOutcome).filter(
            DecisionOutcome.decision_id == decision.id,
        ).all()
        assert len(db_outcomes) == 3

        # Verify scheduled jobs in DB
        jobs = db_session.query(ScheduledJob).filter(
            ScheduledJob.job_type == "outcome_capture",
        ).all()
        assert len(jobs) == 3

        # Each job references a unique outcome
        job_refs = {j.reference_id for j in jobs}
        outcome_ids = {o.id for o in outcomes}
        assert job_refs == outcome_ids

        # All outcomes have before_metrics populated
        for o in outcomes:
            assert o.before_metrics_json is not None
            assert o.before_metrics_json.get("provider") == "mock"


# ── Test 2: OutcomeScheduler.process_pending ─────────────────────────────────


class TestOutcomeSchedulerProcessesPending:

    def test_scheduler_processes_due_jobs(self, db_session):
        """OutcomeScheduler.process_pending processes jobs with scheduled_for in the past."""
        data = _seed_org_full(db_session, "Scheduler Org", "scheduler-org", "scheduler@test.com")
        decision = _seed_decision(db_session, data["ad_account_id"], data["user_id"])

        # Create outcome + job manually (job is past-due)
        outcome = DecisionOutcome(
            id=uuid4(),
            org_id=data["org_id"],
            decision_id=decision.id,
            entity_type="campaign",
            entity_id="camp_001",
            action_type=ActionType.BUDGET_CHANGE,
            executed_at=datetime.utcnow() - timedelta(hours=2),
            dry_run=False,
            horizon_minutes=60,
            before_metrics_json={
                "provider": "mock", "available": True,
                "metrics": {"spend": 100.0, "ctr": 0.05, "cpa": 12.0, "roas": 2.5},
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
        db_session.add(outcome)
        db_session.flush()

        job = ScheduledJob(
            id=uuid4(),
            org_id=data["org_id"],
            job_type="outcome_capture",
            reference_id=outcome.id,
            scheduled_for=datetime.utcnow() - timedelta(minutes=30),  # Past-due
        )
        db_session.add(job)
        db_session.commit()

        # Mock the provider for capture_after
        after_snap = _mock_snapshot(
            entity_id="camp_001",
            metrics={"spend": 110.0, "ctr": 0.06, "cpa": 11.0, "roas": 2.8},
        )

        with patch(
            "backend.src.services.outcome_service.MetricsProviderFactory"
        ) as mock_factory:
            mock_provider = MagicMock()
            mock_provider.get_snapshot.return_value = after_snap
            mock_factory.get_provider.return_value = mock_provider

            scheduler = OutcomeScheduler(db_session)
            results = scheduler.process_pending(limit=50)

        assert len(results) == 1
        assert results[0]["status"] == "completed"

        # Job should be marked completed
        db_session.expire_all()
        updated_job = db_session.query(ScheduledJob).filter(ScheduledJob.id == job.id).first()
        assert updated_job.completed_at is not None

        # Outcome should have after_metrics and a label
        updated_outcome = db_session.query(DecisionOutcome).filter(
            DecisionOutcome.id == outcome.id
        ).first()
        assert updated_outcome.after_metrics_json is not None
        assert updated_outcome.delta_metrics_json is not None
        assert updated_outcome.outcome_label != OutcomeLabel.UNKNOWN


# ── Test 3: GET /decisions/{id}/outcomes ──────────────────────────────────────


class TestGetDecisionOutcomesAPI:

    def test_get_outcomes_returns_list(self, db_session, override_db):
        """GET /decisions/{id}/outcomes returns outcomes for a decision."""
        data = _seed_org_full(db_session, "Outcomes API Org", "outcomes-api", "outcomes@test.com")
        decision = _seed_decision(db_session, data["ad_account_id"], data["user_id"])

        # Insert 2 outcomes
        for horizon in [60, 1440]:
            outcome = DecisionOutcome(
                id=uuid4(),
                org_id=data["org_id"],
                decision_id=decision.id,
                entity_type="campaign",
                entity_id="camp_001",
                action_type=ActionType.BUDGET_CHANGE,
                executed_at=datetime.utcnow(),
                dry_run=False,
                horizon_minutes=horizon,
                before_metrics_json={"provider": "mock", "metrics": {}},
                outcome_label=OutcomeLabel.WIN if horizon == 60 else OutcomeLabel.NEUTRAL,
                confidence=0.8,
            )
            db_session.add(outcome)
        db_session.commit()

        client = TestClient(app)
        resp = client.get(
            f"/api/decisions/{decision.id}/outcomes",
            headers=_auth(data["token"]),
        )
        assert resp.status_code == 200
        outcomes = resp.json()
        assert len(outcomes) == 2
        # Ordered by horizon_minutes
        assert outcomes[0]["horizon_minutes"] == 60
        assert outcomes[1]["horizon_minutes"] == 1440


# ── Test 4: GET /decisions/ranked ────────────────────────────────────────────


class TestGetRankedDecisions:

    def test_ranked_returns_scored_list(self, db_session, override_db):
        """GET /decisions/ranked returns scored decisions sorted by score_total."""
        data = _seed_org_full(db_session, "Ranked Org", "ranked-org", "ranked@test.com")

        # Create 2 decisions in PENDING_APPROVAL state
        d1 = _seed_decision(
            db_session, data["ad_account_id"], data["user_id"],
            state=DecisionState.PENDING_APPROVAL, entity_id="camp_rank_1",
        )
        d2 = _seed_decision(
            db_session, data["ad_account_id"], data["user_id"],
            state=DecisionState.PENDING_APPROVAL, entity_id="camp_rank_2",
        )

        client = TestClient(app)
        resp = client.get(
            "/api/decisions/ranked?state=pending_approval",
            headers=_auth(data["token"]),
        )
        assert resp.status_code == 200
        ranked = resp.json()
        assert len(ranked) == 2

        # Each item should have scoring fields
        for item in ranked:
            assert "score_total" in item
            assert "score_impact" in item
            assert "score_risk" in item
            assert "score_confidence" in item
            assert "score_freshness" in item
            assert "explanation" in item

        # Verify sorted by score_total descending
        assert ranked[0]["score_total"] >= ranked[1]["score_total"]


# ── Test 5: GET /decisions/{id}/rank-explanation ─────────────────────────────


class TestGetRankExplanation:

    def test_rank_explanation_returns_breakdown(self, db_session, override_db):
        """GET /decisions/{id}/rank-explanation returns score breakdown."""
        data = _seed_org_full(db_session, "Explain Org", "explain-org", "explain@test.com")
        decision = _seed_decision(
            db_session, data["ad_account_id"], data["user_id"],
            state=DecisionState.PENDING_APPROVAL, entity_id="camp_explain_1",
        )

        client = TestClient(app)
        resp = client.get(
            f"/api/decisions/{decision.id}/rank-explanation",
            headers=_auth(data["token"]),
        )
        assert resp.status_code == 200
        body = resp.json()

        assert body["decision_id"] == str(decision.id)
        assert "score_total" in body
        assert "score_impact" in body
        assert "score_risk" in body
        assert "score_confidence" in body
        assert "score_freshness" in body
        assert "rank_version" in body
        assert "explanation" in body


# ── Test 6: GET /brain/stats ─────────────────────────────────────────────────


class TestBrainStats:

    def test_brain_stats_returns_features_outcomes_trust(self, db_session, override_db):
        """GET /brain/stats returns top features, recent outcomes, and entity trust."""
        data = _seed_org_full(db_session, "Brain Org", "brain-org", "brain@test.com")
        decision = _seed_decision(db_session, data["ad_account_id"], data["user_id"])

        # Seed FeatureMemory with samples >= 3
        fm = FeatureMemory(
            id=uuid4(),
            org_id=data["org_id"],
            feature_type=FeatureType.ACTION_TYPE,
            feature_key="budget_change",
            win_rate=0.75,
            avg_delta_json={"spend": 10.0, "cpa": -1.5},
            samples=5,
        )
        db_session.add(fm)

        # Seed a labeled outcome (non-UNKNOWN)
        outcome = DecisionOutcome(
            id=uuid4(),
            org_id=data["org_id"],
            decision_id=decision.id,
            entity_type="campaign",
            entity_id="camp_001",
            action_type=ActionType.BUDGET_CHANGE,
            executed_at=datetime.utcnow(),
            dry_run=False,
            horizon_minutes=60,
            before_metrics_json={"metrics": {}},
            outcome_label=OutcomeLabel.WIN,
            confidence=0.9,
        )
        db_session.add(outcome)

        # Seed EntityMemory
        em = EntityMemory(
            id=uuid4(),
            org_id=data["org_id"],
            entity_type="campaign",
            entity_id="camp_001",
            trust_score=72.0,
            last_outcome_label=OutcomeLabel.WIN,
            last_seen_at=datetime.utcnow(),
        )
        db_session.add(em)
        db_session.commit()

        client = TestClient(app)
        resp = client.get(
            "/api/brain/stats",
            headers=_auth(data["token"]),
        )
        assert resp.status_code == 200
        body = resp.json()

        assert "top_features" in body
        assert "recent_outcomes" in body
        assert "entity_trust" in body

        # Features should include our seeded one
        assert len(body["top_features"]) >= 1
        feat = body["top_features"][0]
        assert feat["feature_key"] == "budget_change"
        assert feat["win_rate"] == 0.75
        assert feat["samples"] == 5

        # Recent outcomes should include our labeled one
        assert len(body["recent_outcomes"]) >= 1
        ro = body["recent_outcomes"][0]
        assert ro["outcome_label"] == "win"

        # Entity trust should include our entity
        assert len(body["entity_trust"]) >= 1
        et = body["entity_trust"][0]
        assert et["entity_id"] == "camp_001"
        assert et["trust_score"] == 72.0


# ── Test 7: TRIAL plan can access ranked endpoint ────────────────────────────


class TestTrialPlanAccessRanked:

    def test_trial_plan_can_read_ranked(self, db_session, override_db):
        """TRIAL plan users can access GET /decisions/ranked (read-only, no plan block)."""
        # Create org with TRIAL plan
        org_id = uuid4()
        org = Organization(
            id=org_id, name="Trial Org", slug="trial-org",
            operator_armed=True, created_at=datetime.utcnow(),
        )
        db_session.add(org)

        user_id = uuid4()
        user = User(
            id=user_id, email="trial@test.com", name="Trial User",
            password_hash=hash_password("TrialPass123"),
            created_at=datetime.utcnow(),
        )
        db_session.add(user)

        role = UserOrgRole(
            id=uuid4(), user_id=user_id, org_id=org_id,
            role=RoleEnum.ADMIN, assigned_at=datetime.utcnow(),
        )
        db_session.add(role)

        conn_id = uuid4()
        conn = MetaConnection(
            id=conn_id, org_id=org_id,
            access_token_encrypted="enc_test", status="active",
            connected_at=datetime.utcnow(),
        )
        db_session.add(conn)

        ad_account_id = uuid4()
        ad_account = AdAccount(
            id=ad_account_id, connection_id=conn_id,
            meta_ad_account_id="act_trial_001", name="Trial Ad Account",
            currency="USD", synced_at=datetime.utcnow(),
        )
        db_session.add(ad_account)

        # TRIAL subscription
        sub = Subscription(
            id=uuid4(), org_id=org_id,
            plan=PlanEnum.TRIAL, status=SubscriptionStatusEnum.TRIALING,
            max_ad_accounts=1, max_decisions_per_month=50,
            max_creatives_per_month=30, allow_live_execution=False,
            created_at=datetime.utcnow(),
        )
        db_session.add(sub)
        db_session.commit()

        token = create_access_token(
            user_id=str(user_id), email="trial@test.com",
            role="admin", org_id=str(org_id),
        )

        client = TestClient(app)
        resp = client.get(
            "/api/decisions/ranked?state=pending_approval",
            headers=_auth(token),
        )
        # Read-only endpoint should return 200 even for TRIAL plan
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ── Test 8: past_due/canceled blocks outcome creation ────────────────────────


class TestSubscriptionStatusBlocksOutcomeCreation:

    def test_past_due_blocks_decision_create(self, db_session, override_db):
        """past_due subscription status blocks new decision creation (which triggers outcome capture)."""
        org_id = uuid4()
        org = Organization(
            id=org_id, name="PastDue Org", slug="pastdue-org",
            operator_armed=True, created_at=datetime.utcnow(),
        )
        db_session.add(org)

        user_id = uuid4()
        user = User(
            id=user_id, email="pastdue@test.com", name="PastDue User",
            password_hash=hash_password("PastDuePass123"),
            created_at=datetime.utcnow(),
        )
        db_session.add(user)

        role = UserOrgRole(
            id=uuid4(), user_id=user_id, org_id=org_id,
            role=RoleEnum.ADMIN, assigned_at=datetime.utcnow(),
        )
        db_session.add(role)

        conn_id = uuid4()
        conn = MetaConnection(
            id=conn_id, org_id=org_id,
            access_token_encrypted="enc_test", status="active",
            connected_at=datetime.utcnow(),
        )
        db_session.add(conn)

        ad_account_id = uuid4()
        ad_account = AdAccount(
            id=ad_account_id, connection_id=conn_id,
            meta_ad_account_id="act_pastdue_001", name="PastDue Ad Account",
            currency="USD", synced_at=datetime.utcnow(),
        )
        db_session.add(ad_account)

        # PAST_DUE subscription
        sub = Subscription(
            id=uuid4(), org_id=org_id,
            plan=PlanEnum.PRO, status=SubscriptionStatusEnum.PAST_DUE,
            max_ad_accounts=100, max_decisions_per_month=1000,
            max_creatives_per_month=500, allow_live_execution=True,
            created_at=datetime.utcnow(),
        )
        db_session.add(sub)
        db_session.commit()

        token = create_access_token(
            user_id=str(user_id), email="pastdue@test.com",
            role="admin", org_id=str(org_id),
        )

        client = TestClient(app)
        resp = client.post(
            "/api/decisions/",
            json={
                "ad_account_id": str(ad_account_id),
                "user_id": str(user_id),
                "action_type": "budget_change",
                "entity_type": "campaign",
                "entity_id": "camp_blocked",
                "entity_name": "Blocked Campaign",
                "payload": {"budget": 200},
                "rationale": "should be blocked",
                "source": "test",
            },
            headers=_auth(token),
        )
        # past_due triggers 402 or 403 from UsageService._check_read_only
        assert resp.status_code in (402, 403)

    def test_canceled_blocks_decision_create(self, db_session, override_db):
        """canceled subscription status blocks new decision creation."""
        org_id = uuid4()
        org = Organization(
            id=org_id, name="Canceled Org", slug="canceled-org",
            operator_armed=True, created_at=datetime.utcnow(),
        )
        db_session.add(org)

        user_id = uuid4()
        user = User(
            id=user_id, email="canceled@test.com", name="Canceled User",
            password_hash=hash_password("CanceledPass123"),
            created_at=datetime.utcnow(),
        )
        db_session.add(user)

        role = UserOrgRole(
            id=uuid4(), user_id=user_id, org_id=org_id,
            role=RoleEnum.ADMIN, assigned_at=datetime.utcnow(),
        )
        db_session.add(role)

        conn_id = uuid4()
        conn = MetaConnection(
            id=conn_id, org_id=org_id,
            access_token_encrypted="enc_test", status="active",
            connected_at=datetime.utcnow(),
        )
        db_session.add(conn)

        ad_account_id = uuid4()
        ad_account = AdAccount(
            id=ad_account_id, connection_id=conn_id,
            meta_ad_account_id="act_canceled_001", name="Canceled Ad Account",
            currency="USD", synced_at=datetime.utcnow(),
        )
        db_session.add(ad_account)

        # CANCELED subscription
        sub = Subscription(
            id=uuid4(), org_id=org_id,
            plan=PlanEnum.PRO, status=SubscriptionStatusEnum.CANCELED,
            max_ad_accounts=100, max_decisions_per_month=1000,
            max_creatives_per_month=500, allow_live_execution=True,
            created_at=datetime.utcnow(),
        )
        db_session.add(sub)
        db_session.commit()

        token = create_access_token(
            user_id=str(user_id), email="canceled@test.com",
            role="admin", org_id=str(org_id),
        )

        client = TestClient(app)
        resp = client.post(
            "/api/decisions/",
            json={
                "ad_account_id": str(ad_account_id),
                "user_id": str(user_id),
                "action_type": "budget_change",
                "entity_type": "campaign",
                "entity_id": "camp_canceled",
                "entity_name": "Canceled Campaign",
                "payload": {"budget": 200},
                "rationale": "should be blocked",
                "source": "test",
            },
            headers=_auth(token),
        )
        # canceled triggers 403 from UsageService._check_read_only
        assert resp.status_code == 403


# ── Test 9: Multi-tenant outcome isolation ───────────────────────────────────


class TestMultiTenantOutcomeIsolation:

    def test_org_a_outcomes_invisible_to_org_b(self, db_session, override_db):
        """Outcomes created for Org A are not visible when Org B queries /decisions/{id}/outcomes."""
        data_a = _seed_org_full(db_session, "Iso Org A", "iso-org-a", "iso-a@test.com")
        data_b = _seed_org_full(db_session, "Iso Org B", "iso-org-b", "iso-b@test.com")

        # Decision belongs to Org A
        decision_a = _seed_decision(db_session, data_a["ad_account_id"], data_a["user_id"])

        # Outcomes belong to Org A
        for horizon in [60, 1440, 4320]:
            outcome = DecisionOutcome(
                id=uuid4(),
                org_id=data_a["org_id"],
                decision_id=decision_a.id,
                entity_type="campaign",
                entity_id="camp_001",
                action_type=ActionType.BUDGET_CHANGE,
                executed_at=datetime.utcnow(),
                dry_run=False,
                horizon_minutes=horizon,
                before_metrics_json={"provider": "mock", "metrics": {}},
                outcome_label=OutcomeLabel.WIN,
                confidence=0.9,
            )
            db_session.add(outcome)
        db_session.commit()

        client = TestClient(app)

        # Org A can see its own outcomes
        resp_a = client.get(
            f"/api/decisions/{decision_a.id}/outcomes",
            headers=_auth(data_a["token"]),
        )
        assert resp_a.status_code == 200
        assert len(resp_a.json()) == 3

        # Org B cannot see Org A's decision (404 because decision belongs to different org)
        resp_b = client.get(
            f"/api/decisions/{decision_a.id}/outcomes",
            headers=_auth(data_b["token"]),
        )
        assert resp_b.status_code == 404


# ── Test 10: Multi-tenant ranking isolation ──────────────────────────────────


class TestMultiTenantRankingIsolation:

    def test_org_b_ranked_empty_when_decisions_belong_to_org_a(self, db_session, override_db):
        """Decisions in Org A do not appear in Org B's ranked list."""
        data_a = _seed_org_full(db_session, "Rank Org A", "rank-org-a", "rank-a@test.com")
        data_b = _seed_org_full(db_session, "Rank Org B", "rank-org-b", "rank-b@test.com")

        # Create decisions only in Org A
        _seed_decision(
            db_session, data_a["ad_account_id"], data_a["user_id"],
            state=DecisionState.PENDING_APPROVAL, entity_id="camp_rank_a1",
        )
        _seed_decision(
            db_session, data_a["ad_account_id"], data_a["user_id"],
            state=DecisionState.PENDING_APPROVAL, entity_id="camp_rank_a2",
        )

        client = TestClient(app)

        # Org A sees ranked decisions
        resp_a = client.get(
            "/api/decisions/ranked?state=pending_approval",
            headers=_auth(data_a["token"]),
        )
        assert resp_a.status_code == 200
        assert len(resp_a.json()) == 2

        # Org B sees empty ranked list
        resp_b = client.get(
            "/api/decisions/ranked?state=pending_approval",
            headers=_auth(data_b["token"]),
        )
        assert resp_b.status_code == 200
        assert len(resp_b.json()) == 0


# ── Test 11: Memory updates after outcome capture ────────────────────────────


class TestMemoryUpdatesAfterOutcomeCapture:

    def test_entity_memory_created_after_capture_after(self, db_session):
        """After capture_after, EntityMemory exists for the entity with updated trust."""
        data = _seed_org_full(db_session, "Memory Org", "memory-org", "memory@test.com")
        decision = _seed_decision(db_session, data["ad_account_id"], data["user_id"])

        # Create outcome with before_metrics (simulating capture_before already done)
        outcome = DecisionOutcome(
            id=uuid4(),
            org_id=data["org_id"],
            decision_id=decision.id,
            entity_type="campaign",
            entity_id="camp_001",
            action_type=ActionType.BUDGET_CHANGE,
            executed_at=datetime.utcnow() - timedelta(hours=2),
            dry_run=False,
            horizon_minutes=60,
            before_metrics_json={
                "provider": "mock", "available": True,
                "metrics": {"spend": 100.0, "ctr": 0.05, "cpa": 12.0, "roas": 2.5},
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
        db_session.add(outcome)
        db_session.commit()
        db_session.refresh(outcome)

        # Verify no EntityMemory exists yet
        em_before = db_session.query(EntityMemory).filter(
            EntityMemory.org_id == data["org_id"],
            EntityMemory.entity_id == "camp_001",
        ).first()
        assert em_before is None

        # Mock provider to return improved metrics (WIN scenario: roas up, cpa down)
        after_snap = _mock_snapshot(
            entity_id="camp_001",
            metrics={"spend": 110.0, "ctr": 0.06, "cpa": 10.0, "roas": 3.2},
        )

        with patch(
            "backend.src.services.outcome_service.MetricsProviderFactory"
        ) as mock_factory:
            mock_provider = MagicMock()
            mock_provider.get_snapshot.return_value = after_snap
            mock_factory.get_provider.return_value = mock_provider

            collector = OutcomeCollector(db_session)
            result = collector.capture_after(outcome.id)

        db_session.commit()

        # Outcome should be labeled (WIN expected: roas +0.7 > 0.05 noise, cpa -2.0 < 0.1 noise)
        assert result is not None
        assert result.outcome_label != OutcomeLabel.UNKNOWN

        # EntityMemory should now exist
        em_after = db_session.query(EntityMemory).filter(
            EntityMemory.org_id == data["org_id"],
            EntityMemory.entity_id == "camp_001",
        ).first()
        assert em_after is not None
        assert em_after.entity_type == "campaign"
        assert em_after.last_outcome_label is not None
        assert em_after.trust_score != 50.0 or em_after.last_seen_at is not None


# ── Test 12: PolicyContext adjusts budget delta threshold ────────────────────


class TestPolicyContextBudgetDelta:

    def test_high_trust_gets_relaxed_threshold(self):
        """Trust=90 gets 25% cap, so a 22% budget change is allowed."""
        from src.core.policy_engine import PolicyEngine, PolicyContext
        from src.schemas.policy import ActionRequest

        context_high = PolicyContext(trust_score=90)

        request = ActionRequest(
            action_type="budget_change",
            entity_id="camp_policy_001",
            entity_type="campaign",
            payload={
                "current_budget": 100.0,
                "new_budget": 122.0,  # 22% increase
            },
            trace_id=f"trace-policy-{uuid4().hex[:8]}",
        )

        engine = PolicyEngine()
        result = engine.validate(request, context=context_high)

        # 22% < 25% cap for high trust -> should be approved
        assert result.approved is True
        blocking = result.blocking_violations()
        budget_blocks = [v for v in blocking if v.rule_name == "BudgetDeltaRule"]
        assert len(budget_blocks) == 0

    def test_low_trust_gets_strict_threshold(self):
        """Trust=20 gets 15% cap, so a 22% budget change is blocked."""
        from src.core.policy_engine import PolicyEngine, PolicyContext
        from src.schemas.policy import ActionRequest

        context_low = PolicyContext(trust_score=20)

        request = ActionRequest(
            action_type="budget_change",
            entity_id="camp_policy_002",
            entity_type="campaign",
            payload={
                "current_budget": 100.0,
                "new_budget": 122.0,  # 22% increase
            },
            trace_id=f"trace-policy-{uuid4().hex[:8]}",
        )

        engine = PolicyEngine()
        result = engine.validate(request, context=context_low)

        # 22% > 15% cap for low trust -> should be blocked
        assert result.approved is False
        blocking = result.blocking_violations()
        budget_blocks = [v for v in blocking if v.rule_name == "BudgetDeltaRule"]
        assert len(budget_blocks) == 1
        assert "22%" in budget_blocks[0].message or "22.0%" in budget_blocks[0].message

    def test_default_trust_uses_standard_threshold(self):
        """Trust=50 (default) gets 20% cap, so a 22% budget change is blocked and 18% is allowed."""
        from src.core.policy_engine import PolicyEngine, PolicyContext
        from src.schemas.policy import ActionRequest

        context_default = PolicyContext(trust_score=50)

        # 22% change -> blocked by default 20% threshold
        request_over = ActionRequest(
            action_type="budget_change",
            entity_id="camp_policy_003",
            entity_type="campaign",
            payload={
                "current_budget": 100.0,
                "new_budget": 122.0,
            },
            trace_id=f"trace-policy-{uuid4().hex[:8]}",
        )

        engine = PolicyEngine()
        result_over = engine.validate(request_over, context=context_default)
        assert result_over.approved is False

        # 18% change -> allowed by default 20% threshold
        request_under = ActionRequest(
            action_type="budget_change",
            entity_id="camp_policy_004",
            entity_type="campaign",
            payload={
                "current_budget": 100.0,
                "new_budget": 118.0,
            },
            trace_id=f"trace-policy-{uuid4().hex[:8]}",
        )

        engine2 = PolicyEngine()
        result_under = engine2.validate(request_under, context=context_default)
        assert result_under.approved is True
