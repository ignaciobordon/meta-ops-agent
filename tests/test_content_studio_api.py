"""
Sprint 13 – Content Studio API endpoint tests.
Tests the full CRUD lifecycle: channels, packs, variants, locks, exports.
"""
import os
import pytest
from uuid import uuid4, UUID as PyUUID
from datetime import datetime
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
    Base,
    Organization,
    MetaConnection,
    AdAccount,
    Creative,
    ContentPack,
    ContentVariant,
    ContentChannelLock,
    ContentExport,
    ContentPackStatus,
    ConnectionStatus,
    JobRun,
    JobRunStatus,
)
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user


# ── Constants ────────────────────────────────────────────────────────────────

ORG_ID = "00000000-0000-0000-0000-000000000001"
CONNECTION_ID = "00000000-0000-0000-0000-000000000002"
AD_ACCOUNT_ID = "00000000-0000-0000-0000-000000000003"
CREATIVE_ID = "00000000-0000-0000-0000-000000000004"
USER_ID = "00000000-0000-0000-0000-000000000099"


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
def override_deps(db_engine):
    """Override get_db and get_current_user for all tests."""
    SessionLocal = sessionmaker(bind=db_engine)

    def _override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def _override_get_current_user():
        return {
            "user_id": USER_ID,
            "org_id": ORG_ID,
            "role": "admin",
        }

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    yield
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def seed_data(db_session, override_deps):
    """Seed Organization, MetaConnection, AdAccount, Creative."""
    org = Organization(
        id=PyUUID(ORG_ID),
        name="Content Studio Test Corp",
        slug="content-studio-test",
        operator_armed=True,
        created_at=datetime.utcnow(),
    )
    db_session.add(org)

    conn = MetaConnection(
        id=PyUUID(CONNECTION_ID),
        org_id=PyUUID(ORG_ID),
        access_token_encrypted="enc_test",
        status=ConnectionStatus.ACTIVE,
        connected_at=datetime.utcnow(),
    )
    db_session.add(conn)

    ad_account = AdAccount(
        id=PyUUID(AD_ACCOUNT_ID),
        connection_id=PyUUID(CONNECTION_ID),
        meta_ad_account_id="act_content_studio_test",
        name="CS Test Account",
        currency="USD",
        synced_at=datetime.utcnow(),
    )
    db_session.add(ad_account)

    creative = Creative(
        id=PyUUID(CREATIVE_ID),
        ad_account_id=PyUUID(AD_ACCOUNT_ID),
        name="Test Creative for CS",
        ad_copy="This is the base creative copy for content studio.",
        headline="Test Headline",
        overall_score=8.0,
        meta_ad_id=f"gen-cs-{uuid4().hex[:16]}",
        tags=[{"l1": "angle", "l2": "test_angle", "confidence": 1.0, "source": "factory"}],
        created_at=datetime.utcnow(),
    )
    db_session.add(creative)
    db_session.commit()

    return {
        "org_id": ORG_ID,
        "connection_id": CONNECTION_ID,
        "ad_account_id": AD_ACCOUNT_ID,
        "creative_id": CREATIVE_ID,
    }


@pytest.fixture
def client(override_deps):
    return TestClient(app)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_pack(db_session, status=ContentPackStatus.QUEUED, creative_id=CREATIVE_ID):
    """Create a ContentPack directly in DB and return it."""
    pack = ContentPack(
        id=uuid4(),
        org_id=PyUUID(ORG_ID),
        creative_id=PyUUID(creative_id) if creative_id else None,
        status=status,
        goal="awareness",
        language="es-AR",
        channels_json=[{"channel": "ig_reel", "format": "9x16_30s"}],
        input_json={"target_audience": "young adults"},
        created_at=datetime.utcnow(),
    )
    db_session.add(pack)
    db_session.flush()
    return pack


def _make_variant(db_session, pack_id, channel="ig_reel", variant_index=1, score=75.0):
    """Create a ContentVariant directly in DB and return it."""
    variant = ContentVariant(
        id=uuid4(),
        content_pack_id=pack_id,
        channel=channel,
        format="9x16_30s",
        variant_index=variant_index,
        output_json={"hook": "Test hook", "script": "Test script", "cta": "Buy now"},
        score=score,
        score_breakdown_json={"hook_strength": 20, "clarity": 12, "cta_fit": 8},
        rationale_text="Strong hook with clear CTA.",
        created_at=datetime.utcnow(),
    )
    db_session.add(variant)
    db_session.flush()
    return variant


