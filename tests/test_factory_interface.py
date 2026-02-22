"""
Test Factory Interface — verifies the canonical method exists
and legacy methods do NOT exist.
"""
import os

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from src.engines.factory.factory import Factory


class TestFactoryCanonicalMethod:

    def test_factory_has_generate_scripts(self):
        """Factory must expose generate_scripts (plural)."""
        factory = Factory()
        assert hasattr(factory, "generate_scripts"), (
            "Factory is missing 'generate_scripts' method"
        )
        assert callable(factory.generate_scripts)

    def test_factory_no_generate_script_singular(self):
        """generate_script (singular) must NOT exist — it's a legacy name."""
        factory = Factory()
        assert not hasattr(factory, "generate_script"), (
            "Factory still has legacy 'generate_script' (singular). "
            "Only 'generate_scripts' (plural) should exist."
        )

    def test_factory_no_score_method(self):
        """Factory should not have a score() method — scoring belongs to Scorer."""
        factory = Factory()
        assert not hasattr(factory, "score"), (
            "Factory should not have 'score' method"
        )


class TestScorerCanonicalMethod:

    def test_scorer_has_evaluate(self):
        """Scorer must expose evaluate(), not score()."""
        from src.engines.scoring.scorer import Scorer
        scorer = Scorer()
        assert hasattr(scorer, "evaluate"), (
            "Scorer is missing 'evaluate' method"
        )
        assert callable(scorer.evaluate)

    def test_scorer_no_score_method(self):
        """score() is a legacy name — only evaluate() should exist."""
        from src.engines.scoring.scorer import Scorer
        scorer = Scorer()
        assert not hasattr(scorer, "score"), (
            "Scorer still has legacy 'score' method. "
            "Only 'evaluate' should exist."
        )


class TestBrandMapBuilderCanonicalMethod:

    def test_builder_has_build(self):
        """BrandMapBuilder must expose build()."""
        from src.engines.brand_map.builder import BrandMapBuilder
        builder = BrandMapBuilder()
        assert hasattr(builder, "build"), (
            "BrandMapBuilder is missing 'build' method"
        )
        assert callable(builder.build)
