"""
Enhanced DOCX Report Content Tests.
Tests that ReportBuilder.build_docx produces documents with the expected sections:
Executive Summary, Metrics Comparison, Recommendations, Data Sources.
4 tests verifying section headings/text exist in the generated DOCX.
"""
import os

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

import pytest
from uuid import UUID, uuid4

from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PG_UUID BEFORE any model imports so SQLite can handle UUID columns.
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

from docx import Document

from backend.src.database.models import (
    Base,
    Organization,
    MetaConnection,
    AdAccount,
    DecisionPack,
    ConnectionStatus,
    ActionType,
)
from backend.src.services.report_service import ReportBuilder


# ── Constants ────────────────────────────────────────────────────────────────

ORG_ID = UUID("00000000-0000-0000-0000-000000000001")


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


# ── Helper ───────────────────────────────────────────────────────────────────


def _seed_decision_with_snapshots(db_session):
    """Create Organization -> MetaConnection -> AdAccount -> DecisionPack
    with before_snapshot and after_proposal populated.
    Returns (decision_id, ad_account_id)."""
    org = Organization(id=ORG_ID, name="Test Org", slug="test-org-report")
    db_session.add(org)
    db_session.flush()

    conn_id = uuid4()
    conn = MetaConnection(
        id=conn_id,
        org_id=ORG_ID,
        meta_user_id="meta-user-123",
        access_token_encrypted="encrypted-token",
        status=ConnectionStatus.ACTIVE,
    )
    db_session.add(conn)
    db_session.flush()

    account_id = uuid4()
    account = AdAccount(
        id=account_id,
        connection_id=conn_id,
        meta_ad_account_id=f"act_{uuid4().hex[:8]}",
        name="Test Ad Account",
        currency="USD",
    )
    db_session.add(account)
    db_session.flush()

    decision_id = uuid4()
    decision = DecisionPack(
        id=decision_id,
        ad_account_id=account_id,
        trace_id=f"trace-{uuid4().hex[:12]}",
        action_type=ActionType.BUDGET_CHANGE,
        entity_type="campaign",
        entity_id="campaign_123",
        entity_name="Test Campaign",
        before_snapshot={
            "daily_budget": 50.0,
            "cpa": 12.5,
            "impressions": 1000,
        },
        after_proposal={
            "daily_budget": 75.0,
            "cpa": 10.0,
            "impressions": 1500,
        },
        action_request={"action": "budget_change", "entity_id": "campaign_123"},
        rationale="Budget increase recommended due to strong ROAS.",
        source="SaturationEngine",
        risk_score=0.25,
    )
    db_session.add(decision)
    db_session.commit()

    return decision_id, account_id


def _build_docx_text(db_session, decision_id, ad_account_id):
    """Build DOCX via ReportBuilder and return the full text content."""
    builder = ReportBuilder(db_session)
    buf = builder.build_docx(decision_id, [ad_account_id])
    assert buf is not None, "build_docx returned None; decision not found"
    doc = Document(buf)
    full_text = "\n".join([p.text for p in doc.paragraphs])
    return full_text


# ── 1. test_docx_has_executive_summary ────────────────────────────────────────


class TestDocxHasExecutiveSummary:

    def test_docx_has_executive_summary(self, db_session):
        """DOCX document contains an 'Executive Summary' section."""
        decision_id, account_id = _seed_decision_with_snapshots(db_session)
        full_text = _build_docx_text(db_session, decision_id, account_id)
        assert "Executive Summary" in full_text, (
            "DOCX should contain 'Executive Summary' heading"
        )


# ── 2. test_docx_has_metrics_comparison ───────────────────────────────────────


class TestDocxHasMetricsComparison:

    def test_docx_has_metrics_comparison(self, db_session):
        """When before_snapshot and after_proposal exist, DOCX contains
        'Metrics Comparison' section."""
        decision_id, account_id = _seed_decision_with_snapshots(db_session)
        full_text = _build_docx_text(db_session, decision_id, account_id)
        assert "Metrics Comparison" in full_text, (
            "DOCX should contain 'Metrics Comparison' heading when "
            "both before_snapshot and after_proposal are present"
        )


# ── 3. test_docx_has_recommendations ─────────────────────────────────────────


class TestDocxHasRecommendations:

    def test_docx_has_recommendations(self, db_session):
        """DOCX document contains a 'Recommendations' section."""
        decision_id, account_id = _seed_decision_with_snapshots(db_session)
        full_text = _build_docx_text(db_session, decision_id, account_id)
        assert "Recommendations" in full_text, (
            "DOCX should contain 'Recommendations' heading"
        )


# ── 4. test_docx_has_data_sources ─────────────────────────────────────────────


class TestDocxHasDataSources:

    def test_docx_has_data_sources(self, db_session):
        """DOCX document contains a 'Data Sources' section."""
        decision_id, account_id = _seed_decision_with_snapshots(db_session)
        full_text = _build_docx_text(db_session, decision_id, account_id)
        assert "Data Sources" in full_text, (
            "DOCX should contain 'Data Sources' heading"
        )