# ── 1. test_list_channels_returns_all ────────────────────────────────────────


def test_list_channels_returns_all(client, seed_data):
    """GET /api/content-studio/channels returns all 13 channels."""
    resp = client.get("/api/content-studio/channels")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 13


# ── 2. test_list_channels_shape ──────────────────────────────────────────────


def test_list_channels_shape(client, seed_data):
    """Each channel object has key, display_name, platform, variants_count."""
    resp = client.get("/api/content-studio/channels")
    assert resp.status_code == 200
    data = resp.json()
    for ch in data:
        assert "key" in ch
        assert "display_name" in ch
        assert "platform" in ch
        assert "variants_count" in ch
        assert isinstance(ch["variants_count"], int)
        assert ch["variants_count"] > 0


# ── 3. test_create_pack_returns_202 ──────────────────────────────────────────


def test_create_pack_returns_202(client, seed_data):
    """POST /api/content-studio/packs returns 202 with pack_id and job_id."""
    fake_job_id = str(uuid4())

    with patch(
        "backend.src.jobs.queue.enqueue",
        return_value=fake_job_id,
    ):
        resp = client.post("/api/content-studio/packs", json={
            "creative_id": CREATIVE_ID,
            "channels": [{"channel": "ig_reel", "format": "9x16_30s"}],
            "goal": "awareness",
            "language": "es-AR",
        })

    assert resp.status_code == 202
    body = resp.json()
    assert "pack_id" in body
    assert body["job_id"] == fake_job_id
    assert body["status"] == "queued"


# ── 4. test_create_pack_missing_channels ─────────────────────────────────────


def test_create_pack_missing_channels(client, seed_data):
    """POST /api/content-studio/packs with empty channels returns 400."""
    with patch(
        "backend.src.jobs.queue.enqueue",
        return_value=str(uuid4()),
    ):
        resp = client.post("/api/content-studio/packs", json={
            "creative_id": CREATIVE_ID,
            "channels": [],
            "goal": "awareness",
        })

    assert resp.status_code == 400
    assert "channel" in resp.json()["detail"].lower()


# ── 5. test_create_pack_unknown_channel ──────────────────────────────────────


def test_create_pack_unknown_channel(client, seed_data):
    """POST /api/content-studio/packs with unknown channel returns 400."""
    with patch(
        "backend.src.jobs.queue.enqueue",
        return_value=str(uuid4()),
    ):
        resp = client.post("/api/content-studio/packs", json={
            "creative_id": CREATIVE_ID,
            "channels": [{"channel": "nope", "format": ""}],
            "goal": "awareness",
        })

    assert resp.status_code == 400
    assert "nope" in resp.json()["detail"].lower()


# ── 6. test_create_pack_no_creative ──────────────────────────────────────────


def test_create_pack_no_creative(client, seed_data):
    """POST /api/content-studio/packs without creative_id returns 422 (validation)."""
    resp = client.post("/api/content-studio/packs", json={
        "channels": [{"channel": "ig_reel"}],
        "goal": "awareness",
    })
    assert resp.status_code == 422


# ── 7. test_get_pack_found ───────────────────────────────────────────────────


