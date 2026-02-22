"""Content extractors — pull structured marketing intelligence from HTML."""
from __future__ import annotations

import re
from collections import Counter

from bs4 import BeautifulSoup, Tag

# ── Helpers ──────────────────────────────────────────────────────────────────


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _visible_text(el: Tag) -> str:
    return el.get_text(separator=" ", strip=True)


def _dedupe(items: list[str], min_len: int = 3) -> list[str]:
    """Deduplicate, filter short strings, preserve order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        item = item.strip()
        normalized = item.lower()
        if len(item) >= min_len and normalized not in seen:
            seen.add(normalized)
            out.append(item)
    return out


# ── Extractors ───────────────────────────────────────────────────────────────


def extract_headlines(html: str) -> list[str]:
    """Extract all heading text (h1-h6)."""
    soup = _soup(html)
    results: list[str] = []
    for level in range(1, 7):
        for tag in soup.find_all(f"h{level}"):
            text = _visible_text(tag)
            if text:
                results.append(text)
    return _dedupe(results)


def extract_offers(html: str) -> list[str]:
    """Extract promotional offer text — discounts, free trials, limited-time."""
    soup = _soup(html)
    offer_patterns = re.compile(
        r"(\d+%\s*(?:off|descuento|desc))|"
        r"(free\s+(?:trial|shipping|delivery|envío))|"
        r"(limited[\s-]*time)|"
        r"(oferta\s+(?:especial|limitada))|"
        r"(save\s+\$?\d+)|"
        r"(buy\s+\d+\s+get)|"
        r"(gratis)|"
        r"(promo(?:ción|tion)?)",
        re.IGNORECASE,
    )
    results: list[str] = []
    for tag in soup.find_all(string=offer_patterns):
        parent = tag.parent
        if parent:
            text = _visible_text(parent)
            if len(text) < 300:
                results.append(text)
    return _dedupe(results)


def extract_pricing_blocks(html: str) -> list[str]:
    """Extract pricing elements — dollar/euro amounts, plan cards."""
    soup = _soup(html)
    price_re = re.compile(
        r"[\$€£]\s?\d[\d,]*(?:\.\d{1,2})?|"
        r"\d[\d,]*(?:\.\d{1,2})?\s?(?:USD|EUR|ARS|/mo|/mes|/month|/año|/year)",
        re.IGNORECASE,
    )
    results: list[str] = []

    # Price patterns in text
    for tag in soup.find_all(string=price_re):
        parent = tag.parent
        if parent:
            text = _visible_text(parent)
            if len(text) < 500:
                results.append(text)

    # Pricing card containers (common class patterns)
    for cls_pattern in ["pric", "plan", "tier", "package"]:
        for el in soup.find_all(class_=re.compile(cls_pattern, re.IGNORECASE)):
            text = _visible_text(el)
            if 10 < len(text) < 1000:
                results.append(text)

    return _dedupe(results)


def extract_cta_phrases(html: str) -> list[str]:
    """Extract call-to-action text from buttons, links with CTA patterns."""
    soup = _soup(html)
    results: list[str] = []

    # Buttons and links with action text
    cta_re = re.compile(
        r"(sign\s*up|get\s+started|buy\s+now|shop\s+now|subscribe|"
        r"start\s+free|join|register|comprar|suscri|empezar|"
        r"download|descargar|learn\s+more|try\s+free|book\s+now|"
        r"add\s+to\s+cart|checkout|contact\s+us|request\s+demo|"
        r"reservar|agendar|comenzar|inscrib)",
        re.IGNORECASE,
    )

    for tag in soup.find_all(["button", "a", "input"]):
        text = _visible_text(tag)
        if not text and tag.get("value"):
            text = tag["value"]
        if text and cta_re.search(text) and len(text) < 100:
            results.append(text)

    # Also check role="button" and class*="btn"/"cta"
    for el in soup.find_all(attrs={"role": "button"}):
        text = _visible_text(el)
        if text and len(text) < 100:
            results.append(text)

    for el in soup.find_all(class_=re.compile(r"btn|cta|button", re.IGNORECASE)):
        text = _visible_text(el)
        if text and len(text) < 100:
            results.append(text)

    return _dedupe(results)


def extract_guarantees(html: str) -> list[str]:
    """Extract guarantee/warranty/refund messaging."""
    soup = _soup(html)
    guarantee_re = re.compile(
        r"(money[\s-]*back|refund|guarantee|warranty|garant[ií]a|devoluc|"
        r"risk[\s-]*free|satisfaction|hassle[\s-]*free|no[\s-]*questions)",
        re.IGNORECASE,
    )
    results: list[str] = []
    for tag in soup.find_all(string=guarantee_re):
        parent = tag.parent
        if parent:
            text = _visible_text(parent)
            if 5 < len(text) < 500:
                results.append(text)
    return _dedupe(results)


def extract_product_names(html: str) -> list[str]:
    """Extract product/service names from structured data and headings."""
    soup = _soup(html)
    results: list[str] = []

    # Schema.org product names
    for el in soup.find_all(attrs={"itemprop": "name"}):
        text = _visible_text(el)
        if text:
            results.append(text)

    # og:title
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        results.append(og["content"])

    # Title tag
    title_tag = soup.find("title")
    if title_tag:
        text = _visible_text(title_tag)
        if text:
            results.append(text)

    # h1 tags (often product names)
    for h1 in soup.find_all("h1"):
        text = _visible_text(h1)
        if text and len(text) < 150:
            results.append(text)

    return _dedupe(results)


def extract_hero_sections(html: str) -> list[str]:
    """Extract hero/banner sections — typically the first major visual block."""
    soup = _soup(html)
    results: list[str] = []

    # Look for hero patterns in classes/ids
    for pattern in ["hero", "banner", "jumbotron", "masthead", "splash"]:
        for el in soup.find_all(
            class_=re.compile(pattern, re.IGNORECASE)
        ):
            text = _visible_text(el)
            if 10 < len(text) < 2000:
                results.append(text)
        for el in soup.find_all(id=re.compile(pattern, re.IGNORECASE)):
            text = _visible_text(el)
            if 10 < len(text) < 2000:
                results.append(text)

    # Fallback: first <section> or <header> with substantial content
    if not results:
        for tag_name in ["header", "section"]:
            first = soup.find(tag_name)
            if first:
                text = _visible_text(first)
                if len(text) > 20:
                    results.append(text)
                    break

    return _dedupe(results)


def extract_structured_lists(html: str) -> list[list[str]]:
    """Extract <ul>/<ol> lists with at least 3 items."""
    soup = _soup(html)
    results: list[list[str]] = []
    for list_tag in soup.find_all(["ul", "ol"]):
        items = []
        for li in list_tag.find_all("li", recursive=False):
            text = _visible_text(li)
            if text:
                items.append(text)
        if len(items) >= 3:
            results.append(items)
    return results


def extract_semantic_keywords(html: str, top_n: int = 20) -> list[str]:
    """Extract top semantic keywords by frequency (excluding stop words)."""
    soup = _soup(html)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True).lower()

    # Basic stop words (EN + ES)
    stop = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "out", "off", "over",
        "under", "again", "further", "then", "once", "and", "but", "or", "nor",
        "not", "so", "very", "just", "than", "too", "also", "only", "own",
        "same", "that", "this", "these", "those", "it", "its", "he", "she",
        "they", "them", "their", "we", "our", "you", "your", "i", "me", "my",
        "all", "each", "every", "both", "few", "more", "most", "other", "some",
        "such", "no", "nor", "if", "when", "how", "what", "which", "who",
        "de", "la", "el", "en", "y", "que", "los", "las", "un", "una",
        "por", "con", "para", "del", "al", "es", "se", "no", "su", "lo",
        "como", "más", "pero", "sus", "le", "ya", "o", "fue", "este",
    }

    words = re.findall(r"\b[a-záéíóúñü]{3,}\b", text)
    counter = Counter(w for w in words if w not in stop)
    return [word for word, _ in counter.most_common(top_n)]


# ── Aggregate extractor ──────────────────────────────────────────────────────


def extract_all(html: str, url: str = "") -> dict:
    """Run all extractors and return a flat dict of results."""
    from .fingerprint import content_hash

    return {
        "url": url,
        "content_hash": content_hash(html),
        "headlines": extract_headlines(html),
        "offers": extract_offers(html),
        "pricing_blocks": extract_pricing_blocks(html),
        "cta_phrases": extract_cta_phrases(html),
        "guarantees": extract_guarantees(html),
        "product_names": extract_product_names(html),
        "hero_sections": extract_hero_sections(html),
        "structured_lists": extract_structured_lists(html),
        "semantic_keywords": extract_semantic_keywords(html),
    }
