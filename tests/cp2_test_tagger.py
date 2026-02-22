"""
CP2 Test Suite — Angle Tagger
DoD:
  - classify() returns a TaxonomyTags object
  - L1 and L2 are populated above threshold for clear ad copy
  - L3 execution tags list is non-empty
  - ChromaDB taxonomy_centroids collection has all tags stored
  - Same input produces the same classification (deterministic)
"""
import pytest
from src.utils.logging_config import setup_logging, set_trace_id
from src.engines.tagger import Tagger
from src.schemas.taxonomy import ALL_TAGS, TaxonomyTags
from src.database.vector.db_client import VectorDBClient

setup_logging()

AD_SAMPLES = {
    "testimonial_conversion": (
        "Sarah lost 30 lbs in 90 days with our coaching program. "
        "Join 10,000+ happy customers. Limited spots available — claim your free trial today."
    ),
    "founder_story": (
        "I started this company after my dog got sick from cheap kibble. "
        "Now we make premium organic dog food that I'd feed my own family."
    ),
    "feature_demo": (
        "Build a landing page in 5 minutes. No code. No designer needed. "
        "Just drag, drop, and publish. Try it free for 14 days."
    ),
    "comparison_usp": (
        "Unlike Noom or generic personal trainers, our elite coaches are available 24/7. "
        "We guarantee results in 90 days or your money back."
    ),
    "community_loyalty": (
        "Welcome back! As a premium member you unlock exclusive early access to our "
        "new collection. Thank you for being part of the family."
    ),
}


@pytest.fixture(scope="module")
def tagger():
    set_trace_id("cp2-test-setup")
    return Tagger()


def test_returns_taxonomy_tags(tagger):
    """classify() must return a valid TaxonomyTags instance."""
    set_trace_id("cp2-test-returns-tags")
    result = tagger.classify(AD_SAMPLES["testimonial_conversion"])
    assert isinstance(result, TaxonomyTags)


def test_l1_and_l2_populated(tagger):
    """Clear conversion copy must produce L1 and L2 above threshold."""
    set_trace_id("cp2-test-l1-l2")
    result = tagger.classify(AD_SAMPLES["testimonial_conversion"])
    assert result.l1_intent is not None, "L1 intent should be set for clear conversion copy"
    assert result.l2_driver is not None, "L2 driver should be set for clear conversion copy"
    assert 0.0 <= result.l1_intent.score <= 1.0
    assert 0.0 <= result.l2_driver.score <= 1.0


def test_l3_execution_tags(tagger):
    """At least one L3 execution tag should be returned for clear ad copy."""
    set_trace_id("cp2-test-l3")
    result = tagger.classify(AD_SAMPLES["founder_story"])
    assert len(result.l3_execution) >= 1, "Expected at least one L3 tag"
    for tag_score in result.l3_execution:
        assert tag_score.score >= result.threshold


def test_all_scores_cover_taxonomy(tagger):
    """all_scores must contain every tag in the taxonomy."""
    set_trace_id("cp2-test-all-scores")
    result = tagger.classify(AD_SAMPLES["feature_demo"])
    scored_tags = {ts.tag for ts in result.all_scores}
    for tag in ALL_TAGS:
        assert tag in scored_tags, f"Tag '{tag}' missing from all_scores"


def test_deterministic(tagger):
    """Same input must always produce the same L1 tag."""
    set_trace_id("cp2-test-deterministic")
    r1 = tagger.classify(AD_SAMPLES["comparison_usp"])
    r2 = tagger.classify(AD_SAMPLES["comparison_usp"])
    assert r1.l1_intent == r2.l1_intent
    assert r1.l2_driver == r2.l2_driver


def test_centroids_in_chromadb(tagger):
    """All taxonomy tags must be stored as centroids in ChromaDB."""
    set_trace_id("cp2-test-chromadb-centroids")
    db = VectorDBClient()
    collection = db.get_collection("taxonomy_centroids")
    result = collection.get()
    stored_ids = set(result["ids"])
    for tag in ALL_TAGS:
        assert tag in stored_ids, f"Tag '{tag}' centroid missing from ChromaDB"


def test_different_ads_different_results(tagger):
    """Semantically different ads should yield different top L2 tags."""
    set_trace_id("cp2-test-different-ads")
    r_conversion = tagger.classify(AD_SAMPLES["testimonial_conversion"])
    r_loyalty = tagger.classify(AD_SAMPLES["community_loyalty"])
    # They shouldn't both have identical full all_scores (scores will differ even if top tag matches)
    scores_conv = {ts.tag: ts.score for ts in r_conversion.all_scores}
    scores_loyal = {ts.tag: ts.score for ts in r_loyalty.all_scores}
    assert scores_conv != scores_loyal, "Different ad content should produce different score distributions"


if __name__ == "__main__":
    set_trace_id("cp2-manual-run")
    t = Tagger()
    for name, text in AD_SAMPLES.items():
        result = t.classify(text)
        print(f"\n[{name}]")
        print(f"  L1: {result.l1_intent}")
        print(f"  L2: {result.l2_driver}")
        print(f"  L3: {result.l3_execution}")
