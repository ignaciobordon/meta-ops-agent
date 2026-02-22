"""Diff engine — compare page versions, detect meaningful changes."""
from __future__ import annotations

import re
from difflib import unified_diff

from bs4 import BeautifulSoup

from .fingerprint import _clean_text


# ── Text normalization ───────────────────────────────────────────────────────


def _normalize_html_text(html: str) -> str:
    """Extract visible text, strip noise, normalize whitespace."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return _clean_text(text)


def _extract_section_texts(html: str) -> dict[str, str]:
    """Extract text per semantic section."""
    soup = BeautifulSoup(html, "html.parser")
    sections: dict[str, str] = {}
    for tag_name in ["header", "main", "footer", "nav"]:
        el = soup.find(tag_name)
        if el:
            sections[tag_name] = _clean_text(el.get_text(separator=" ", strip=True))
    # Named sections
    for idx, sec in enumerate(soup.find_all("section")):
        sec_id = sec.get("id") or sec.get("class", [f"section-{idx}"])
        if isinstance(sec_id, list):
            sec_id = sec_id[0] if sec_id else f"section-{idx}"
        sections[f"section:{sec_id}"] = _clean_text(
            sec.get_text(separator=" ", strip=True)
        )
    return sections


def _extract_prices(html: str) -> list[str]:
    """Pull all price strings from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    price_re = re.compile(
        r"[\$€£]\s?\d[\d,]*(?:\.\d{1,2})?|"
        r"\d[\d,]*(?:\.\d{1,2})?\s?(?:USD|EUR|ARS|/mo|/mes|/month)",
        re.IGNORECASE,
    )
    return sorted(set(price_re.findall(text)))


def _extract_ctas(html: str) -> list[str]:
    """Pull CTA texts from buttons/links."""
    soup = BeautifulSoup(html, "html.parser")
    ctas: list[str] = []
    for tag in soup.find_all(["button", "a"]):
        text = tag.get_text(strip=True)
        if text and len(text) < 100:
            ctas.append(text.lower())
    return sorted(set(ctas))


# ── Diff functions ───────────────────────────────────────────────────────────


def text_diff(old_html: str, new_html: str) -> list[str]:
    """Line-level diff of normalized visible text."""
    old_lines = _normalize_html_text(old_html).splitlines()
    new_lines = _normalize_html_text(new_html).splitlines()
    return list(
        unified_diff(old_lines, new_lines, lineterm="", n=1)
    )


def section_diff(old_html: str, new_html: str) -> dict[str, dict]:
    """Compare semantic sections between versions."""
    old_sections = _extract_section_texts(old_html)
    new_sections = _extract_section_texts(new_html)

    all_keys = set(old_sections) | set(new_sections)
    changes: dict[str, dict] = {}

    for key in all_keys:
        old_val = old_sections.get(key, "")
        new_val = new_sections.get(key, "")
        if old_val != new_val:
            changes[key] = {
                "old": old_val[:500] if old_val else None,
                "new": new_val[:500] if new_val else None,
                "status": (
                    "added" if not old_val else "removed" if not new_val else "changed"
                ),
            }
    return changes


def pricing_diff(old_html: str, new_html: str) -> dict:
    """Compare pricing between versions."""
    old_prices = _extract_prices(old_html)
    new_prices = _extract_prices(new_html)

    added = [p for p in new_prices if p not in old_prices]
    removed = [p for p in old_prices if p not in new_prices]

    return {
        "changed": bool(added or removed),
        "old_prices": old_prices,
        "new_prices": new_prices,
        "added": added,
        "removed": removed,
    }


def cta_diff(old_html: str, new_html: str) -> dict:
    """Compare CTAs between versions."""
    old_ctas = _extract_ctas(old_html)
    new_ctas = _extract_ctas(new_html)

    added = [c for c in new_ctas if c not in old_ctas]
    removed = [c for c in old_ctas if c not in new_ctas]

    return {
        "changed": bool(added or removed),
        "old_ctas": old_ctas,
        "new_ctas": new_ctas,
        "added": added,
        "removed": removed,
    }


def full_diff(old_html: str, new_html: str) -> dict:
    """Run all diff comparisons between two HTML versions."""
    return {
        "text_diff": text_diff(old_html, new_html),
        "section_diff": section_diff(old_html, new_html),
        "pricing_diff": pricing_diff(old_html, new_html),
        "cta_diff": cta_diff(old_html, new_html),
    }
