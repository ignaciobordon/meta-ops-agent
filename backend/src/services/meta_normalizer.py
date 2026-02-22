"""
Sprint 6 – BLOQUE C: Meta Data Normalizer
Normalizes raw Meta Graph API JSON into clean dicts for DB upsert.
Tolerates missing fields, safe type casting, no PII in output.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional


def _safe_float(value: Any) -> Optional[float]:
    """Safely cast to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    """Safely cast to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_datetime(value: Any) -> Optional[datetime]:
    """Parse ISO datetime string from Meta API."""
    if not value:
        return None
    try:
        if isinstance(value, datetime):
            return value
        # Meta returns ISO 8601: "2024-01-15T10:30:00+0000"
        value = str(value).replace("+0000", "+00:00").replace("Z", "+00:00")
        # Strip timezone info for naive datetime (our DB is UTC)
        if "+" in value and "T" in value:
            value = value.rsplit("+", 1)[0]
        if "-" in value and "T" in value and value.count("-") > 2:
            # Already has timezone offset in format -XX:XX
            parts = value.rsplit("-", 1)
            if len(parts[-1]) <= 5 and "T" not in parts[-1]:
                value = parts[0]
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _safe_date(value: Any) -> Optional[datetime]:
    """Parse date string (YYYY-MM-DD) from Meta API."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _extract_conversions(actions: Optional[List[Dict]]) -> Optional[int]:
    """Extract total conversions from Meta actions array."""
    if not actions:
        return None
    total = 0
    for action in actions:
        action_type = action.get("action_type", "")
        if action_type in ("purchase", "offsite_conversion.fb_pixel_purchase", "complete_registration"):
            total += _safe_int(action.get("value", 0)) or 0
    return total if total > 0 else None


def _extract_roas(actions: Optional[List[Dict]]) -> Optional[float]:
    """Extract purchase ROAS from Meta action values."""
    if not actions:
        return None
    for action in actions:
        if action.get("action_type") in ("purchase", "offsite_conversion.fb_pixel_purchase"):
            return _safe_float(action.get("value"))
    return None


def normalize_ad_account(meta_json: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a Meta ad account JSON response."""
    account_id = meta_json.get("account_id") or meta_json.get("id", "")
    # Ensure act_ prefix
    if account_id and not account_id.startswith("act_"):
        account_id = f"act_{account_id}"

    return {
        "meta_account_id": account_id,
        "name": meta_json.get("name", f"Account {account_id}"),
        "currency": meta_json.get("currency", "USD"),
        "timezone_name": meta_json.get("timezone_name"),
        "status": _map_account_status(meta_json.get("account_status")),
    }


def _map_account_status(status_code: Any) -> str:
    """Map Meta numeric account_status to string."""
    status_map = {1: "active", 2: "disabled", 3: "unsettled", 7: "pending_review", 9: "in_grace_period", 101: "temporarily_unavailable"}
    return status_map.get(_safe_int(status_code), "active")


def normalize_campaign(meta_json: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a Meta campaign JSON response."""
    # Meta returns budget in cents for some currencies
    daily_budget = _safe_float(meta_json.get("daily_budget"))
    lifetime_budget = _safe_float(meta_json.get("lifetime_budget"))
    # Convert cents to dollars (Meta API returns budget in account currency minor units)
    if daily_budget and daily_budget > 1000:
        daily_budget = daily_budget / 100
    if lifetime_budget and lifetime_budget > 1000:
        lifetime_budget = lifetime_budget / 100

    return {
        "meta_campaign_id": meta_json.get("id", ""),
        "name": meta_json.get("name"),
        "objective": meta_json.get("objective"),
        "status": meta_json.get("status"),
        "effective_status": meta_json.get("effective_status"),
        "daily_budget": daily_budget,
        "lifetime_budget": lifetime_budget,
        "bid_strategy": meta_json.get("bid_strategy"),
        "created_time": _safe_datetime(meta_json.get("created_time")),
        "updated_time": _safe_datetime(meta_json.get("updated_time")),
    }


def normalize_adset(meta_json: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a Meta adset JSON response."""
    daily_budget = _safe_float(meta_json.get("daily_budget"))
    lifetime_budget = _safe_float(meta_json.get("lifetime_budget"))
    if daily_budget and daily_budget > 1000:
        daily_budget = daily_budget / 100
    if lifetime_budget and lifetime_budget > 1000:
        lifetime_budget = lifetime_budget / 100

    return {
        "meta_adset_id": meta_json.get("id", ""),
        "meta_campaign_id": meta_json.get("campaign_id", ""),
        "name": meta_json.get("name"),
        "status": meta_json.get("status"),
        "effective_status": meta_json.get("effective_status"),
        "daily_budget": daily_budget,
        "lifetime_budget": lifetime_budget,
        "optimization_goal": meta_json.get("optimization_goal"),
        "billing_event": meta_json.get("billing_event"),
        "start_time": _safe_datetime(meta_json.get("start_time")),
        "end_time": _safe_datetime(meta_json.get("end_time")),
    }


def normalize_ad(meta_json: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a Meta ad JSON response."""
    # Extract creative ID from nested object
    creative = meta_json.get("creative", {})
    creative_id = creative.get("id") if isinstance(creative, dict) else None

    return {
        "meta_ad_id": meta_json.get("id", ""),
        "meta_adset_id": meta_json.get("adset_id", ""),
        "name": meta_json.get("name"),
        "status": meta_json.get("status"),
        "effective_status": meta_json.get("effective_status"),
        "creative_id": creative_id,
    }


def normalize_insight(row_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a Meta insights row.
    Maps actions array → conversions count and purchase_roas.
    """
    actions = row_json.get("actions")
    conversions_data = row_json.get("conversions")
    roas_data = row_json.get("purchase_roas")

    # Try extracting from nested action data
    conversions = _extract_conversions(actions) or _extract_conversions(conversions_data)
    purchase_roas_val = None
    if isinstance(roas_data, list):
        purchase_roas_val = _extract_roas(roas_data)
    elif roas_data is not None:
        purchase_roas_val = _safe_float(roas_data)

    return {
        "date_start": _safe_date(row_json.get("date_start")),
        "date_stop": _safe_date(row_json.get("date_stop")),
        "spend": _safe_float(row_json.get("spend")),
        "impressions": _safe_int(row_json.get("impressions")),
        "clicks": _safe_int(row_json.get("clicks")),
        "ctr": _safe_float(row_json.get("ctr")),
        "cpm": _safe_float(row_json.get("cpm")),
        "cpc": _safe_float(row_json.get("cpc")),
        "frequency": _safe_float(row_json.get("frequency")),
        "conversions": conversions,
        "purchase_roas": purchase_roas_val,
        "actions_json": actions,
        "conversions_json": conversions_data if isinstance(conversions_data, list) else None,
    }
