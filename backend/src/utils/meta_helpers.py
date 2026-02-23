"""Shared Meta helpers: objective labels and date-range parsing."""
from datetime import datetime, timedelta
from typing import Optional, Tuple

# ── Human-readable objective names (union of brain.py + analytics_service.py) ─

OBJECTIVE_LABELS = {
    "OUTCOME_LEADS": "Leads",
    "OUTCOME_ENGAGEMENT": "Engagement",
    "OUTCOME_AWARENESS": "Awareness",
    "OUTCOME_TRAFFIC": "Traffic",
    "OUTCOME_SALES": "Sales",
    "OUTCOME_APP_PROMOTION": "App Promotion",
    "CONVERSIONS": "Conversions",
    "LINK_CLICKS": "Link Clicks",
    "REACH": "Reach",
    "BRAND_AWARENESS": "Brand Awareness",
    "POST_ENGAGEMENT": "Post Engagement",
    "VIDEO_VIEWS": "Video Views",
    "MESSAGES": "Messages",
    "STORE_VISITS": "Store Visits",
    "LEAD_GENERATION": "Lead Generation",
    "PRODUCT_CATALOG_SALES": "Catalog Sales",
}


def parse_date_range(
    days: int,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Tuple[datetime, Optional[datetime]]:
    """Return (since_dt, until_dt) from either explicit dates or days offset."""
    if since:
        since_dt = datetime.strptime(since, "%Y-%m-%d")
    else:
        since_dt = datetime.utcnow() - timedelta(days=days)

    until_dt = None
    if until:
        until_dt = datetime.strptime(until, "%Y-%m-%d") + timedelta(days=1)

    return since_dt, until_dt
