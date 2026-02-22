"""
Tests for Content Studio channel_specs.py and schemas.py modules.
Pure unit tests — no database or external dependencies required.
"""
import os
import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.src.content.channel_specs import CHANNEL_SPECS, get_channel_spec, get_all_channels, ChannelSpec
from backend.src.content.schemas import (
    validate_channel_output, CHANNEL_OUTPUT_SCHEMAS, VariantScoreBreakdown,
    IGReelOutput, IGPostOutput, TikTokShortOutput, FBAdCopyOutput, EmailNewsletterOutput,
)
from pydantic import BaseModel


# ── channel_specs.py ─────────────────────────────────────────────────────────


def test_channel_specs_count():
    """CHANNEL_SPECS dict must contain exactly 13 channels."""
    assert len(CHANNEL_SPECS) == 13


def test_all_channels_are_channel_spec():
    """Every value in CHANNEL_SPECS must be an instance of ChannelSpec."""
    for key, spec in CHANNEL_SPECS.items():
        assert isinstance(spec, ChannelSpec), f"{key} is not a ChannelSpec instance"


def test_get_channel_spec_known():
    """get_channel_spec should return the correct ChannelSpec for a known key."""
    spec = get_channel_spec("ig_reel")
    assert spec is not None
    assert isinstance(spec, ChannelSpec)
    assert spec.key == "ig_reel"


def test_get_channel_spec_unknown():
    """get_channel_spec should return None for an unknown channel key."""
    result = get_channel_spec("nope")
    assert result is None


def test_get_all_channels():
    """get_all_channels should return a list of 13 ChannelSpec items."""
    channels = get_all_channels()
    assert isinstance(channels, list)
    assert len(channels) == 13
    for item in channels:
        assert isinstance(item, ChannelSpec)


def test_channel_spec_required_fields():
    """Every channel spec must define at least 2 required_fields."""
    for key, spec in CHANNEL_SPECS.items():
        assert len(spec.required_fields) >= 2, (
            f"Channel '{key}' has only {len(spec.required_fields)} required_fields"
        )


def test_channel_spec_best_practices():
    """Every channel spec must define at least 1 best_practice."""
    for key, spec in CHANNEL_SPECS.items():
        assert len(spec.best_practices) >= 1, (
            f"Channel '{key}' has no best_practices"
        )


# ── schemas.py ───────────────────────────────────────────────────────────────


def test_validate_channel_output_ig_reel():
    """validate_channel_output should return a valid IGReelOutput when given correct data."""
    data = {
        "hook": "test",
        "script": "test",
        "cta": "test",
        "hashtags": ["a"],
        "music_suggestion": "b",
        "shot_list": ["c"],
    }
    result = validate_channel_output("ig_reel", data)
    assert isinstance(result, IGReelOutput)
    assert result.hook == "test"
    assert result.hashtags == ["a"]


def test_validate_channel_output_unknown():
    """validate_channel_output should raise ValueError for an unknown channel key."""
    with pytest.raises(ValueError, match="No schema for channel"):
        validate_channel_output("nope", {})


def test_validate_channel_output_empty():
    """validate_channel_output should succeed with an empty dict because all fields have defaults."""
    result = validate_channel_output("ig_reel", {})
    assert isinstance(result, IGReelOutput)
    assert result.hook == ""
    assert result.hashtags == []


def test_variant_score_breakdown_total():
    """VariantScoreBreakdown.total should sum all component scores."""
    breakdown = VariantScoreBreakdown(
        hook_strength=25,
        clarity=15,
        cta_fit=10,
        channel_fit=15,
        brand_voice_match=15,
        goal_alignment=10,
        novelty=10,
    )
    assert breakdown.total == 100


def test_output_schemas_mapping():
    """CHANNEL_OUTPUT_SCHEMAS must map 13 channels and every value must be a BaseModel subclass."""
    assert len(CHANNEL_OUTPUT_SCHEMAS) == 13
    for key, schema_cls in CHANNEL_OUTPUT_SCHEMAS.items():
        assert issubclass(schema_cls, BaseModel), (
            f"Schema for '{key}' is not a BaseModel subclass"
        )
