"""Mock storage — in-memory store with swappable interface for future DB."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import ExtractedPageData, SignalEvent


class PageStore(Protocol):
    """Interface for page storage. Replace with DB implementation later."""

    def store_page(self, url: str, html: str, data: ExtractedPageData) -> None: ...
    def load_last_page(self, url: str) -> tuple[str | None, ExtractedPageData | None]: ...
    def store_signals(self, domain: str, signals: list[SignalEvent]) -> None: ...


class InMemoryStore:
    """In-memory mock storage. Data is lost on process restart."""

    def __init__(self):
        self._pages: dict[str, list[tuple[str, ExtractedPageData, datetime]]] = {}
        self._signals: dict[str, list[SignalEvent]] = {}

    def store_page(self, url: str, html: str, data: ExtractedPageData) -> None:
        if url not in self._pages:
            self._pages[url] = []
        self._pages[url].append((html, data, datetime.utcnow()))

    def load_last_page(self, url: str) -> tuple[str | None, ExtractedPageData | None]:
        """Load the most recent version of a page."""
        entries = self._pages.get(url)
        if not entries:
            return None, None
        html, data, _ts = entries[-1]
        return html, data

    def load_previous_page(self, url: str) -> tuple[str | None, ExtractedPageData | None]:
        """Load the second-most-recent version (for diffing)."""
        entries = self._pages.get(url)
        if not entries or len(entries) < 2:
            return None, None
        html, data, _ts = entries[-2]
        return html, data

    def store_signals(self, domain: str, signals: list[SignalEvent]) -> None:
        if domain not in self._signals:
            self._signals[domain] = []
        self._signals[domain].extend(signals)

    def get_signals(self, domain: str) -> list[SignalEvent]:
        return self._signals.get(domain, [])

    def get_all_pages(self) -> dict[str, ExtractedPageData]:
        """Get latest ExtractedPageData for all URLs."""
        result: dict[str, ExtractedPageData] = {}
        for url, entries in self._pages.items():
            if entries:
                _, data, _ = entries[-1]
                result[url] = data
        return result

    def get_all_previous_pages(self) -> dict[str, ExtractedPageData]:
        """Get previous ExtractedPageData for all URLs (for diffing)."""
        result: dict[str, ExtractedPageData] = {}
        for url, entries in self._pages.items():
            if len(entries) >= 2:
                _, data, _ = entries[-2]
                result[url] = data
        return result

    def page_count(self) -> int:
        return len(self._pages)

    def version_count(self, url: str) -> int:
        return len(self._pages.get(url, []))