def test_get_pack_found(client, seed_data, db_session):
    """GET /api/content-studio/packs/{id} returns 200 with correct shape."""
    pack = _make_pack(db_session)
    db_session.commit()

    resp = client.get(f"/api/content-studio/packs/{pack.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(pack.id)
    assert body["status"] == "queued"
    assert "creative_id" in body
    assert "goal" in body
    assert "language" in body
    assert "channels_json" in body
    assert "created_at" in body
    assert "variants_count" in body
    assert body["variants_count"] == 0


# ── 8. test_get_pack_not_found ───────────────────────────────────────────────


def test_get_pack_not_found(client, seed_data):
    """GET /api/content-studio/packs/{unknown} returns 404."""
    fake_id = str(uuid4())
    resp = client.get(f"/api/content-studio/packs/{fake_id}")
    assert resp.status_code == 404


# ── 9. test_get_variants_empty ───────────────────────────────────────────────


def test_get_variants_empty(client, seed_data, db_session):
    """GET /api/content-studio/packs/{id}/variants returns 200 with empty list when no variants."""
    pack = _make_pack(db_session)
    db_session.commit()

    resp = client.get(f"/api/content-studio/packs/{pack.id}/variants")
    assert resp.status_code == 200
    assert resp.json() == []


# ── 10. test_get_variants_with_data ──────────────────────────────────────────


def test_get_variants_with_data(client, seed_data, db_session):
    """GET /api/content-studio/packs/{id}/variants returns variants with correct data."""
    pack = _make_pack(db_session)
    v1 = _make_variant(db_session, pack.id, channel="ig_reel", variant_index=1, score=85.0)
    v2 = _make_variant(db_session, pack.id, channel="ig_reel", variant_index=2, score=70.0)
    v3 = _make_variant(db_session, pack.id, channel="ig_post", variant_index=1, score=60.0)
    db_session.commit()

    resp = client.get(f"/api/content-studio/packs/{pack.id}/variants")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3

    # Verify shape of each variant
    for v in data:
        assert "id" in v
        assert "channel" in v
        assert "variant_index" in v
        assert "output_json" in v
        assert "score" in v
        assert "rationale_text" in v

    # Verify ordering: by channel then variant_index
    channels_indices = [(v["channel"], v["variant_index"]) for v in data]
    assert channels_indices == sorted(channels_indices)


# ── 11. test_get_variants_filter_by_channel ──────────────────────────────────


def test_get_variants_filter_by_channel(client, seed_data, db_session):
    """GET /api/content-studio/packs/{id}/variants?channel=ig_reel filters correctly."""
    pack = _make_pack(db_session)
    _make_variant(db_session, pack.id, channel="ig_reel", variant_index=1)
    _make_variant(db_session, pack.id, channel="ig_reel", variant_index=2)
    _make_variant(db_session, pack.id, channel="ig_post", variant_index=1)
    _make_variant(db_session, pack.id, channel="tiktok_short", variant_index=1)
    db_session.commit()

    resp = client.get(f"/api/content-studio/packs/{pack.id}/variants?channel=ig_reel")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert all(v["channel"] == "ig_reel" for v in data)


# ── 12. test_lock_variant ────────────────────────────────────────────────────


def test_lock_variant(client, seed_data, db_session):
    """POST /api/content-studio/packs/{id}/lock locks a variant for a channel."""
    pack = _make_pack(db_session)
    variant = _make_variant(db_session, pack.id, channel="ig_reel", variant_index=1)
    db_session.commit()

    resp = client.post(f"/api/content-studio/packs/{pack.id}/lock", json={
        "channel": "ig_reel",
        "variant_id": str(variant.id),
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "locked"
    assert body["channel"] == "ig_reel"
    assert body["variant_id"] == str(variant.id)


# ── 13. test_lock_variant_not_found ──────────────────────────────────────────


def test_lock_variant_not_found(client, seed_data, db_session):
    """POST /api/content-studio/packs/{id}/lock with bad variant_id returns 404."""
    pack = _make_pack(db_session)
    db_session.commit()

    fake_variant_id = str(uuid4())
    resp = client.post(f"/api/content-studio/packs/{pack.id}/lock", json={
        "channel": "ig_reel",
        "variant_id": fake_variant_id,
    })
    assert resp.status_code == 404


# ── 14. test_export_pdf ──────────────────────────────────────────────────────


def test_export_pdf(client, seed_data, db_session):
    """GET /api/content-studio/packs/{id}/export/pdf returns 200 with application/pdf."""
    pack = _make_pack(db_session, status=ContentPackStatus.SUCCEEDED)
    _make_variant(db_session, pack.id, channel="ig_reel", variant_index=1, score=80.0)
    db_session.commit()

    resp = client.get(f"/api/content-studio/packs/{pack.id}/export/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "content-disposition" in resp.headers
    assert resp.headers["content-disposition"].startswith("attachment")
    # Verify it produced actual bytes (PDF magic bytes: %PDF)
    assert len(resp.content) > 0
    assert resp.content[:5] == b"%PDF-"


# ── 15. test_export_xlsx ─────────────────────────────────────────────────────


def test_export_xlsx(client, seed_data, db_session):
    """GET /api/content-studio/packs/{id}/export/xlsx returns 200 with xlsx content-type."""
    pack = _make_pack(db_session, status=ContentPackStatus.SUCCEEDED)
    _make_variant(db_session, pack.id, channel="ig_reel", variant_index=1, score=80.0)
    db_session.commit()

    resp = client.get(f"/api/content-studio/packs/{pack.id}/export/xlsx")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "content-disposition" in resp.headers
    assert resp.headers["content-disposition"].startswith("attachment")
    # XLSX files start with PK zip signature
    assert len(resp.content) > 0
    assert resp.content[:2] == b"PK"
