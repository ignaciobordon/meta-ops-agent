"""Internal tick-based scheduler — tier-based crawl frequency, no cron."""
from __future__ import annotations

from datetime import datetime, timedelta

from .models import CrawlTarget, CrawlTier

# ── Tier intervals ───────────────────────────────────────────────────────────

TIER_INTERVALS: dict[CrawlTier, timedelta] = {
    CrawlTier.A: timedelta(days=1),
    CrawlTier.B: timedelta(weeks=1),
    CrawlTier.C: timedelta(days=30),
}


def compute_next_run(target: CrawlTarget) -> datetime:
    """Calculate next_run_at based on tier and last crawl."""
    interval = TIER_INTERVALS[target.tier]
    base = target.last_crawl_at or datetime.utcnow()
    return base + interval


def get_due_targets(
    targets: list[CrawlTarget], now: datetime | None = None
) -> list[CrawlTarget]:
    """Return targets that are due for crawling right now."""
    now = now or datetime.utcnow()
    due: list[CrawlTarget] = []

    for t in targets:
        # Never crawled → due immediately
        if t.last_crawl_at is None:
            due.append(t)
            continue
        # Has a computed next_run
        if t.next_run_at and t.next_run_at <= now:
            due.append(t)
            continue
        # Fallback: check interval
        interval = TIER_INTERVALS[t.tier]
        if (now - t.last_crawl_at) >= interval:
            due.append(t)

    return due


def update_after_crawl(target: CrawlTarget) -> CrawlTarget:
    """Update target timestamps after a successful crawl."""
    now = datetime.utcnow()
    target.last_crawl_at = now
    target.next_run_at = compute_next_run(target)
    return target


class Scheduler:
    """
    Simple tick-based scheduler.
    Call `tick()` periodically; it returns targets due for crawling.
    """

    def __init__(self, targets: list[CrawlTarget] | None = None):
        self._targets: list[CrawlTarget] = targets or []

    def add_target(self, target: CrawlTarget):
        # Compute initial next_run if missing
        if target.next_run_at is None:
            target.next_run_at = compute_next_run(target)
        self._targets.append(target)

    def remove_target(self, domain: str):
        self._targets = [t for t in self._targets if t.domain != domain]

    @property
    def targets(self) -> list[CrawlTarget]:
        return list(self._targets)

    def tick(self, now: datetime | None = None) -> list[CrawlTarget]:
        """Check which targets are due and return them."""
        return get_due_targets(self._targets, now)

    def mark_completed(self, domain: str):
        """Mark a target as crawled (updates timestamps)."""
        for t in self._targets:
            if t.domain == domain:
                update_after_crawl(t)
                break
