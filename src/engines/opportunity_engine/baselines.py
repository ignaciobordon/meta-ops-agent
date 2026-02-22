"""Baseline computation — historical averages for comparison."""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta

from .models import CanonicalItem

_WHITESPACE_RE = re.compile(r"\s+")


def _items_in_window(
    items: list[CanonicalItem],
    end: datetime,
    window_days: int,
) -> list[CanonicalItem]:
    """Filter items whose first_seen falls within [end - window_days, end]."""
    start = end - timedelta(days=window_days)
    return [it for it in items if start <= it.first_seen <= end]


# ── Ad rate baseline ─────────────────────────────────────────────────────────

def compute_ad_rate_per_competitor(
    items: list[CanonicalItem],
    window_days: int = 30,
    now: datetime | None = None,
) -> dict[str, float]:
    """
    Average ads/day per competitor in the given window.
    Returns {competitor: ads_per_day}.
    """
    now = now or datetime.utcnow()
    window_items = _items_in_window(items, now, window_days)
    counts: dict[str, int] = {}
    for it in window_items:
        if it.item_type == "ad":
            counts[it.competitor] = counts.get(it.competitor, 0) + 1
    return {comp: cnt / max(window_days, 1) for comp, cnt in counts.items()}


def count_ads_per_competitor(
    items: list[CanonicalItem],
    window_days: int = 7,
    now: datetime | None = None,
) -> dict[str, int]:
    """Count total ads per competitor in the recent window."""
    now = now or datetime.utcnow()
    window_items = _items_in_window(items, now, window_days)
    counts: dict[str, int] = {}
    for it in window_items:
        if it.item_type == "ad":
            counts[it.competitor] = counts.get(it.competitor, 0) + 1
    return counts


# ── Keyword frequency ────────────────────────────────────────────────────────

_STOPWORDS_EN = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "of",
    "for", "is", "it", "be", "as", "was", "with", "by", "are", "this",
    "that", "from", "not", "have", "has", "had", "do", "does", "did",
    "will", "can", "may", "so", "if", "we", "you", "he", "she", "they",
    "i", "me", "my", "our", "your", "his", "her", "its", "us", "them",
    "all", "no", "yes", "up", "out", "get", "just", "been", "about",
    "more", "some", "very", "most", "also", "than", "then", "only",
    "what", "when", "who", "how", "which", "where", "each", "every",
    "any", "both", "few", "much", "own", "same", "such",
})
_STOPWORDS_ES = frozenset({
    "de", "el", "la", "en", "y", "los", "las", "un", "una", "es",
    "se", "que", "por", "con", "para", "del", "al", "lo", "su",
    "no", "más", "pero", "como", "ya", "o", "si", "me", "le",
    "ha", "muy", "sin", "sobre", "ser", "también", "fue", "han",
    "sus", "hay", "son", "entre", "está", "todo", "esta", "nos",
    "ni", "tu", "te", "ti", "mi", "uno", "dos", "tres",
})
STOPWORDS = _STOPWORDS_EN | _STOPWORDS_ES


def extract_keywords(text: str, min_length: int = 3) -> list[str]:
    """Tokenize text into meaningful keywords (lowercase, no stopwords)."""
    if not text:
        return []
    words = _WHITESPACE_RE.split(text.lower())
    clean = [
        re.sub(r"[^a-záéíóúñü0-9]", "", w)
        for w in words
    ]
    return [w for w in clean if len(w) >= min_length and w not in STOPWORDS]


def compute_keyword_frequency(
    items: list[CanonicalItem],
    window_days: int = 7,
    now: datetime | None = None,
) -> Counter:
    """Word frequency across all item text in the window."""
    now = now or datetime.utcnow()
    window_items = _items_in_window(items, now, window_days)
    counter: Counter = Counter()
    for it in window_items:
        text = f"{it.headline} {it.body}"
        counter.update(extract_keywords(text))
    return counter


# ── Format distribution ──────────────────────────────────────────────────────

def compute_format_distribution(
    items: list[CanonicalItem],
    window_days: int = 7,
    now: datetime | None = None,
) -> dict[str, float]:
    """Percentage of each ad format in the window. Returns {format: pct}."""
    now = now or datetime.utcnow()
    ads = [it for it in _items_in_window(items, now, window_days) if it.item_type == "ad"]
    if not ads:
        return {}
    counts: dict[str, int] = {}
    for ad in ads:
        fmt = ad.format or "unknown"
        counts[fmt] = counts.get(fmt, 0) + 1
    total = len(ads)
    return {fmt: round(cnt / total, 4) for fmt, cnt in counts.items()}


# ── Offer snapshots ──────────────────────────────────────────────────────────

def build_offer_snapshots(
    items: list[CanonicalItem],
    window_days: int = 7,
    now: datetime | None = None,
) -> dict[str, list[CanonicalItem]]:
    """Group items by competitor for offer comparison. Returns {competitor: [items]}."""
    now = now or datetime.utcnow()
    window_items = _items_in_window(items, now, window_days)
    groups: dict[str, list[CanonicalItem]] = {}
    for it in window_items:
        groups.setdefault(it.competitor, []).append(it)
    return groups
