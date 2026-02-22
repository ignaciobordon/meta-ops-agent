"""Page fingerprinting — structural + content hash to detect meaningful changes."""
from __future__ import annotations

import hashlib
import re

from bs4 import BeautifulSoup


# ── Noise patterns to strip before fingerprinting ─────────────────────────────

_STRIP_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b\d{10,13}\b"),                  # Unix timestamps
    re.compile(r"nonce=['\"]?[\w-]+['\"]?"),        # nonce tokens
    re.compile(r"session[_-]?id=['\"]?[\w-]+"),     # session ids
    re.compile(r"csrf[_-]?token=['\"]?[\w-]+"),     # CSRF tokens
    re.compile(r"utm_\w+=[^&\s]+"),                 # UTM tracking params
    re.compile(r"fbclid=[^&\s]+"),                  # FB click ids
    re.compile(r"gclid=[^&\s]+"),                   # Google click ids
    re.compile(r"_ga=[^&\s]+"),                     # GA cookies
    re.compile(r"\b[0-9a-f]{32,64}\b"),             # Long hex hashes (cache busters)
]


def _clean_text(text: str) -> str:
    """Remove noise patterns and normalize whitespace."""
    for pat in _STRIP_PATTERNS:
        text = pat.sub("", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ── DOM structure fingerprint ─────────────────────────────────────────────────


def dom_structure_fingerprint(html: str) -> str:
    """
    Generate a fingerprint based on the DOM tag structure.
    Ignores text content — only considers tag hierarchy.
    """
    soup = BeautifulSoup(html, "html.parser")
    tags: list[str] = []

    for tag in soup.find_all(True):
        depth = len(list(tag.parents)) - 1
        tags.append(f"{depth}:{tag.name}")

    structure = "|".join(tags)
    return hashlib.sha256(structure.encode()).hexdigest()[:32]


# ── Visible text fingerprint ─────────────────────────────────────────────────


def text_fingerprint(html: str) -> str:
    """
    Fingerprint based on visible text content, with noise stripped.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove script, style, noscript
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    cleaned = _clean_text(text)
    return hashlib.sha256(cleaned.encode()).hexdigest()[:32]


# ── Section-block fingerprint ─────────────────────────────────────────────────


def section_fingerprint(html: str) -> str:
    """
    Fingerprint based on major semantic sections (header, main, footer, sections).
    More resilient to minor text changes.
    """
    soup = BeautifulSoup(html, "html.parser")
    section_tags = ["header", "main", "footer", "section", "article", "aside", "nav"]
    parts: list[str] = []

    for tag_name in section_tags:
        for el in soup.find_all(tag_name):
            # Use tag name + child tag count + text length as lightweight fingerprint
            child_count = len(list(el.children))
            text_len = len(el.get_text(strip=True))
            parts.append(f"{tag_name}:{child_count}:{text_len}")

    blob = "|".join(parts) if parts else "empty"
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


# ── Combined fingerprint ─────────────────────────────────────────────────────


def page_fingerprint(html: str) -> str:
    """
    Combined fingerprint: hash of (dom_structure + text + section).
    Use this as the primary change-detection key.
    """
    d = dom_structure_fingerprint(html)
    t = text_fingerprint(html)
    s = section_fingerprint(html)
    combined = f"{d}|{t}|{s}"
    return hashlib.sha256(combined.encode()).hexdigest()[:40]


def content_hash(text: str) -> str:
    """Simple SHA-256 of raw text, truncated to 32 chars."""
    return hashlib.sha256(text.encode()).hexdigest()[:32]
