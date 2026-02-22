"""
Tests for Content Studio — content_creator_service.py.
10 tests covering build_pack_from_creative, _parse_variants_json, and score_variant.
Uses SQLite in-memory DB for tests 1-4 (build_pack). No LLM calls.
"""
import os
import json
import pytest
from uuid import uuid4, UUID
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PG_UUID BEFORE any model imports so SQLite can handle UUID columns.
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.src.database.models import (
    Base, Organization, Creative, AdAccount, MetaConnection,
    ContentPack, ContentVariant, ContentPackStatus, ConnectionStatus,
)
from backend.src.services.content_creator_service import (
    build_pack_from_creative, generate_pack, _parse_variants_json, score_variant,
)


# ── Constants ─────────────────────────────────────────────────────────────────

ORG_ID = "00000000-0000-0000-0000-000000000001"
CONNECTION_ID = "00000000-0000-0000-0000-000000000002"
AD_ACCOUNT_ID = "00000000-0000-0000-0000-000000000003"
CREATIVE_ID = "00000000-0000-0000-0000-000000000004"

CHANNELS = [
    {"channel": "ig_reel", "format": "9x16_30s"},
    {"channel": "ig_post", "format": "1x1"},
]

SETTINGS = {
    "goal": "leads",
    "language": "es-AR",
    "tone_tags": ["professional", "urgent"],
    "curator_prompt": "Focus on conversion",
    "target_audience": "Small business owners",
}


# ── Fixtures ──────────────────────────────────────────────────────────────────


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

    # Seed organization
    org = Organization(
        id=UUID(ORG_ID),
        name="Test Org",
        slug="test-org",
    )
    session.add(org)

    # Seed meta connection (required FK for ad_accounts)
    conn = MetaConnection(
        id=UUID(CONNECTION_ID),
        org_id=UUID(ORG_ID),
        access_token_encrypted="fake-encrypted-token",
        status=ConnectionStatus.ACTIVE,
    )
    session.add(conn)

    # Seed ad account (required FK for creatives)
    ad_account = AdAccount(
        id=UUID(AD_ACCOUNT_ID),
        connection_id=UUID(CONNECTION_ID),
        meta_ad_account_id="act_test_123",
        name="Test Ad Account",
    )
    session.add(ad_account)

    # Seed creative
    creative = Creative(
        id=UUID(CREATIVE_ID),
        ad_account_id=UUID(AD_ACCOUNT_ID),
        name="Base Creative",
        ad_copy="Buy now",
        headline="Great Deal",
        overall_score=8.5,
        meta_ad_id="ad_test_001",
    )
    session.add(creative)

    session.commit()
    yield session
    session.close()


# ── Tests 1-4: build_pack_from_creative ───────────────────────────────────────


def test_build_pack_creates_record(db_session):
    """build_pack_from_creative creates a ContentPack with a valid UUID id."""
    pack = build_pack_from_creative(
        db=db_session,
        org_id=ORG_ID,
        creative_id=CREATIVE_ID,
        channels=CHANNELS,
        settings=SETTINGS,
    )
    assert pack is not None
    assert isinstance(pack.id, UUID)
    assert pack.org_id == UUID(ORG_ID)
    assert pack.creative_id == UUID(CREATIVE_ID)
    assert pack.goal == "leads"
    assert pack.language == "es-AR"

    # Verify it is persisted in the session
    found = db_session.query(ContentPack).filter(ContentPack.id == pack.id).first()
    assert found is not None
    assert found.id == pack.id


def test_build_pack_default_status(db_session):
    """build_pack_from_creative sets pack status to QUEUED."""
    pack = build_pack_from_creative(
        db=db_session,
        org_id=ORG_ID,
        creative_id=CREATIVE_ID,
        channels=CHANNELS,
        settings=SETTINGS,
    )
    assert pack.status == ContentPackStatus.QUEUED


def test_build_pack_stores_channels(db_session):
    """build_pack_from_creative stores the channels list in channels_json."""
    pack = build_pack_from_creative(
        db=db_session,
        org_id=ORG_ID,
        creative_id=CREATIVE_ID,
        channels=CHANNELS,
        settings=SETTINGS,
    )
    assert pack.channels_json == CHANNELS
    assert len(pack.channels_json) == 2
    assert pack.channels_json[0]["channel"] == "ig_reel"
    assert pack.channels_json[1]["channel"] == "ig_post"


def test_build_pack_stores_settings(db_session):
    """build_pack_from_creative stores settings in input_json with goal, language, etc."""
    pack = build_pack_from_creative(
        db=db_session,
        org_id=ORG_ID,
        creative_id=CREATIVE_ID,
        channels=CHANNELS,
        settings=SETTINGS,
    )
    assert pack.input_json is not None
    assert pack.input_json["goal"] == "leads"
    assert pack.input_json["language"] == "es-AR"
    assert pack.input_json["tone_tags"] == ["professional", "urgent"]
    assert pack.input_json["curator_prompt"] == "Focus on conversion"
    assert pack.input_json["target_audience"] == "Small business owners"


# ── Tests 5-9: _parse_variants_json ──────────────────────────────────────────


def test_parse_variants_json_valid_array():
    """_parse_variants_json parses a direct JSON array with output, score, rationale."""
    raw = json.dumps([{"output": {}, "score": {}, "rationale": "test"}])
    result = _parse_variants_json(raw, expected_count=5)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["rationale"] == "test"
    assert result[0]["output"] == {}
    assert result[0]["score"] == {}


def test_parse_variants_json_wrapped_in_object():
    """_parse_variants_json extracts inner array from a {variants: [...]} wrapper."""
    raw = json.dumps({"variants": [{"output": {"hook": "hi"}, "score": {}, "rationale": "wrapped"}]})
    result = _parse_variants_json(raw, expected_count=5)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["output"]["hook"] == "hi"


def test_parse_variants_json_embedded_in_text():
    """_parse_variants_json extracts JSON array embedded in surrounding text."""
    raw = 'Here are variants:\n[{"output": {"cta": "click"}, "score": {}, "rationale": "embedded"}]\nEnd of response.'
    result = _parse_variants_json(raw, expected_count=5)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["output"]["cta"] == "click"
    assert result[0]["rationale"] == "embedded"


def test_parse_variants_json_invalid():
    """_parse_variants_json raises ValueError when given non-JSON text."""
    with pytest.raises(ValueError, match="Failed to parse"):
        _parse_variants_json("not json at all", expected_count=3)


def test_parse_variants_json_truncates():
    """_parse_variants_json truncates array to expected_count."""
    variants = [{"output": {}, "score": {}, "rationale": f"v{i}"} for i in range(5)]
    raw = json.dumps(variants)
    result = _parse_variants_json(raw, expected_count=3)
    assert len(result) == 3
    assert result[0]["rationale"] == "v0"
    assert result[2]["rationale"] == "v2"


# ── Test 10: score_variant ───────────────────────────────────────────────────


def test_score_variant_returns_defaults():
    """score_variant returns a dict with all 7 default score keys."""
    result = score_variant({}, "ig_reel", {})
    assert isinstance(result, dict)
    expected_keys = {
        "hook_strength",
        "clarity",
        "cta_fit",
        "channel_fit",
        "brand_voice_match",
        "goal_alignment",
        "novelty",
    }
    assert set(result.keys()) == expected_keys
    assert len(result) == 7
    # Verify default values
    assert result["hook_strength"] == 15
    assert result["clarity"] == 10
    assert result["cta_fit"] == 7
    assert result["channel_fit"] == 10
    assert result["brand_voice_match"] == 10
    assert result["goal_alignment"] == 7
    assert result["novelty"] == 7
