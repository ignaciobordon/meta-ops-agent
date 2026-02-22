"""
CP1 Test Suite — BrandMap Builder
DoD: JSON output passes 100% Pydantic validation, hash is present, ChromaDB has the entry.
"""
import os
import pytest
from dotenv import load_dotenv

load_dotenv()

from src.utils.logging_config import setup_logging, set_trace_id
from src.engines.brand_map import BrandMapBuilder
from src.schemas.brand_map import BrandMap
from src.database.vector.db_client import VectorDBClient

setup_logging()

BRAND_TEXTS = [
    "We sell premium organic dog food. Targeted at health-conscious millennial pet owners in urban areas. "
    "Our main product is a subscription box called BarkBox Premium at $79/month. "
    "Our tone is warm, scientific, and trustworthy. We compete with Purina and Blue Buffalo.",

    "SaaS tool for indie hackers to build landing pages in 5 minutes. No code needed. "
    "$29/month flat. Our users are solo founders frustrated by expensive Webflow templates. "
    "We're bootstrapped, ship fast, and obsess over simplicity.",

    "Premium fitness coaching for busy executives. 1-on-1 online sessions. "
    "$500/month. We guarantee results in 90 days or full refund. "
    "Competitors are Noom and personal trainers. Our edge is elite-level coaching at scale.",

    "Sustainable bamboo clothing brand. Our mission is zero-waste fashion. "
    "Target: eco-conscious women 25-40. Products: t-shirts, joggers, hoodies. "
    "$45-$89 price range. Competing with Patagonia and Allbirds.",

    "B2B lead generation agency for SaaS companies. We run cold email campaigns. "
    "Retainer model at $3k/month. Target: SaaS founders doing $1M-$10M ARR struggling with outbound. "
    "Our USP: we guarantee 10 qualified calls per month.",
]


@pytest.fixture(scope="module")
def builder():
    return BrandMapBuilder()


def test_schema_validation(builder):
    """All 5 brand text inputs should produce fully valid BrandMap objects."""
    set_trace_id("cp1-test-schema-validation")
    for i, text in enumerate(BRAND_TEXTS):
        brand_map = builder.build(text)
        assert isinstance(brand_map, BrandMap), f"Build {i} did not return a BrandMap"
        assert brand_map.metadata.hash, f"Build {i} missing hash"
        assert brand_map.core_identity.mission, f"Build {i} missing mission"
        assert len(brand_map.audience_model) >= 1, f"Build {i} has no audience avatars"
        assert len(brand_map.opportunity_map) >= 1, f"Build {i} has no opportunities"
        # Confirm Pydantic validation passes by re-parsing the JSON
        reparsed = BrandMap.model_validate_json(brand_map.model_dump_json())
        assert reparsed.metadata.hash == brand_map.metadata.hash


def test_hash_changes_on_different_input(builder):
    """Different inputs must produce different hashes."""
    set_trace_id("cp1-test-hash-diff")
    bm1 = builder.build(BRAND_TEXTS[0])
    bm2 = builder.build(BRAND_TEXTS[1])
    assert bm1.metadata.hash != bm2.metadata.hash


def test_hash_stable_for_same_input(builder):
    """Same input must always produce the same hash."""
    set_trace_id("cp1-test-hash-stable")
    h1 = BrandMap.content_hash(BRAND_TEXTS[0])
    h2 = BrandMap.content_hash(BRAND_TEXTS[0])
    assert h1 == h2


def test_stored_in_chromadb(builder):
    """After build(), the brand map entry must exist in ChromaDB."""
    set_trace_id("cp1-test-chromadb-storage")
    text = BRAND_TEXTS[2]
    brand_map = builder.build(text)

    db = VectorDBClient()
    collection = db.get_collection("brand_maps")
    results = collection.get(ids=[brand_map.metadata.hash])

    assert results["ids"], "No entry found in ChromaDB after build()"
    assert results["ids"][0] == brand_map.metadata.hash
    assert results["metadatas"][0]["hash"] == brand_map.metadata.hash


if __name__ == "__main__":
    set_trace_id("cp1-manual-run")
    b = BrandMapBuilder()
    result = b.build(BRAND_TEXTS[0])
    print(result.model_dump_json(indent=2))
    print(f"\n[PASS] CP1: BrandMap generated with hash={result.metadata.hash}")
