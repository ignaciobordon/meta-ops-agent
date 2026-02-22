"""Abstract storage layer — in-memory implementation, swappable for DB."""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol

from .models import AdCanonical, SignalEvent


class AdsStore(Protocol):
    """Interface for ad storage. Replace with DB implementation later."""

    def store_ad(self, ad: AdCanonical) -> None: ...
    def get_ad(self, fingerprint: str) -> Optional[AdCanonical]: ...
    def get_existing_fingerprints(self, platform: str | None = None) -> set[str]: ...
    def store_signal(self, signal: SignalEvent) -> None: ...
    def get_signals(self, platform: str | None = None) -> list[SignalEvent]: ...
    def get_ads(
        self,
        platform: str | None = None,
        advertiser: str | None = None,
        country: str | None = None,
    ) -> list[AdCanonical]: ...


class InMemoryAdsStore:
    """In-memory mock storage. Data is lost on restart."""

    def __init__(self) -> None:
        self._ads: dict[str, AdCanonical] = {}          # fingerprint → ad
        self._signals: list[SignalEvent] = []
        self._ad_history: dict[str, list[AdCanonical]] = {}  # fingerprint → versions

    # ── Ads ───────────────────────────────────────────────────────────────────

    def store_ad(self, ad: AdCanonical) -> None:
        fp = ad.fingerprint
        if fp in self._ads:
            # Existing ad — update last_seen, keep history
            self._ads[fp].last_seen = ad.last_seen or datetime.utcnow()
            self._ad_history.setdefault(fp, []).append(ad)
        else:
            self._ads[fp] = ad

    def get_ad(self, fingerprint: str) -> Optional[AdCanonical]:
        return self._ads.get(fingerprint)

    def get_existing_fingerprints(self, platform: str | None = None) -> set[str]:
        if platform:
            return {
                fp for fp, ad in self._ads.items()
                if (ad.platform.value if hasattr(ad.platform, "value") else str(ad.platform)) == platform
            }
        return set(self._ads.keys())

    # ── Signals ───────────────────────────────────────────────────────────────

    def store_signal(self, signal: SignalEvent) -> None:
        self._signals.append(signal)

    def get_signals(self, platform: str | None = None) -> list[SignalEvent]:
        if platform:
            return [s for s in self._signals if s.platform == platform]
        return list(self._signals)

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_ads(
        self,
        platform: str | None = None,
        advertiser: str | None = None,
        country: str | None = None,
    ) -> list[AdCanonical]:
        result = list(self._ads.values())
        if platform:
            result = [
                a for a in result
                if (a.platform.value if hasattr(a.platform, "value") else str(a.platform)) == platform
            ]
        if advertiser:
            result = [a for a in result if advertiser.lower() in a.advertiser.lower()]
        if country:
            result = [a for a in result if a.country.upper() == country.upper()]
        return result

    def ad_count(self) -> int:
        return len(self._ads)

    def signal_count(self) -> int:
        return len(self._signals)
