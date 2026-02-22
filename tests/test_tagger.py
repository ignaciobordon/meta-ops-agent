"""
Unit tests for Tagger module (CP2).
Tests classification accuracy and threshold behavior.
"""
import pytest
from src.engines.tagger.tagger import Tagger


class TestTaggerClassification:
    """Test tag classification accuracy."""

    def test_conversion_offer_detection(self):
        """Test that promotional offers are classified as Conversion/Offer intent."""
        tagger = Tagger()

        # Clear promotional offer
        ad_text = "Get 20% off your first order! Buy premium dog food now."
        result = tagger.classify(ad_text)

        # Should detect conversion intent
        assert result.l1_intent is not None, "L1 intent should be detected"
        assert result.l1_intent.tag in ["Conversion", "Consideration"], \
            f"Expected Conversion or Consideration, got {result.l1_intent.tag}"

        # Should detect offer/discount in top scores
        all_tags = [score.tag for score in result.all_scores[:5]]
        assert "Offer / Discount" in all_tags or "Urgency / Scarcity" in all_tags, \
            f"Expected 'Offer / Discount' in top 5 tags, got: {all_tags}"

    def test_social_proof_detection(self):
        """Test that testimonials are classified as Social Proof."""
        tagger = Tagger()

        ad_text = "Five star reviews from 10,000 happy customers. See what people are saying about us!"
        result = tagger.classify(ad_text)

        # Social Proof should be in top scores
        all_tags = [score.tag for score in result.all_scores[:5]]
        assert "Social Proof" in all_tags, f"Expected 'Social Proof' in top 5, got: {all_tags}"

    def test_brand_story_detection(self):
        """Test that founder stories are classified as Brand Story."""
        tagger = Tagger()

        ad_text = "Our founder started this company 10 years ago with a simple mission: help dogs live healthier lives."
        result = tagger.classify(ad_text)

        # Should detect Awareness or Brand Story
        assert result.l1_intent is not None
        assert result.l1_intent.tag in ["Awareness", "Advocacy", "Consideration"], \
            f"Expected Awareness-related tag, got {result.l1_intent.tag}"


class TestTaggerThreshold:
    """Test threshold behavior."""

    def test_threshold_enforcement(self):
        """Test that tags below threshold are excluded."""
        tagger = Tagger()

        # Generic text that shouldn't strongly match any tag
        ad_text = "Product."
        result = tagger.classify(ad_text)

        # All returned tags should be above threshold
        if result.l1_intent:
            assert result.l1_intent.score >= tagger.threshold, \
                f"L1 score {result.l1_intent.score} below threshold {tagger.threshold}"

        if result.l2_driver:
            assert result.l2_driver.score >= tagger.threshold, \
                f"L2 score {result.l2_driver.score} below threshold {tagger.threshold}"

        for l3_tag in result.l3_execution:
            assert l3_tag.score >= tagger.threshold, \
                f"L3 tag {l3_tag.tag} score {l3_tag.score} below threshold {tagger.threshold}"

    def test_top_k_l3_limit(self):
        """Test that L3 tags are limited to TOP_K (default 3)."""
        tagger = Tagger()

        ad_text = "Limited time offer! Get 50% off with free shipping and money-back guarantee. Five star reviews!"
        result = tagger.classify(ad_text)

        # Should return at most 3 L3 tags
        assert len(result.l3_execution) <= 3, \
            f"Expected max 3 L3 tags, got {len(result.l3_execution)}"


class TestTaggerRobustness:
    """Test edge cases and error handling."""

    def test_empty_string(self):
        """Test classification of empty string."""
        tagger = Tagger()
        result = tagger.classify("")

        # Should not crash, may return None or low-confidence tags
        assert result is not None
        assert hasattr(result, 'all_scores')

    def test_very_long_text(self):
        """Test classification of very long text."""
        tagger = Tagger()

        # 1000+ word text
        ad_text = "Premium dog food. " * 500
        result = tagger.classify(ad_text)

        # Should not crash
        assert result is not None
        assert len(result.all_scores) > 0

    def test_special_characters(self):
        """Test classification with special characters."""
        tagger = Tagger()

        ad_text = "🐕 Premium dog food! 20% OFF 💰 Limited time ⏰"
        result = tagger.classify(ad_text)

        # Should handle emojis without crashing
        assert result is not None

    def test_non_english_text(self):
        """Test classification with non-English text."""
        tagger = Tagger()

        ad_text = "Comida premium para perros. 20% de descuento."
        result = tagger.classify(ad_text)

        # Should not crash (may have low confidence)
        assert result is not None


class TestTaggerConsistency:
    """Test classification consistency."""

    def test_same_input_same_output(self):
        """Test that same input produces same classification."""
        tagger = Tagger()

        ad_text = "Get 20% off your first order!"

        result1 = tagger.classify(ad_text)
        result2 = tagger.classify(ad_text)

        # Should be deterministic
        assert result1.l1_intent == result2.l1_intent
        assert result1.l2_driver == result2.l2_driver

        # Scores should match
        if result1.l1_intent and result2.l1_intent:
            assert abs(result1.l1_intent.score - result2.l1_intent.score) < 0.0001


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
