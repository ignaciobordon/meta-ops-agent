"""
Tests for CI module — Engine Core with DB integration.

Uses SQLite in-memory for fast isolated tests.
"""
import pytest
from datetime import datetime
from uuid import uuid4, UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.src.database.models import Base, Organization
from backend.src.ci.models import (
    CICanonicalItem,
    CICompetitor,
    CICompetitorDomain,
    CICompetitorStatus,
    CIDomainType,
    CIIngestRun,
    CIIngestStatus,
    CIItemType,
    CISource,
    CISourceType,
)
from backend.src.ci.engine import CompetitiveIntelligenceEngine


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database session for testing."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Create a test organization
    org = Organization(
        id=uuid4(),
        name="Test Org",
        slug="test-org",
    )
    session.add(org)
    session.commit()
    session.org_id = org.id  # Stash for test access

    yield session
    session.close()


@pytest.fixture
def engine(db_session):
    """Create a CI engine instance."""
    return CompetitiveIntelligenceEngine(db_session)


@pytest.fixture
def org_id(db_session):
    return db_session.org_id


class TestRegisterCompetitor:
    def test_register_basic(self, engine, org_id):
        comp = engine.register_competitor(org_id, name="Acme Corp")
        assert comp.name == "Acme Corp"
        assert comp.org_id == org_id
        assert comp.status == CICompetitorStatus.ACTIVE

    def test_register_with_domains(self, engine, org_id):
        comp = engine.register_competitor(
            org_id,
            name="Widget Co",
            website_url="https://widget.co",
            domains=[
                {"domain": "widget.co", "domain_type": "website"},
                {"domain": "widget-ads", "domain_type": "ad_library"},
            ],
        )
        assert len(comp.domains) == 2
        assert comp.domains[0].domain == "widget.co"

    def test_register_with_metadata(self, engine, org_id):
        comp = engine.register_competitor(
            org_id,
            name="MetaCo",
            meta_json={"industry": "ecommerce", "size": "enterprise"},
        )
        assert comp.meta_json["industry"] == "ecommerce"


