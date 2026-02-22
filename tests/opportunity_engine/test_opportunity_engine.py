"""Tests for the Opportunity Detection Engine — 40+ tests covering all blocks."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from src.engines.opportunity_engine.models import (
    CanonicalItem, Opportunity, OpportunityRunReport, OpportunityType,
)
from src.engines.opportunity_engine.config import OpportunityConfig, DEFAULT_CONFIG
from src.engines.opportunity_engine.scoring import (
    compute_impact_score, compute_novelty_score, compute_priority_score,
    score_opportunity,
)
from src.engines.opportunity_engine.baselines import (
    compute_ad_rate_per_competitor, compute_format_distribution,
    compute_keyword_frequency, count_ads_per_competitor,
    extract_keywords, build_offer_snapshots,
)
from src.engines.opportunity_engine.dedup import (
    deduplicate_opportunities, merge_opportunities, should_merge,
)
from src.engines.opportunity_engine.storage import InMemoryOpportunityStore
from src.engines.opportunity_engine.engine import OpportunityEngine
from src.engines.opportunity_detectors.new_ads_spike import NewAdsSpikeDetector
from src.engines.opportunity_detectors.angle_trend_rise import AngleTrendRiseDetector
from src.engines.opportunity_detectors.competitor_offer_change import CompetitorOfferChangeDetector
from src.engines.opportunity_detectors.format_dominance_shift import FormatDominanceShiftDetector
from src.engines.opportunity_detectors.keyword_emergence import KeywordEmergenceDetector, _simple_stem


# ── Helpers ──────────────────────────────────────────────────────────────────

NOW = datetime.utcnow()


def _item(
    competitor: str = "CompetitorA",
    headline: str = "Great Product",
    body: str = "Buy the best product today",
    item_type: str = "ad",
    fmt: str = "image",
    first_seen: datetime | None = None,
    price: float | None = None,
    discount: str = "",
    cta: str = "",
    guarantee: str = "",
    country: str = "US",
) -> CanonicalItem:
    return CanonicalItem(
        id=str(uuid.uuid4()),
        source="test",
        platform="meta",
        competitor=competitor,
        item_type=item_type,
        headline=headline,
        body=body,
        format=fmt,
        first_seen=first_seen or NOW,
        last_seen=first_seen or NOW,
        price=price,
        discount=discount,
        cta=cta,
        guarantee=guarantee,
        country=country,
    )


def _items_spread(
    n: int,
    competitor: str = "CompetitorA",
    days_back: int = 30,
    **kwargs,
) -> list[CanonicalItem]:
    """Create n items spread over days_back days."""
    items = []
    for i in range(n):
        offset = timedelta(days=days_back * i / max(n - 1, 1))
        items.append(_item(
            competitor=competitor,
            headline=f"Ad {i}",
            first_seen=NOW - timedelta(days=days_back) + offset,
            **kwargs,
        ))
    return items


# ══════════════════════════════════════════════════════════════════════════════
# 1. SCORING TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestScoring:

    def test_impact_score_range(self):
        score = compute_impact_score(0.5, 0.5, 3, 0.5)
        assert 0 <= score <= 1

    def test_impact_score_zero_inputs(self):
        score = compute_impact_score(0, 0, 0, 0)
        assert score == 0

    def test_impact_score_max_inputs(self):
        score = compute_impact_score(1.0, 1.0, 10, 1.0)
        assert score == 1.0

    def test_novelty_full_when_no_similar(self):
        assert compute_novelty_score(0) == 1.0

    def test_novelty_decays(self):
        n1 = compute_novelty_score(1)
        n3 = compute_novelty_score(3)
        assert n1 > n3

    def test_novelty_zero_at_threshold(self):
        cfg = OpportunityConfig(novelty_decay_count=5)
        assert compute_novelty_score(5, cfg) == 0.0

    def test_priority_score_product(self):
        score = compute_priority_score(0.8, 0.6, 1.0)
        assert score == pytest.approx(0.48, abs=0.01)

    def test_priority_score_clamps(self):
        assert compute_priority_score(1.5, 1.0, 1.0) == 1.0
        assert compute_priority_score(-0.5, 1.0, 1.0) == 0.0

    def test_score_opportunity_mutates(self):
        opp = Opportunity(
            type=OpportunityType.NEW_ADS_SPIKE,
            title="Test",
            description="Test opp",
            confidence_score=0.8,
            impact_score=0.7,
        )
        scored = score_opportunity(opp, similar_count=0)
        assert scored.priority_score > 0
        assert scored is opp  # mutated in place


# ══════════════════════════════════════════════════════════════════════════════
# 2. BASELINE TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestBaselines:

    def test_ad_rate_per_competitor(self):
        items = _items_spread(10, competitor="BrandA", days_back=30)
        rates = compute_ad_rate_per_competitor(items, window_days=30, now=NOW)
        assert "BrandA" in rates
        assert rates["BrandA"] > 0

    def test_count_ads_per_competitor(self):
        items = [_item(competitor="A"), _item(competitor="A"), _item(competitor="B")]
        counts = count_ads_per_competitor(items, window_days=7, now=NOW)
        assert counts["A"] == 2
        assert counts["B"] == 1

    def test_keyword_frequency(self):
        items = [
            _item(body="revolutionary product launch"),
            _item(body="another revolutionary idea"),
        ]
        freq = compute_keyword_frequency(items, window_days=7, now=NOW)
        assert freq["revolutionary"] == 2

    def test_extract_keywords_filters_stopwords(self):
        words = extract_keywords("The best product for your home")
        assert "the" not in words   # stopword
        assert "for" not in words   # stopword
        assert "your" not in words  # stopword
        assert "product" in words
        assert "home" in words
        assert "best" in words      # not a stopword — meaningful keyword

    def test_format_distribution(self):
        items = [
            _item(fmt="image"), _item(fmt="image", headline="i2"),
            _item(fmt="video", headline="v1"),
        ]
        dist = compute_format_distribution(items, window_days=7, now=NOW)
        assert dist["image"] == pytest.approx(2 / 3, abs=0.01)
        assert dist["video"] == pytest.approx(1 / 3, abs=0.01)

    def test_offer_snapshots(self):
        items = [
            _item(competitor="A", price=99),
            _item(competitor="B", price=49),
        ]
        snaps = build_offer_snapshots(items, window_days=7, now=NOW)
        assert "A" in snaps
        assert "B" in snaps


# ══════════════════════════════════════════════════════════════════════════════
# 3. DETECTOR: NewAdsSpikeDetector
# ══════════════════════════════════════════════════════════════════════════════

class TestNewAdsSpikeDetector:

    def test_detects_spike(self):
        # Baseline: 5 ads spread over 30 days
        previous = _items_spread(5, competitor="Nike", days_back=30)
        # Current: 10 ads in last 7 days (spike!)
        current = [
            _item(competitor="Nike", headline=f"New Ad {i}", first_seen=NOW - timedelta(days=i % 7))
            for i in range(10)
        ]
        detector = NewAdsSpikeDetector()
        opps = detector.run(current, previous)
        assert len(opps) >= 1
        assert opps[0].type == OpportunityType.NEW_ADS_SPIKE
        assert "Nike" in opps[0].title
        assert opps[0].rationale  # has explanation

    def test_no_spike_below_threshold(self):
        previous = _items_spread(10, competitor="Nike", days_back=30)
        current = [_item(competitor="Nike", first_seen=NOW - timedelta(days=1))]
        detector = NewAdsSpikeDetector()
        opps = detector.run(current, previous)
        assert len(opps) == 0

    def test_spike_with_no_previous(self):
        """No baseline → any cluster of ads is a spike."""
        current = [
            _item(competitor="NewBrand", headline=f"Ad {i}", first_seen=NOW - timedelta(hours=i))
            for i in range(5)
        ]
        detector = NewAdsSpikeDetector()
        opps = detector.run(current, [])
        assert len(opps) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# 4. DETECTOR: AngleTrendRiseDetector
# ══════════════════════════════════════════════════════════════════════════════

class TestAngleTrendRiseDetector:

    def test_detects_rising_angle(self):
        # Previous: 1/10 has "free"
        previous = [_item(body=f"product {i}") for i in range(10)]
        previous[0].body = "Get it free today"
        # Current: 8/10 have "free"
        current = [_item(body=f"Free offer {i}", headline=f"H{i}") for i in range(8)]
        current += [_item(body=f"Regular ad {i}", headline=f"R{i}") for i in range(2)]

        detector = AngleTrendRiseDetector()
        opps = detector.run(current, previous)
        free_opps = [o for o in opps if "free" in o.title.lower()]
        assert len(free_opps) >= 1
        assert free_opps[0].rationale

    def test_no_trend_without_previous(self):
        current = [_item(body="Free stuff free stuff")]
        detector = AngleTrendRiseDetector()
        opps = detector.run(current, [])
        assert len(opps) == 0

    def test_no_trend_stable_frequency(self):
        items = [_item(body="Great product for you", headline=f"H{i}") for i in range(10)]
        detector = AngleTrendRiseDetector()
        opps = detector.run(items, items)  # same data → no increase
        assert len(opps) == 0


# ══════════════════════════════════════════════════════════════════════════════
# 5. DETECTOR: CompetitorOfferChangeDetector
# ══════════════════════════════════════════════════════════════════════════════

class TestCompetitorOfferChangeDetector:

    def test_detects_price_change(self):
        previous = [_item(competitor="BrandX", price=99.0, first_seen=NOW - timedelta(days=10))]
        current = [_item(competitor="BrandX", price=79.0)]
        detector = CompetitorOfferChangeDetector()
        opps = detector.run(current, previous)
        assert len(opps) >= 1
        assert opps[0].type == OpportunityType.COMPETITOR_OFFER_CHANGE
        assert "BrandX" in opps[0].title

    def test_detects_discount_change(self):
        previous = [_item(competitor="BrandX", discount="", first_seen=NOW - timedelta(days=10))]
        current = [_item(competitor="BrandX", discount="20% off")]
        detector = CompetitorOfferChangeDetector()
        opps = detector.run(current, previous)
        assert len(opps) >= 1

    def test_detects_cta_change(self):
        previous = [_item(competitor="BrandX", cta="Learn More", first_seen=NOW - timedelta(days=10))]
        current = [_item(competitor="BrandX", cta="Buy Now")]
        detector = CompetitorOfferChangeDetector()
        opps = detector.run(current, previous)
        assert len(opps) >= 1

    def test_no_change_when_identical(self):
        items = [_item(competitor="BrandX", price=99.0, discount="10%")]
        detector = CompetitorOfferChangeDetector()
        opps = detector.run(items, items)
        assert len(opps) == 0


# ══════════════════════════════════════════════════════════════════════════════
# 6. DETECTOR: FormatDominanceShiftDetector
# ══════════════════════════════════════════════════════════════════════════════

class TestFormatDominanceShiftDetector:

    def test_detects_image_to_video_shift(self):
        previous = [_item(fmt="image", headline=f"P{i}") for i in range(8)] + \
                   [_item(fmt="video", headline=f"PV{i}") for i in range(2)]
        current = [_item(fmt="video", headline=f"C{i}") for i in range(8)] + \
                  [_item(fmt="image", headline=f"CI{i}") for i in range(2)]
        detector = FormatDominanceShiftDetector()
        opps = detector.run(current, previous)
        assert len(opps) >= 1
        video_opps = [o for o in opps if "video" in o.title.lower()]
        assert len(video_opps) >= 1

    def test_no_shift_when_stable(self):
        items = [_item(fmt="image", headline=f"H{i}") for i in range(10)]
        detector = FormatDominanceShiftDetector()
        opps = detector.run(items, items)
        assert len(opps) == 0

    def test_no_shift_empty_data(self):
        detector = FormatDominanceShiftDetector()
        opps = detector.run([], [])
        assert len(opps) == 0


# ══════════════════════════════════════════════════════════════════════════════
# 7. DETECTOR: KeywordEmergenceDetector
# ══════════════════════════════════════════════════════════════════════════════

class TestKeywordEmergenceDetector:

    def test_detects_new_keyword(self):
        previous = [_item(body=f"Regular product number {i}", headline=f"H{i}") for i in range(10)]
        current = [
            _item(body=f"Revolutionary breakthrough technology number {i}", headline=f"C{i}")
            for i in range(10)
        ]
        detector = KeywordEmergenceDetector()
        opps = detector.run(current, previous)
        assert len(opps) >= 1
        assert opps[0].type == OpportunityType.KEYWORD_EMERGENCE

    def test_no_emergence_without_previous(self):
        current = [_item(body="New amazing product")]
        detector = KeywordEmergenceDetector()
        opps = detector.run(current, [])
        assert len(opps) == 0

    def test_simple_stem(self):
        assert _simple_stem("running") == "runn"
        assert _simple_stem("products") == "product"
        assert _simple_stem("the") == "the"  # too short


# ══════════════════════════════════════════════════════════════════════════════
# 8. DEDUP TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestDedup:

    def test_should_merge_same_type_overlapping_evidence(self):
        a = Opportunity(
            type=OpportunityType.NEW_ADS_SPIKE,
            title="Spike A", description="D",
            evidence_ids=["e1", "e2"],
            detected_at=NOW,
        )
        b = Opportunity(
            type=OpportunityType.NEW_ADS_SPIKE,
            title="Spike B", description="D",
            evidence_ids=["e2", "e3"],
            detected_at=NOW + timedelta(hours=1),
        )
        assert should_merge(a, b)

    def test_no_merge_different_type(self):
        a = Opportunity(
            type=OpportunityType.NEW_ADS_SPIKE,
            title="A", description="D", evidence_ids=["e1"],
        )
        b = Opportunity(
            type=OpportunityType.ANGLE_TREND_RISE,
            title="B", description="D", evidence_ids=["e1"],
        )
        assert not should_merge(a, b)

    def test_no_merge_no_evidence_overlap(self):
        a = Opportunity(
            type=OpportunityType.NEW_ADS_SPIKE,
            title="A", description="D", evidence_ids=["e1"],
        )
        b = Opportunity(
            type=OpportunityType.NEW_ADS_SPIKE,
            title="B", description="D", evidence_ids=["e99"],
        )
        assert not should_merge(a, b)

    def test_merge_combines_evidence(self):
        a = Opportunity(
            type=OpportunityType.NEW_ADS_SPIKE,
            title="A", description="D",
            evidence_ids=["e1", "e2"],
            priority_score=0.8,
            detected_at=NOW,
        )
        b = Opportunity(
            type=OpportunityType.NEW_ADS_SPIKE,
            title="B", description="D",
            evidence_ids=["e2", "e3"],
            priority_score=0.6,
            detected_at=NOW + timedelta(hours=1),
        )
        merged = merge_opportunities(a, b)
        assert set(merged.evidence_ids) == {"e1", "e2", "e3"}
        assert merged.priority_score == 0.8
        assert merged.version == 2

    def test_deduplicate_list(self):
        opps = [
            Opportunity(
                type=OpportunityType.NEW_ADS_SPIKE,
                title="A", description="D",
                evidence_ids=["e1", "e2"],
                detected_at=NOW,
            ),
            Opportunity(
                type=OpportunityType.NEW_ADS_SPIKE,
                title="B", description="D",
                evidence_ids=["e2", "e3"],
                detected_at=NOW,
            ),
            Opportunity(
                type=OpportunityType.ANGLE_TREND_RISE,
                title="C", description="D",
                evidence_ids=["e4"],
                detected_at=NOW,
            ),
        ]
        result = deduplicate_opportunities(opps)
        assert len(result) == 2  # first two merged, third kept


# ══════════════════════════════════════════════════════════════════════════════
# 9. STORAGE TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestStorage:

    def test_store_and_retrieve(self):
        store = InMemoryOpportunityStore()
        opp = Opportunity(
            type=OpportunityType.NEW_ADS_SPIKE,
            title="Test", description="D",
            priority_score=0.7,
        )
        store.store_opportunity(opp)
        assert store.opportunity_count() == 1
        retrieved = store.get_opportunity(opp.id)
        assert retrieved is not None
        assert retrieved.title == "Test"

    def test_list_with_filters(self):
        store = InMemoryOpportunityStore()
        store.store_opportunity(Opportunity(
            type=OpportunityType.NEW_ADS_SPIKE,
            title="High", description="D", priority_score=0.9, confidence_score=0.8,
        ))
        store.store_opportunity(Opportunity(
            type=OpportunityType.ANGLE_TREND_RISE,
            title="Low", description="D", priority_score=0.1, confidence_score=0.2,
        ))
        high = store.list_opportunities(min_priority=0.5)
        assert len(high) == 1
        assert high[0].title == "High"

    def test_list_by_type(self):
        store = InMemoryOpportunityStore()
        store.store_opportunity(Opportunity(
            type=OpportunityType.NEW_ADS_SPIKE, title="S", description="D",
        ))
        store.store_opportunity(Opportunity(
            type=OpportunityType.KEYWORD_EMERGENCE, title="K", description="D",
        ))
        spike_only = store.list_opportunities(opp_type="new_ads_spike")
        assert len(spike_only) == 1

    def test_watermark(self):
        store = InMemoryOpportunityStore()
        assert store.last_run_at is None
        store.last_run_at = NOW
        assert store.last_run_at == NOW


# ══════════════════════════════════════════════════════════════════════════════
# 10. ENGINE ORCHESTRATION TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestEngine:

    def test_engine_init(self):
        engine = OpportunityEngine()
        assert "new_ads_spike" in engine._detectors
        assert "keyword_emergence" in engine._detectors
        assert len(engine._detectors) == 5

    def test_run_all_no_data(self):
        engine = OpportunityEngine()
        report = engine.run_all([], [])
        assert report.detectors_executed == 5
        assert report.opportunities_found == 0
        assert report.errors == 0

    def test_run_all_with_spike_data(self):
        engine = OpportunityEngine()
        previous = _items_spread(5, competitor="Nike", days_back=30)
        current = [
            _item(competitor="Nike", headline=f"New {i}", first_seen=NOW - timedelta(days=i % 3))
            for i in range(10)
        ]
        report = engine.run_all(current, previous)
        assert report.detectors_executed == 5
        assert report.opportunities_found >= 1

    def test_run_single_detector(self):
        engine = OpportunityEngine()
        items = [
            _item(competitor="Nike", headline=f"Ad {i}", first_seen=NOW - timedelta(hours=i))
            for i in range(5)
        ]
        report = engine.run_detector("new_ads_spike", items)
        assert report.detectors_executed == 1

    def test_run_unknown_detector(self):
        engine = OpportunityEngine()
        report = engine.run_detector("nonexistent", [])
        assert report.errors == 1

    def test_run_since_incremental(self):
        engine = OpportunityEngine()
        since = NOW - timedelta(days=3)
        old_items = [_item(first_seen=NOW - timedelta(days=10))]
        new_items = [
            _item(competitor="Nike", headline=f"New {i}", first_seen=NOW - timedelta(hours=i))
            for i in range(5)
        ]
        report = engine.run_since(since, old_items + new_items, old_items)
        # Only new_items should be processed (old_items filtered by since)
        assert report.detectors_executed == 5

    def test_get_opportunities_empty(self):
        engine = OpportunityEngine()
        assert engine.get_opportunities() == []

    def test_get_opportunity_not_found(self):
        engine = OpportunityEngine()
        assert engine.get_opportunity("nonexistent") is None

    def test_evidence_linking(self):
        """Verify opportunities link back to source item IDs."""
        engine = OpportunityEngine()
        items = [
            _item(competitor="Nike", headline=f"New {i}", first_seen=NOW - timedelta(hours=i))
            for i in range(6)
        ]
        item_ids = {it.id for it in items}
        engine.run_all(items, [])
        opps = engine.get_opportunities()
        for opp in opps:
            for eid in opp.evidence_ids:
                assert eid in item_ids, f"Evidence {eid} not traceable"

    def test_deterministic_same_input_same_output(self):
        """Same input → same opportunity types and counts."""
        config = OpportunityConfig()
        previous = _items_spread(5, competitor="Nike", days_back=30)
        current = [
            _item(competitor="Nike", headline=f"New {i}", first_seen=NOW - timedelta(hours=i))
            for i in range(8)
        ]

        engine1 = OpportunityEngine(config=config)
        r1 = engine1.run_all(current, previous)

        engine2 = OpportunityEngine(config=config)
        r2 = engine2.run_all(current, previous)

        assert r1.opportunities_found == r2.opportunities_found
        opps1 = engine1.get_opportunities()
        opps2 = engine2.get_opportunities()
        assert len(opps1) == len(opps2)
        for o1, o2 in zip(opps1, opps2):
            assert o1.type == o2.type


# ══════════════════════════════════════════════════════════════════════════════
# 11. MODEL SERIALIZATION TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestModels:

    def test_opportunity_json_roundtrip(self):
        opp = Opportunity(
            type=OpportunityType.NEW_ADS_SPIKE,
            title="Test",
            description="Test opportunity",
            confidence_score=0.85,
            impact_score=0.7,
            priority_score=0.595,
            evidence_ids=["e1", "e2"],
            suggested_actions=["Do X", "Do Y"],
            rationale="Because reasons.",
        )
        data = opp.model_dump()
        assert data["type"] == "new_ads_spike"
        restored = Opportunity.model_validate(data)
        assert restored.priority_score == opp.priority_score

    def test_canonical_item_json(self):
        item = _item(price=49.99, discount="10% off")
        data = item.model_dump()
        assert data["platform"] == "meta"
        assert data["price"] == 49.99

    def test_run_report_json(self):
        report = OpportunityRunReport(
            detectors_executed=5,
            opportunities_found=3,
            duration=0.42,
        )
        data = report.model_dump()
        assert data["detectors_executed"] == 5
