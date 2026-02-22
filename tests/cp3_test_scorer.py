"""
CP3 Test Suite — Creative Scorer
DoD:
  - evaluate() returns a valid EvaluationScore object
  - All dimension scores are in [0, 10]
  - overall_score matches weighted formula
  - A well-aligned ad scores higher than a misaligned one
  - All reasoning fields are non-empty
"""
import pytest
from src.utils.logging_config import setup_logging, set_trace_id
from src.engines.scoring import Scorer
from src.schemas.scoring import EvaluationScore
from src.schemas.brand_map import (
    BrandMap, BrandMapMetadata, CoreIdentity, OfferLayer,
    AudienceAvatar, DifferentiationLayer, NarrativeAssets,
    CreativeDNA, MarketContext,
)

setup_logging()

# ── Fixtures ────────────────────────────────────────────────────────────────

BRAND_MAP_DATA = {
    "core_identity": {
        "mission": "Help health-conscious millennial pet owners feed their dogs premium organic food.",
        "values": ["transparency", "quality", "sustainability"],
        "tone_voice": "warm, scientific, trustworthy",
        "personality_traits": ["caring", "expert", "authentic"],
    },
    "offer_layer": {
        "main_product": "BarkBox Premium subscription box at $79/month",
        "upsells": ["dental chews add-on", "training treats pack"],
        "pricing_psychology": "Subscription framing to reduce perceived monthly cost",
        "risk_reversal": "30-day money-back guarantee, cancel anytime",
    },
    "audience_model": [{
        "avatar_name": "Millennial Dog Mom",
        "demographics": "Women 28-40, urban, household income $75k+",
        "psychographics": "Treats pet like family, reads ingredient labels, Instagram-active",
        "pains": ["cheap kibble full of fillers", "vet bills from poor nutrition", "lack of transparency"],
        "desires": ["healthy happy dog", "trustworthy brand", "convenience"],
        "triggers": ["dog health scare stories", "vet recommendations", "social proof from other dog moms"],
    }],
    "differentiation_layer": {
        "usp": "100% organic, human-grade ingredients — the only sub box with vet-formulated recipes",
        "competitive_moat": "Proprietary supplier network + vet advisory board",
        "proof_points": ["10,000+ subscribers", "4.9/5 avg rating", "featured in Vogue"],
    },
    "narrative_assets": {
        "lore": "Founded after founder's dog got sick from cheap kibble",
        "story_hooks": ["The night Max got sick", "What vets won't tell you about kibble"],
        "core_myths": ["You can't afford to feed your dog well"],
    },
    "creative_dna": {
        "color_palette": ["Forest Green", "Warm White", "Gold"],
        "typography_intent": "Clean serif for trust, rounded sans for approachability",
        "visual_constraints": ["No artificial-looking photography", "Always show real dogs"],
    },
    "market_context": {
        "seasonal_factors": ["Holiday gifting season", "New Year pet health resolutions"],
        "current_trends": ["Humanization of pets", "Clean label movement"],
    },
    "competitor_map": [{"name": "Purina", "strategy_type": "Mass market", "weak_points": ["artificial ingredients"]}],
    "opportunity_map": [{"gap_id": "OPP-001", "strategy_recommendation": "Target vegan dog owners"}],
    "metadata": {"hash": "test1234abcd5678", "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"},
}

# Ad that tightly matches the brand
ALIGNED_AD = (
    "Is your dog's food actually safe? Most kibble brands hide fillers and by-products behind "
    "fancy packaging. BarkBox Premium uses 100% organic, human-grade ingredients — formulated "
    "by real vets who care about your dog as much as you do. "
    "Join 10,000+ dog moms who made the switch. "
    "Try your first box risk-free — cancel anytime, 30-day money-back guarantee. "
    "👉 Start today for $79/month."
)

# Ad that is off-brand (wrong tone, generic, no alignment to brand values)
MISALIGNED_AD = (
    "BIG SALE!! Dog food 50% OFF TODAY ONLY!! "
    "Click here to buy cheap dog treats!!! "
    "Limited stock — grab it now before it's gone! "
    "Use code SAVE50 at checkout. Hurry!!!"
)


@pytest.fixture(scope="module")
def scorer():
    set_trace_id("cp3-test-setup")
    return Scorer()


@pytest.fixture(scope="module")
def brand_map():
    return BrandMap.model_validate(BRAND_MAP_DATA)


# ── Tests ────────────────────────────────────────────────────────────────────

def test_returns_evaluation_score(scorer, brand_map):
    """evaluate() must return a valid EvaluationScore instance."""
    set_trace_id("cp3-test-returns-score")
    result = scorer.evaluate(ALIGNED_AD, brand_map)
    assert isinstance(result, EvaluationScore)


def test_scores_in_range(scorer, brand_map):
    """All dimension and overall scores must be within [0, 10]."""
    set_trace_id("cp3-test-scores-range")
    result = scorer.evaluate(ALIGNED_AD, brand_map)
    for dim in ("hook_strength", "brand_alignment", "clarity", "audience_fit", "cta_quality"):
        score = getattr(result, dim).score
        assert 0.0 <= score <= 10.0, f"{dim} score {score} out of range"
    assert 0.0 <= result.overall_score <= 10.0


def test_overall_score_matches_weights(scorer, brand_map):
    """overall_score must equal the weighted average of dimension scores (±0.1 tolerance)."""
    set_trace_id("cp3-test-weights")
    weights = {"hook_strength": 0.25, "brand_alignment": 0.20, "clarity": 0.20,
               "audience_fit": 0.20, "cta_quality": 0.15}
    result = scorer.evaluate(ALIGNED_AD, brand_map)
    expected = sum(getattr(result, dim).score * w for dim, w in weights.items())
    assert abs(result.overall_score - round(expected, 2)) < 0.1, (
        f"overall_score {result.overall_score} does not match weighted sum {expected:.2f}"
    )


def test_reasoning_not_empty(scorer, brand_map):
    """All reasoning fields must contain non-empty strings."""
    set_trace_id("cp3-test-reasoning")
    result = scorer.evaluate(ALIGNED_AD, brand_map)
    for dim in ("hook_strength", "brand_alignment", "clarity", "audience_fit", "cta_quality"):
        assert getattr(result, dim).reasoning, f"{dim}.reasoning is empty"
    assert result.overall_reasoning, "overall_reasoning is empty"


def test_aligned_beats_misaligned(scorer, brand_map):
    """The on-brand ad must score higher overall than the misaligned one."""
    set_trace_id("cp3-test-alignment-gap")
    aligned_result = scorer.evaluate(ALIGNED_AD, brand_map)
    misaligned_result = scorer.evaluate(MISALIGNED_AD, brand_map)
    assert aligned_result.overall_score > misaligned_result.overall_score, (
        f"Expected aligned ({aligned_result.overall_score}) > misaligned ({misaligned_result.overall_score})"
    )


if __name__ == "__main__":
    set_trace_id("cp3-manual-run")
    from src.engines.brand_map import BrandMapBuilder
    from src.schemas.brand_map import BrandMap

    bm = BrandMap.model_validate(BRAND_MAP_DATA)
    s = Scorer()
    result = s.evaluate(ALIGNED_AD, bm)
    print(result.model_dump_json(indent=2))
    print(f"\n[PASS] CP3: overall_score={result.overall_score}")
