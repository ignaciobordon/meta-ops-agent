"""
CP4 Test Suite — Saturation Engine
DoD:
  - analyze() returns a valid SaturationReport from real Meta Ads CSV
  - All saturation scores are in [0, 100]
  - All recommendations are valid enum values
  - most_saturated is a real ad name from the data
  - opportunity_gaps is non-empty with at least 1 item
  - Report is serializable to JSON without errors
"""
import os
import pytest
from src.utils.logging_config import setup_logging, set_trace_id
from src.engines.saturation import SaturationEngine
from src.schemas.saturation import SaturationReport

setup_logging()

DATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "v1", "daily_performance.csv"
)

VALID_RECOMMENDATIONS = {"keep", "monitor", "refresh", "kill"}


@pytest.fixture(scope="module")
def engine():
    set_trace_id("cp4-test-setup")
    return SaturationEngine()


@pytest.fixture(scope="module")
def report(engine):
    set_trace_id("cp4-test-report")
    df = engine.load_csv(DATA_PATH)
    return engine.analyze(df)


def test_returns_saturation_report(report):
    """analyze() must return a valid SaturationReport instance."""
    set_trace_id("cp4-test-type")
    assert isinstance(report, SaturationReport)


def test_has_creatives(report):
    """Report must contain at least one creative."""
    set_trace_id("cp4-test-creatives")
    assert len(report.creatives) >= 1


def test_scores_in_range(report):
    """All saturation scores and component scores must be in [0, 100]."""
    set_trace_id("cp4-test-scores-range")
    for c in report.creatives:
        assert 0.0 <= c.saturation_score <= 100.0, f"{c.ad_name}: saturation_score out of range"
        assert 0.0 <= c.frequency_score <= 100.0
        assert 0.0 <= c.ctr_decay_score <= 100.0
        assert 0.0 <= c.cpm_inflation_score <= 100.0
        assert 0.0 <= c.spend_share_pct <= 100.0


def test_valid_recommendations(report):
    """All recommendation values must be one of the 4 valid types."""
    set_trace_id("cp4-test-recommendations")
    for c in report.creatives:
        assert c.recommendation in VALID_RECOMMENDATIONS, (
            f"{c.ad_name}: invalid recommendation '{c.recommendation}'"
        )


def test_most_saturated_is_valid_ad(report):
    """most_saturated must be the name of a real ad in the creatives list."""
    set_trace_id("cp4-test-most-saturated")
    ad_names = {c.ad_name for c in report.creatives}
    assert report.most_saturated in ad_names


def test_opportunity_gaps_populated(report):
    """Opportunity gaps must contain at least one item."""
    set_trace_id("cp4-test-opportunities")
    assert len(report.opportunity_gaps) >= 1
    for gap in report.opportunity_gaps:
        assert gap.ad_name
        assert gap.rationale
        assert 0.0 <= gap.saturation_score <= 100.0


def test_serializable_to_json(report):
    """Report must serialize to JSON without errors."""
    set_trace_id("cp4-test-json")
    json_str = report.model_dump_json()
    assert len(json_str) > 100


if __name__ == "__main__":
    set_trace_id("cp4-manual-run")
    e = SaturationEngine()
    df = e.load_csv(DATA_PATH)
    r = e.analyze(df)
    print(r.model_dump_json(indent=2))
    print(f"\n[MOST SATURATED] {r.most_saturated}")
    print(f"[OPPORTUNITIES]")
    for gap in r.opportunity_gaps:
        print(f"  #{gap.rank} {gap.ad_name} (score={gap.saturation_score}) — {gap.rationale}")
