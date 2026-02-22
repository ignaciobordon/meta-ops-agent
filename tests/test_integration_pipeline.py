"""
FASE 2.4 Integration Tests - Full Pipeline
Tests: BrandMapBuilder -> Opportunities + Saturation + Creatives

Tests the complete intelligence module pipeline:
1. BrandMapBuilder generates from brand text
2. Opportunities extracted from BrandMap.opportunity_map
3. Saturation analyzes ad performance CSV
4. Creatives use BrandMap for generation/scoring
"""
import pytest


class TestBrandMapPipeline:
    """Test BrandMapBuilder -> Opportunities flow."""

    def test_brandmap_generation_from_text(self, demo_brand_path):
        """Test BrandMapBuilder generates valid BrandMap from demo text."""
        from src.engines.brand_map.builder import BrandMapBuilder

        assert demo_brand_path.exists(), f"Demo brand text not found: {demo_brand_path}"

        builder = BrandMapBuilder()
        brand_text = demo_brand_path.read_text(encoding='utf-8')
        brand_map = builder.build(brand_text)

        # Validate structure
        assert brand_map.metadata.hash is not None
        assert brand_map.metadata.version == "2.0"
        assert len(brand_map.core_identity.mission) > 0
        assert len(brand_map.audience_model) > 0
        assert len(brand_map.opportunity_map) > 0

    def test_opportunities_extracted_from_brandmap(self, demo_brand_path):
        """Test opportunities are correctly extracted from BrandMap."""
        from src.engines.brand_map.builder import BrandMapBuilder

        builder = BrandMapBuilder()
        brand_text = demo_brand_path.read_text(encoding='utf-8')
        brand_map = builder.build(brand_text)

        # Demo brand should have 5+ opportunities (LLM output may vary)
        assert len(brand_map.opportunity_map) >= 5

        # Verify first opportunity
        opp1 = brand_map.opportunity_map[0]
        assert opp1.gap_id == "OPP-001"
        assert len(opp1.strategy_recommendation) > 0

    def test_brandmap_hash_stable(self, demo_brand_path):
        """Test BrandMap hash is stable for same input."""
        from src.engines.brand_map.builder import BrandMapBuilder

        builder = BrandMapBuilder()
        brand_text = demo_brand_path.read_text(encoding='utf-8')

        brand_map1 = builder.build(brand_text)
        brand_map2 = builder.build(brand_text)

        assert brand_map1.metadata.hash == brand_map2.metadata.hash


class TestSaturationPipeline:
    """Test SaturationEngine -> Ad Performance Analysis."""

    def test_saturation_analyzes_csv(self, demo_ads_csv_path):
        """Test SaturationEngine analyzes demo ad performance CSV."""
        from src.engines.saturation.engine import SaturationEngine

        assert demo_ads_csv_path.exists(), f"Demo ads CSV not found: {demo_ads_csv_path}"

        engine = SaturationEngine()
        df = engine.load_csv(str(demo_ads_csv_path))

        # Should load 5 different ad creatives
        assert len(df['ad_name'].unique()) == 5

        # Analyze saturation
        report = engine.analyze(df)
        assert len(report.creatives) == 5

    def test_saturation_identifies_fresh_vs_saturated(self, demo_ads_csv_path):
        """Test SaturationEngine assigns recommendations to creatives."""
        from src.engines.saturation.engine import SaturationEngine

        engine = SaturationEngine()
        df = engine.load_csv(str(demo_ads_csv_path))
        report = engine.analyze(df)

        # All creatives should have a valid recommendation
        valid_recommendations = {"keep", "monitor", "refresh", "kill"}
        for creative in report.creatives:
            assert creative.recommendation in valid_recommendations

        # Most saturated creative should have high saturation score
        most_saturated = max(report.creatives, key=lambda c: c.saturation_score)
        assert most_saturated.saturation_score > 0


class TestCreativesPipeline:
    """Test Creatives generation/scoring with BrandMap."""

    def test_tagger_classifies_content(self):
        """Test Tagger classifies ad content into taxonomy."""
        from src.engines.tagger.tagger import Tagger

        tagger = Tagger()
        ad_content = "Transform your body in 8 weeks. Join our proven calisthenics program."

        result = tagger.classify(ad_content)

        # Should return taxonomy classification
        assert result.l1_intent is not None
        assert len(result.l3_execution) > 0

    def test_factory_generates_scripts(self, demo_brand_path):
        """Test Factory generates creative scripts using BrandMap."""
        from src.engines.factory.factory import Factory
        from src.engines.brand_map.builder import BrandMapBuilder

        # Load BrandMap
        builder = BrandMapBuilder()
        brand_text = demo_brand_path.read_text(encoding='utf-8')
        brand_map = builder.build(brand_text)

        factory = Factory()
        scripts = factory.generate_scripts(
            brand_map=brand_map,
            target_angles=["transformation"],
        )

        # Should generate at least 1 script
        assert len(scripts) > 0
        assert scripts[0].hook is not None

    def test_scorer_scores_scripts(self, demo_brand_path):
        """Test Scorer evaluates creative scripts using BrandMap."""
        from src.engines.scoring.scorer import Scorer
        from src.engines.brand_map.builder import BrandMapBuilder

        # Load BrandMap
        builder = BrandMapBuilder()
        brand_text = demo_brand_path.read_text(encoding='utf-8')
        brand_map = builder.build(brand_text)

        scorer = Scorer()
        test_script = "Transform your body in 8 weeks with our proven calisthenics program. No gym required."

        score_result = scorer.evaluate(
            asset=test_script,
            brand_map=brand_map
        )

        # Should return score between 0-10
        assert 0 <= score_result.overall_score <= 10
        assert len(score_result.overall_reasoning) > 0


class TestFullPipelineIntegration:
    """Test complete end-to-end pipeline integration."""

    def test_complete_flow(self, demo_brand_path, demo_ads_csv_path):
        """Test complete flow: BrandMap -> Opportunities + Saturation + Creatives."""
        from src.engines.brand_map.builder import BrandMapBuilder
        from src.engines.saturation.engine import SaturationEngine
        from src.engines.factory.factory import Factory
        from src.engines.scoring.scorer import Scorer

        # Step 1: Generate BrandMap
        builder = BrandMapBuilder()
        brand_text = demo_brand_path.read_text(encoding='utf-8')
        brand_map = builder.build(brand_text)
        assert brand_map is not None

        # Step 2: Extract Opportunities
        opportunities = brand_map.opportunity_map
        assert len(opportunities) >= 5

        # Step 3: Analyze Saturation
        sat_engine = SaturationEngine()
        df = sat_engine.load_csv(str(demo_ads_csv_path))
        sat_report = sat_engine.analyze(df)
        assert len(sat_report.creatives) == 5

        # Step 4: Generate Creative
        factory = Factory()
        scripts = factory.generate_scripts(
            brand_map=brand_map,
            target_angles=["transformation"],
        )
        assert len(scripts) > 0

        # Step 5: Score Creative
        scorer = Scorer()
        script_text = f"{scripts[0].hook}\n{scripts[0].body}\n{scripts[0].cta}"
        score = scorer.evaluate(asset=script_text, brand_map=brand_map)
        assert 0 <= score.overall_score <= 10

        print("\n[SUCCESS] Full pipeline integration test passed!")
        print(f"  BrandMap: {brand_map.metadata.hash}")
        print(f"  Opportunities: {len(opportunities)}")
        print(f"  Saturation Analysis: {len(sat_report.creatives)} creatives")
        print(f"  Creative Generated: {len(script_text)} chars")
        print(f"  Creative Score: {score.overall_score:.2f}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
