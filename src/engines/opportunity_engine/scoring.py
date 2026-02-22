"""Scoring engine — compute priority, impact, and novelty scores."""
from __future__ import annotations

from .config import OpportunityConfig, DEFAULT_CONFIG
from .models import Opportunity


def compute_impact_score(
    frequency: float,
    growth_velocity: float,
    competitor_count: int,
    persistence: float,
) -> float:
    """
    Heuristic impact score based on observed patterns.

    Args:
        frequency:        normalized observation frequency (0–1)
        growth_velocity:  speed of change (0–1)
        competitor_count: number of competitors exhibiting this pattern
        persistence:      how long the pattern has been observed (0–1)

    Returns:
        impact score in [0, 1]
    """
    # Normalize competitor count (1 → 0.2, 5+ → 1.0)
    comp_factor = min(1.0, competitor_count / 5.0)

    # Weighted combination
    score = (
        0.30 * frequency
        + 0.30 * growth_velocity
        + 0.20 * comp_factor
        + 0.20 * persistence
    )
    return round(min(1.0, max(0.0, score)), 4)


def compute_novelty_score(
    similar_count: int,
    config: OpportunityConfig | None = None,
) -> float:
    """
    Novelty score decays as we see more similar opportunities.

    Args:
        similar_count: number of similar opportunities already detected
        config: engine config (for decay threshold)

    Returns:
        novelty score in [0, 1]
    """
    cfg = config or DEFAULT_CONFIG
    decay = cfg.novelty_decay_count
    if decay <= 0:
        return 1.0
    score = max(0.0, 1.0 - (similar_count / decay))
    return round(score, 4)


def compute_priority_score(
    confidence: float,
    impact: float,
    novelty: float,
) -> float:
    """
    priority = confidence × impact × novelty  (all 0–1 → product 0–1)
    """
    return round(
        max(0.0, min(1.0, confidence * impact * novelty)),
        4,
    )


def score_opportunity(
    opp: Opportunity,
    similar_count: int = 0,
    config: OpportunityConfig | None = None,
) -> Opportunity:
    """Recompute priority_score on an opportunity in-place and return it."""
    novelty = compute_novelty_score(similar_count, config)
    opp.priority_score = compute_priority_score(
        opp.confidence_score, opp.impact_score, novelty,
    )
    return opp
