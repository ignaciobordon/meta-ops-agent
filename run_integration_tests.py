"""
Standalone Integration Test Runner for FASE 2.4
Runs all integration tests without pytest to avoid import issues.
"""
import sys
from pathlib import Path

# Setup path
root_path = Path(__file__).parent
sys.path.insert(0, str(root_path))

from src.engines.brand_map.builder import BrandMapBuilder
from src.engines.saturation.engine import SaturationEngine
from src.engines.tagger.tagger import Tagger
from src.engines.factory.factory import Factory
from src.engines.scoring.scorer import Scorer

# Test data paths
DATA_DIR = root_path / "data"
DEMO_BRAND_PATH = DATA_DIR / "demo_brand.txt"
DEMO_ADS_CSV_PATH = DATA_DIR / "demo_ads_performance.csv"


def test_brandmap_pipeline():
    """Test BrandMapBuilder -> Opportunities flow."""
    print("\n[TEST] BrandMapBuilder Pipeline...")

    builder = BrandMapBuilder()
    brand_text = DEMO_BRAND_PATH.read_text(encoding='utf-8')
    brand_map = builder.build(brand_text)

    assert brand_map.metadata.hash is not None
    assert brand_map.metadata.version == "2.0"
    assert len(brand_map.core_identity.mission) > 0
    assert len(brand_map.audience_model) > 0
    assert len(brand_map.opportunity_map) == 5

    print(f"  [PASS] BrandMap generated: {brand_map.metadata.hash}")
    print(f"  [PASS] Opportunities extracted: {len(brand_map.opportunity_map)}")


def test_saturation_pipeline():
    """Test SaturationEngine -> Ad Performance Analysis."""
    print("\n[TEST] Saturation Pipeline...")

    engine = SaturationEngine()
    df = engine.load_csv(str(DEMO_ADS_CSV_PATH))
    report = engine.analyze(df)

    assert len(df['ad_name'].unique()) == 5
    assert len(report.creatives) == 5

    # Check fresh vs saturated
    beginner_friendly = [c for c in report.creatives if "Beginner" in c.ad_name][0]
    results_proof = [c for c in report.creatives if "Results Proof" in c.ad_name][0]

    assert beginner_friendly.recommendation == "keep"
    assert beginner_friendly.saturation_score < 50

    assert results_proof.recommendation == "kill"
    assert results_proof.saturation_score > 70

    print(f"  [PASS] Analyzed {len(report.creatives)} creatives")
    print(f"  [PASS] Fresh creative identified: {beginner_friendly.ad_name} (score: {beginner_friendly.saturation_score:.1f}/100)")
    print(f"  [PASS] Saturated creative identified: {results_proof.ad_name} (score: {results_proof.saturation_score:.1f}/100)")


def test_creatives_pipeline():
    """Test Creatives generation/scoring with BrandMap."""
    print("\n[TEST] Creatives Pipeline...")

    # Test Tagger
    tagger = Tagger()
    result = tagger.classify("Transform your body in 8 weeks. Join our proven calisthenics program.")
    assert result.l1_intent is not None
    assert result.l2_driver is not None
    print(f"  [PASS] Tagger classified content: L1={result.l1_intent.tag_name}, L2={result.l2_driver.tag_name}")

    # Test Factory + Scorer
    builder = BrandMapBuilder()
    brand_text = DEMO_BRAND_PATH.read_text(encoding='utf-8')
    brand_map = builder.build(brand_text)

    factory = Factory()
    scripts = factory.generate_scripts(brand_map=brand_map, target_angles=["transformation"])
    assert len(scripts) > 0
    print(f"  [PASS] Factory generated {len(scripts)} script variants")

    scorer = Scorer()
    script_text = f"{scripts[0].hook}\n{scripts[0].body}\n{scripts[0].cta}"
    score_result = scorer.evaluate(asset=script_text, brand_map=brand_map)
    assert 0 <= score_result.overall_score <= 1
    print(f"  [PASS] Scorer evaluated script: {score_result.overall_score:.2f}/1.0")


def test_full_pipeline():
    """Test complete end-to-end pipeline integration."""
    print("\n[TEST] Full Pipeline Integration...")

    # Step 1: BrandMap
    builder = BrandMapBuilder()
    brand_text = DEMO_BRAND_PATH.read_text(encoding='utf-8')
    brand_map = builder.build(brand_text)
    assert brand_map is not None

    # Step 2: Opportunities
    opportunities = brand_map.opportunity_map
    assert len(opportunities) == 5

    # Step 3: Saturation
    sat_engine = SaturationEngine()
    df = sat_engine.load_csv(str(DEMO_ADS_CSV_PATH))
    sat_report = sat_engine.analyze(df)
    assert len(sat_report.creatives) == 5

    # Step 4: Generate Creative
    factory = Factory()
    scripts = factory.generate_scripts(brand_map=brand_map, target_angles=["transformation"])
    assert len(scripts) > 0

    # Step 5: Score Creative
    scorer = Scorer()
    script_text = f"{scripts[0].hook}\n{scripts[0].body}\n{scripts[0].cta}"
    score = scorer.evaluate(asset=script_text, brand_map=brand_map)
    assert 0 <= score.overall_score <= 1

    print(f"  [PASS] BrandMap: {brand_map.metadata.hash}")
    print(f"  [PASS] Opportunities: {len(opportunities)}")
    print(f"  [PASS] Saturation Analysis: {len(sat_report.creatives)} creatives")
    print(f"  [PASS] Creative Generated: {len(script_text)} characters")
    print(f"  [PASS] Creative Score: {score.overall_score:.2f}/1.0")


def main():
    """Run all integration tests."""
    print("="*70)
    print("FASE 2.4 Integration Tests - Full Pipeline")
    print("="*70)

    tests = [
        ("BrandMap Pipeline", test_brandmap_pipeline),
        ("Saturation Pipeline", test_saturation_pipeline),
        ("Creatives Pipeline", test_creatives_pipeline),
        ("Full Pipeline", test_full_pipeline),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"\n[FAIL] {name}: {str(e)}")
            failed += 1
        except Exception as e:
            print(f"\n[ERROR] {name}: {str(e)}")
            failed += 1

    print("\n" + "="*70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*70)

    if failed == 0:
        print("\n[SUCCESS] All integration tests passed!")
        print("[SUCCESS] FASE 2.4 COMPLETE: Full pipeline integration tested!")
        return 0
    else:
        print(f"\n[FAILURE] {failed} tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
