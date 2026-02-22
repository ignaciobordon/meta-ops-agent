"""Signals engine — detect actionable changes between crawl runs."""
from __future__ import annotations

from datetime import datetime

from .diff_engine import pricing_diff, cta_diff
from .extractors import extract_headlines, extract_offers
from .models import ExtractedPageData, SignalEvent, SignalType


def detect_signals(
    current_pages: dict[str, ExtractedPageData],
    previous_pages: dict[str, ExtractedPageData],
    current_html: dict[str, str] | None = None,
    previous_html: dict[str, str] | None = None,
) -> list[SignalEvent]:
    """
    Compare current crawl vs previous crawl and emit signal events.

    Args:
        current_pages: url -> ExtractedPageData for this run
        previous_pages: url -> ExtractedPageData for last run
        current_html: url -> raw HTML (optional, for pricing/CTA diffs)
        previous_html: url -> raw HTML (optional, for pricing/CTA diffs)

    Returns:
        List of SignalEvent objects
    """
    current_html = current_html or {}
    previous_html = previous_html or {}
    signals: list[SignalEvent] = []
    now = datetime.utcnow()

    current_urls = set(current_pages.keys())
    previous_urls = set(previous_pages.keys())

    # ── New pages ────────────────────────────────────────────────────────────
    for url in current_urls - previous_urls:
        signals.append(
            SignalEvent(
                type=SignalType.NEW_PAGES,
                url=url,
                old_value=None,
                new_value=current_pages[url].title or url,
                detected_at=now,
            )
        )

    # ── Removed pages ────────────────────────────────────────────────────────
    for url in previous_urls - current_urls:
        signals.append(
            SignalEvent(
                type=SignalType.REMOVED_PAGES,
                url=url,
                old_value=previous_pages[url].title or url,
                new_value=None,
                detected_at=now,
            )
        )

    # ── Per-page comparisons (urls present in both runs) ─────────────────────
    for url in current_urls & previous_urls:
        curr = current_pages[url]
        prev = previous_pages[url]

        # Skip if content hash is identical
        if curr.content_hash == prev.content_hash:
            continue

        # Headline changes
        if curr.headlines != prev.headlines:
            signals.append(
                SignalEvent(
                    type=SignalType.HEADLINE_CHANGES,
                    url=url,
                    old_value=prev.headlines,
                    new_value=curr.headlines,
                    detected_at=now,
                )
            )

        # Pricing changes (use HTML if available, fallback to extracted)
        if url in current_html and url in previous_html:
            pdiff = pricing_diff(previous_html[url], current_html[url])
            if pdiff["changed"]:
                signals.append(
                    SignalEvent(
                        type=SignalType.PRICING_CHANGES,
                        url=url,
                        old_value=pdiff["old_prices"],
                        new_value=pdiff["new_prices"],
                        detected_at=now,
                    )
                )
        elif curr.pricing_blocks != prev.pricing_blocks:
            signals.append(
                SignalEvent(
                    type=SignalType.PRICING_CHANGES,
                    url=url,
                    old_value=prev.pricing_blocks,
                    new_value=curr.pricing_blocks,
                    detected_at=now,
                )
            )

        # New offers
        old_offers = set(prev.offers)
        new_offers = [o for o in curr.offers if o not in old_offers]
        if new_offers:
            signals.append(
                SignalEvent(
                    type=SignalType.NEW_OFFERS,
                    url=url,
                    old_value=prev.offers,
                    new_value=curr.offers,
                    detected_at=now,
                )
            )

        # CTA changes
        if url in current_html and url in previous_html:
            cdiff = cta_diff(previous_html[url], current_html[url])
            if cdiff["changed"]:
                signals.append(
                    SignalEvent(
                        type=SignalType.CTA_CHANGES,
                        url=url,
                        old_value=cdiff["old_ctas"],
                        new_value=cdiff["new_ctas"],
                        detected_at=now,
                    )
                )
        elif curr.cta_phrases != prev.cta_phrases:
            signals.append(
                SignalEvent(
                    type=SignalType.CTA_CHANGES,
                    url=url,
                    old_value=prev.cta_phrases,
                    new_value=curr.cta_phrases,
                    detected_at=now,
                )
            )

    return signals
