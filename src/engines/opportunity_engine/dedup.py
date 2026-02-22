"""Deduplication — merge similar opportunities within a time window."""
from __future__ import annotations

from .config import OpportunityConfig, DEFAULT_CONFIG
from .models import Opportunity


def should_merge(
    a: Opportunity,
    b: Opportunity,
    config: OpportunityConfig | None = None,
) -> bool:
    """
    Two opportunities should merge if:
      1. Same type
      2. Evidence overlap >= threshold
      3. Detected within time window
    """
    cfg = config or DEFAULT_CONFIG

    if a.type != b.type:
        return False

    # Evidence overlap
    overlap = len(set(a.evidence_ids) & set(b.evidence_ids))
    if overlap < cfg.dedup_evidence_overlap_min:
        return False

    # Time proximity
    diff_seconds = abs((a.detected_at - b.detected_at).total_seconds())
    if diff_seconds > cfg.dedup_window_hours * 3600:
        return False

    return True


def merge_opportunities(
    a: Opportunity,
    b: Opportunity,
) -> Opportunity:
    """Merge two opportunities, keeping the higher-scoring one and combining evidence."""
    # Keep the one with higher priority as base
    base, extra = (a, b) if a.priority_score >= b.priority_score else (b, a)

    # Combine evidence (deduplicated)
    combined_evidence = list(dict.fromkeys(base.evidence_ids + extra.evidence_ids))

    # Use earlier detected_at, later expires_at
    detected = min(base.detected_at, extra.detected_at)
    expires = None
    if base.expires_at and extra.expires_at:
        expires = max(base.expires_at, extra.expires_at)
    elif base.expires_at or extra.expires_at:
        expires = base.expires_at or extra.expires_at

    # Combine suggested actions (dedup)
    combined_actions = list(dict.fromkeys(base.suggested_actions + extra.suggested_actions))

    # Bump version
    return Opportunity(
        id=base.id,
        type=base.type,
        title=base.title,
        description=base.description,
        confidence_score=max(base.confidence_score, extra.confidence_score),
        impact_score=max(base.impact_score, extra.impact_score),
        priority_score=max(base.priority_score, extra.priority_score),
        evidence_ids=combined_evidence,
        detected_at=detected,
        expires_at=expires,
        suggested_actions=combined_actions,
        rationale=base.rationale,
        version=base.version + 1,
    )


def deduplicate_opportunities(
    opportunities: list[Opportunity],
    config: OpportunityConfig | None = None,
) -> list[Opportunity]:
    """
    Deduplicate a list of opportunities by merging similar ones.
    Returns a list with no duplicates.
    """
    if len(opportunities) <= 1:
        return list(opportunities)

    result: list[Opportunity] = []

    for opp in opportunities:
        merged = False
        for i, existing in enumerate(result):
            if should_merge(opp, existing, config):
                result[i] = merge_opportunities(existing, opp)
                merged = True
                break
        if not merged:
            result.append(opp)

    return result
