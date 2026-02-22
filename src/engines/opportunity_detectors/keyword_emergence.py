"""Detector: KeywordEmergenceDetector — finds new high-frequency words in competitor copy."""
from __future__ import annotations

from datetime import datetime, timedelta

from src.engines.opportunity_engine.baselines import STOPWORDS, extract_keywords
from src.engines.opportunity_engine.config import OpportunityConfig, DEFAULT_CONFIG
from src.engines.opportunity_engine.models import CanonicalItem, Opportunity, OpportunityType
from src.engines.opportunity_engine.scoring import compute_impact_score
from .base import BaseOpportunityDetector


def _simple_stem(word: str) -> str:
    """Very basic suffix stripping to collapse trivial morphological variants."""
    if len(word) <= 4:
        return word
    for suffix in ("ing", "tion", "ness", "ment", "able", "ible", "ous", "ive",
                    "ful", "less", "ity", "ally", "edly", "ando", "ción",
                    "mente", "idad", "oso", "osa", "ero", "era"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    # Plural stripping (English/Spanish)
    if word.endswith("es") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and len(word) > 4:
        return word[:-1]
    return word


class KeywordEmergenceDetector(BaseOpportunityDetector):
    name = "keyword_emergence"

    def run(
        self,
        current_items: list[CanonicalItem],
        previous_items: list[CanonicalItem] | None = None,
        config: OpportunityConfig | None = None,
    ) -> list[Opportunity]:
        cfg = config or DEFAULT_CONFIG
        previous_items = previous_items or []
        now = datetime.utcnow()
        opportunities: list[Opportunity] = []

        if not previous_items:
            return opportunities

        # Build keyword frequency (stemmed)
        curr_freq = self._stemmed_frequency(current_items)
        prev_freq = self._stemmed_frequency(previous_items)

        # Find emerging keywords: high current frequency, low/zero previous
        emerging: list[tuple[str, int, int]] = []  # (stem, curr_count, prev_count)

        for stem, curr_count in curr_freq.items():
            if curr_count < cfg.keyword_min_frequency:
                continue
            prev_count = prev_freq.get(stem, 0)

            # Emergence: new keyword OR >=3x increase
            if prev_count == 0 or (prev_count > 0 and curr_count / prev_count >= 3):
                emerging.append((stem, curr_count, prev_count))

        # Sort by current frequency descending
        emerging.sort(key=lambda x: x[1], reverse=True)

        # Group into a single opportunity if any emerging keywords found
        if not emerging:
            return opportunities

        # Take top 10 keywords
        top_keywords = emerging[:10]

        # Find evidence: items containing these keywords
        evidence_ids: list[str] = []
        all_competitors: set[str] = set()
        for item in current_items:
            text = f"{item.headline} {item.body}".lower()
            for stem, _, _ in top_keywords:
                if stem in text:
                    if item.id not in evidence_ids:
                        evidence_ids.append(item.id)
                    all_competitors.add(item.competitor)
                    break
        evidence_ids = evidence_ids[:15]

        # Build readable keyword list
        keyword_strings = [
            f"'{stem}' ({cc}x, was {pc}x)"
            for stem, cc, pc in top_keywords
        ]

        total_current = max(len(current_items), 1)
        coverage = len(evidence_ids) / total_current

        confidence = min(1.0, len(top_keywords) / 5)
        impact = compute_impact_score(
            frequency=min(1.0, coverage),
            growth_velocity=min(1.0, top_keywords[0][1] / 20),
            competitor_count=len(all_competitors),
            persistence=0.4,
        )

        opportunities.append(Opportunity(
            type=OpportunityType.KEYWORD_EMERGENCE,
            title=f"{len(top_keywords)} emerging keyword(s) detected",
            description=(
                f"New or rapidly growing keywords in competitor copy: "
                + ", ".join(keyword_strings[:5])
                + (f" (and {len(top_keywords) - 5} more)" if len(top_keywords) > 5 else "")
            ),
            confidence_score=round(confidence, 4),
            impact_score=round(impact, 4),
            evidence_ids=evidence_ids,
            detected_at=now,
            expires_at=now + timedelta(days=cfg.default_expiry_days),
            suggested_actions=[
                "Incorporate emerging keywords into your ad copy",
                "Research what products/offers these keywords relate to",
                "Update SEO/SEM strategy to include trending terms",
            ],
            rationale=(
                f"Detected {len(top_keywords)} keyword(s) that are new or rapidly "
                f"increasing in competitor ad copy: {', '.join(keyword_strings)}. "
                f"These appear across {len(all_competitors)} competitor(s). "
                f"Emerging keywords often indicate new market narratives, product "
                f"categories, or seasonal trends. Incorporating these terms into "
                f"your own messaging can improve relevance and ad performance."
            ),
        ))

        return opportunities

    @staticmethod
    def _stemmed_frequency(items: list[CanonicalItem]) -> dict[str, int]:
        """Build stemmed word frequency from all items."""
        freq: dict[str, int] = {}
        for item in items:
            text = f"{item.headline} {item.body}"
            words = extract_keywords(text)
            for word in words:
                stem = _simple_stem(word)
                if stem and stem not in STOPWORDS:
                    freq[stem] = freq.get(stem, 0) + 1
        return freq