class TestListCompetitors:
    def test_list_empty(self, engine, org_id):
        result = engine.list_competitors(org_id)
        assert result == []

    def test_list_all(self, engine, org_id):
        engine.register_competitor(org_id, name="A")
        engine.register_competitor(org_id, name="B")
        result = engine.list_competitors(org_id)
        assert len(result) == 2

    def test_list_with_status_filter(self, engine, org_id):
        engine.register_competitor(org_id, name="Active One")
        comp2 = engine.register_competitor(org_id, name="Paused One")
        engine.update_competitor(org_id, comp2.id, {"status": "paused"})

        active = engine.list_competitors(org_id, status="active")
        assert len(active) == 1
        assert active[0].name == "Active One"

    def test_list_pagination(self, engine, org_id):
        for i in range(5):
            engine.register_competitor(org_id, name=f"Comp {i}")

        page1 = engine.list_competitors(org_id, limit=2, offset=0)
        page2 = engine.list_competitors(org_id, limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2

    def test_list_org_isolation(self, engine, db_session, org_id):
        """Competitors from different orgs should not be visible."""
        engine.register_competitor(org_id, name="My Comp")

        other_org = Organization(id=uuid4(), name="Other", slug="other-org")
        db_session.add(other_org)
        db_session.commit()

        engine.register_competitor(other_org.id, name="Their Comp")

        mine = engine.list_competitors(org_id)
        assert len(mine) == 1
        assert mine[0].name == "My Comp"


class TestUpdateCompetitor:
    def test_update_name(self, engine, org_id):
        comp = engine.register_competitor(org_id, name="Old Name")
        updated = engine.update_competitor(org_id, comp.id, {"name": "New Name"})
        assert updated.name == "New Name"

    def test_update_status(self, engine, org_id):
        comp = engine.register_competitor(org_id, name="To Pause")
        updated = engine.update_competitor(org_id, comp.id, {"status": "paused"})
        assert updated.status == CICompetitorStatus.PAUSED

    def test_update_nonexistent(self, engine, org_id):
        result = engine.update_competitor(org_id, uuid4(), {"name": "X"})
        assert result is None

    def test_update_ignores_invalid_fields(self, engine, org_id):
        comp = engine.register_competitor(org_id, name="Safe")
        updated = engine.update_competitor(org_id, comp.id, {"id": uuid4(), "org_id": uuid4()})
        assert updated.name == "Safe"


class TestDeleteCompetitor:
    def test_delete_existing(self, engine, org_id):
        comp = engine.register_competitor(org_id, name="To Delete")
        assert engine.delete_competitor(org_id, comp.id) is True

        result = engine.get_competitor(org_id, comp.id)
        assert result is None

    def test_delete_nonexistent(self, engine, org_id):
        assert engine.delete_competitor(org_id, uuid4()) is False


class TestSources:
    def test_create_source(self, engine, org_id):
        source = engine.create_source(org_id, "Meta Library", "meta_ad_library")
        assert source.name == "Meta Library"
        assert source.source_type == CISourceType.META_AD_LIBRARY

    def test_list_sources(self, engine, org_id):
        engine.create_source(org_id, "S1", "manual")
        engine.create_source(org_id, "S2", "scraper")
        sources = engine.list_sources(org_id)
        assert len(sources) == 2


class TestIngestRuns:
    def test_start_and_finish(self, engine, org_id):
        source = engine.create_source(org_id, "Test Source", "manual")
        run = engine.start_ingest_run(org_id, source.id)
        assert run.status == CIIngestStatus.RUNNING

        finished = engine.finish_ingest_run(
            run,
            status="succeeded",
            items_fetched=10,
            items_upserted=8,
            items_skipped=2,
        )
        assert finished.status == CIIngestStatus.SUCCEEDED
        assert finished.items_fetched == 10
        assert finished.items_upserted == 8
        assert finished.duration_ms is not None


class TestUpsertCanonicalItem:
    def test_insert_new(self, engine, org_id):
        comp = engine.register_competitor(org_id, name="Target")
        item = engine.upsert_canonical_item(
            org_id=org_id,
            competitor_id=comp.id,
            item_type="ad",
            external_id="ad_001",
            title="Amazing Ad",
            body_text="Buy our stuff",
        )
        assert item.title == "Amazing Ad"
        assert item.item_type == CIItemType.AD

    def test_upsert_updates_existing(self, engine, org_id):
        comp = engine.register_competitor(org_id, name="Target2")
        item1 = engine.upsert_canonical_item(
            org_id=org_id,
            competitor_id=comp.id,
            item_type="ad",
            external_id="ad_002",
            title="V1 Title",
        )
        item2 = engine.upsert_canonical_item(
            org_id=org_id,
            competitor_id=comp.id,
            item_type="ad",
            external_id="ad_002",
            title="V2 Title",
        )
        assert item2.id == item1.id
        assert item2.title == "V2 Title"

    def test_list_items(self, engine, org_id):
        comp = engine.register_competitor(org_id, name="Target3")
        engine.upsert_canonical_item(org_id, comp.id, "ad", "a1", title="Ad 1")
        engine.upsert_canonical_item(org_id, comp.id, "post", "p1", title="Post 1")

        all_items = engine.list_canonical_items(org_id)
        assert len(all_items) == 2

        ads_only = engine.list_canonical_items(org_id, item_type="ad")
        assert len(ads_only) == 1

    def test_get_item(self, engine, org_id):
        comp = engine.register_competitor(org_id, name="Target4")
        item = engine.upsert_canonical_item(org_id, comp.id, "offer", "o1", title="Deal")
        fetched = engine.get_canonical_item(org_id, item.id)
        assert fetched is not None
        assert fetched.title == "Deal"

    def test_get_nonexistent(self, engine, org_id):
        result = engine.get_canonical_item(org_id, uuid4())
        assert result is None
