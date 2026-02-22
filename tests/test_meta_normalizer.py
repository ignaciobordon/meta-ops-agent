"""
Tests for Meta Data Normalizer (pure functions, no DB needed).
Covers: normalize_campaign, normalize_adset, normalize_ad, normalize_ad_account,
        normalize_insight, and internal helpers (_safe_float, _safe_int,
        _safe_datetime, _safe_date).
"""
from datetime import datetime

import pytest

from backend.src.services.meta_normalizer import (
    normalize_campaign,
    normalize_adset,
    normalize_ad,
    normalize_ad_account,
    normalize_insight,
    _safe_float,
    _safe_int,
    _safe_datetime,
    _safe_date,
    _extract_conversions,
)


# ── Test: normalize_campaign ─────────────────────────────────────────────────


class TestNormalizeCampaign:
    """Tests for normalize_campaign."""

    def test_campaign_all_fields(self):
        """Normal campaign with every field populated."""
        raw = {
            "id": "120345678",
            "name": "Summer Sale 2025",
            "objective": "CONVERSIONS",
            "status": "ACTIVE",
            "effective_status": "ACTIVE",
            "daily_budget": "500",
            "lifetime_budget": "0",
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "created_time": "2025-06-01T12:00:00+0000",
            "updated_time": "2025-06-15T08:30:00+0000",
        }
        result = normalize_campaign(raw)

        assert result["meta_campaign_id"] == "120345678"
        assert result["name"] == "Summer Sale 2025"
        assert result["objective"] == "CONVERSIONS"
        assert result["status"] == "ACTIVE"
        assert result["effective_status"] == "ACTIVE"
        assert result["daily_budget"] == 500.0
        assert result["lifetime_budget"] == 0.0
        assert result["bid_strategy"] == "LOWEST_COST_WITHOUT_CAP"
        assert isinstance(result["created_time"], datetime)
        assert isinstance(result["updated_time"], datetime)

    def test_campaign_missing_fields_tolerates_nulls(self):
        """Campaign with only id -- all optional fields should be None."""
        raw = {"id": "99999"}
        result = normalize_campaign(raw)

        assert result["meta_campaign_id"] == "99999"
        assert result["name"] is None
        assert result["objective"] is None
        assert result["status"] is None
        assert result["effective_status"] is None
        assert result["daily_budget"] is None
        assert result["lifetime_budget"] is None
        assert result["bid_strategy"] is None
        assert result["created_time"] is None
        assert result["updated_time"] is None

    def test_campaign_budget_in_cents_converts_to_dollars(self):
        """Budget > 1000 is treated as cents and divided by 100."""
        raw = {
            "id": "111",
            "daily_budget": "500000",     # 500000 cents = $5000
            "lifetime_budget": "2000000",  # 2000000 cents = $20000
        }
        result = normalize_campaign(raw)

        assert result["daily_budget"] == 5000.0
        assert result["lifetime_budget"] == 20000.0

    def test_campaign_budget_at_threshold_not_converted(self):
        """Budget exactly at 1000 should NOT be converted (only > 1000)."""
        raw = {"id": "222", "daily_budget": "1000"}
        result = normalize_campaign(raw)

        assert result["daily_budget"] == 1000.0

    def test_campaign_empty_dict(self):
        """Completely empty input should produce defaults without crashing."""
        result = normalize_campaign({})

        assert result["meta_campaign_id"] == ""
        assert result["name"] is None
        assert result["daily_budget"] is None


# ── Test: normalize_adset ────────────────────────────────────────────────────


class TestNormalizeAdset:
    """Tests for normalize_adset."""

    def test_adset_all_fields(self):
        """Full adset payload normalizes correctly."""
        raw = {
            "id": "adset_001",
            "campaign_id": "campaign_001",
            "name": "Lookalike US 1%",
            "status": "ACTIVE",
            "effective_status": "ACTIVE",
            "daily_budget": "750",
            "lifetime_budget": "0",
            "optimization_goal": "OFFSITE_CONVERSIONS",
            "billing_event": "IMPRESSIONS",
            "start_time": "2025-07-01T00:00:00+0000",
            "end_time": "2025-07-31T23:59:59+0000",
        }
        result = normalize_adset(raw)

        assert result["meta_adset_id"] == "adset_001"
        assert result["meta_campaign_id"] == "campaign_001"
        assert result["name"] == "Lookalike US 1%"
        assert result["status"] == "ACTIVE"
        assert result["effective_status"] == "ACTIVE"
        assert result["daily_budget"] == 750.0
        assert result["lifetime_budget"] == 0.0
        assert result["optimization_goal"] == "OFFSITE_CONVERSIONS"
        assert result["billing_event"] == "IMPRESSIONS"
        assert isinstance(result["start_time"], datetime)
        assert isinstance(result["end_time"], datetime)

    def test_adset_missing_budget(self):
        """Adset without budget fields returns None for both."""
        raw = {"id": "adset_002", "campaign_id": "campaign_001", "name": "No Budget"}
        result = normalize_adset(raw)

        assert result["meta_adset_id"] == "adset_002"
        assert result["daily_budget"] is None
        assert result["lifetime_budget"] is None

    def test_adset_budget_in_cents(self):
        """Adset budget > 1000 converted from cents to dollars."""
        raw = {"id": "adset_003", "daily_budget": "150000"}
        result = normalize_adset(raw)

        assert result["daily_budget"] == 1500.0


# ── Test: normalize_ad ───────────────────────────────────────────────────────


class TestNormalizeAd:
    """Tests for normalize_ad."""

    def test_ad_with_creative_nested_object(self):
        """Creative as nested dict extracts creative_id."""
        raw = {
            "id": "ad_001",
            "adset_id": "adset_001",
            "name": "Image Ad Variant A",
            "status": "ACTIVE",
            "effective_status": "ACTIVE",
            "creative": {"id": "creative_555"},
        }
        result = normalize_ad(raw)

        assert result["meta_ad_id"] == "ad_001"
        assert result["meta_adset_id"] == "adset_001"
        assert result["name"] == "Image Ad Variant A"
        assert result["status"] == "ACTIVE"
        assert result["creative_id"] == "creative_555"

    def test_ad_missing_creative_returns_none(self):
        """Ad without creative key returns creative_id=None."""
        raw = {
            "id": "ad_002",
            "adset_id": "adset_001",
            "name": "No Creative Ad",
            "status": "PAUSED",
        }
        result = normalize_ad(raw)

        assert result["meta_ad_id"] == "ad_002"
        assert result["creative_id"] is None

    def test_ad_creative_as_non_dict_returns_none(self):
        """If creative is a string or other non-dict, creative_id should be None."""
        raw = {
            "id": "ad_003",
            "adset_id": "adset_002",
            "creative": "not_a_dict",
        }
        result = normalize_ad(raw)

        assert result["creative_id"] is None

    def test_ad_empty_creative_dict(self):
        """Empty creative dict results in None creative_id."""
        raw = {"id": "ad_004", "creative": {}}
        result = normalize_ad(raw)

        assert result["creative_id"] is None


# ── Test: normalize_ad_account ───────────────────────────────────────────────


class TestNormalizeAdAccount:
    """Tests for normalize_ad_account."""

    def test_ad_account_with_act_prefix(self):
        """Account that already has act_ prefix keeps it."""
        raw = {
            "account_id": "act_123456789",
            "name": "My Main Account",
            "currency": "EUR",
            "timezone_name": "Europe/Madrid",
            "account_status": 1,
        }
        result = normalize_ad_account(raw)

        assert result["meta_account_id"] == "act_123456789"
        assert result["name"] == "My Main Account"
        assert result["currency"] == "EUR"
        assert result["timezone_name"] == "Europe/Madrid"
        assert result["status"] == "active"

    def test_ad_account_without_act_prefix_adds_it(self):
        """Numeric-only account_id gets act_ prefix prepended."""
        raw = {"account_id": "987654321", "name": "Bare ID Account"}
        result = normalize_ad_account(raw)

        assert result["meta_account_id"] == "act_987654321"

    def test_ad_account_falls_back_to_id_field(self):
        """When account_id is missing, falls back to 'id' field."""
        raw = {"id": "act_fallback_001", "name": "Fallback Account"}
        result = normalize_ad_account(raw)

        assert result["meta_account_id"] == "act_fallback_001"

    def test_ad_account_defaults_currency_usd(self):
        """Missing currency defaults to USD."""
        raw = {"account_id": "act_111"}
        result = normalize_ad_account(raw)

        assert result["currency"] == "USD"

    def test_ad_account_disabled_status(self):
        """Account status 2 maps to 'disabled'."""
        raw = {"account_id": "act_222", "account_status": 2}
        result = normalize_ad_account(raw)

        assert result["status"] == "disabled"

    def test_ad_account_unknown_status_defaults_active(self):
        """Unrecognized account_status code defaults to 'active'."""
        raw = {"account_id": "act_333", "account_status": 999}
        result = normalize_ad_account(raw)

        assert result["status"] == "active"

    def test_ad_account_missing_name_generates_default(self):
        """Missing name generates 'Account act_xxx' string."""
        raw = {"account_id": "act_444"}
        result = normalize_ad_account(raw)

        assert result["name"] == "Account act_444"


# ── Test: normalize_insight ──────────────────────────────────────────────────


class TestNormalizeInsight:
    """Tests for normalize_insight."""

    def test_insight_with_actions_maps_conversions(self):
        """Actions array with purchase entries sums into conversions."""
        raw = {
            "date_start": "2025-08-01",
            "date_stop": "2025-08-01",
            "spend": "42.50",
            "impressions": "10000",
            "clicks": "350",
            "ctr": "3.5",
            "cpm": "4.25",
            "cpc": "0.12",
            "frequency": "1.8",
            "actions": [
                {"action_type": "purchase", "value": "12"},
                {"action_type": "link_click", "value": "350"},
                {"action_type": "complete_registration", "value": "5"},
            ],
        }
        result = normalize_insight(raw)

        assert isinstance(result["date_start"], datetime)
        assert result["date_start"].year == 2025
        assert result["date_start"].month == 8
        assert result["date_start"].day == 1
        assert isinstance(result["date_stop"], datetime)
        assert result["spend"] == 42.50
        assert result["impressions"] == 10000
        assert result["clicks"] == 350
        assert result["ctr"] == 3.5
        assert result["cpm"] == 4.25
        assert result["cpc"] == 0.12
        assert result["frequency"] == 1.8
        # purchase (12) + complete_registration (5) = 17
        assert result["conversions"] == 17
        assert result["actions_json"] is not None

    def test_insight_missing_actions_returns_none_conversions(self):
        """Insight without actions key yields conversions=None."""
        raw = {
            "date_start": "2025-08-01",
            "date_stop": "2025-08-01",
            "spend": "10.00",
            "impressions": "500",
            "clicks": "20",
        }
        result = normalize_insight(raw)

        assert result["conversions"] is None
        assert result["actions_json"] is None

    def test_insight_with_purchase_roas_as_list(self):
        """purchase_roas as a list of action objects extracts correctly."""
        raw = {
            "date_start": "2025-09-01",
            "date_stop": "2025-09-01",
            "spend": "100.00",
            "purchase_roas": [
                {"action_type": "purchase", "value": "3.45"},
            ],
        }
        result = normalize_insight(raw)

        assert result["purchase_roas"] == 3.45

    def test_insight_with_purchase_roas_as_scalar(self):
        """purchase_roas as a direct float value."""
        raw = {
            "date_start": "2025-09-01",
            "date_stop": "2025-09-01",
            "spend": "100.00",
            "purchase_roas": "2.75",
        }
        result = normalize_insight(raw)

        assert result["purchase_roas"] == 2.75

    def test_insight_empty_actions_yields_none_conversions(self):
        """Empty actions list yields conversions=None."""
        raw = {
            "date_start": "2025-10-01",
            "date_stop": "2025-10-01",
            "spend": "5.00",
            "actions": [],
        }
        result = normalize_insight(raw)

        assert result["conversions"] is None

    def test_insight_conversions_json_preserved_when_list(self):
        """conversions_json field is set when conversions is a list."""
        conversions_data = [
            {"action_type": "purchase", "value": "3"},
        ]
        raw = {
            "date_start": "2025-10-01",
            "date_stop": "2025-10-01",
            "spend": "20.00",
            "conversions": conversions_data,
        }
        result = normalize_insight(raw)

        assert result["conversions_json"] == conversions_data


# ── Test: _safe_float ────────────────────────────────────────────────────────


class TestSafeFloat:
    """Tests for _safe_float helper."""

    def test_safe_float_none_returns_none(self):
        assert _safe_float(None) is None

    def test_safe_float_string_number(self):
        assert _safe_float("3.14") == 3.14

    def test_safe_float_int_input(self):
        assert _safe_float(42) == 42.0

    def test_safe_float_actual_float(self):
        assert _safe_float(2.718) == 2.718

    def test_safe_float_invalid_string_returns_none(self):
        assert _safe_float("not-a-number") is None

    def test_safe_float_empty_string_returns_none(self):
        assert _safe_float("") is None


# ── Test: _safe_int ──────────────────────────────────────────────────────────


class TestSafeInt:
    """Tests for _safe_int helper."""

    def test_safe_int_none_returns_none(self):
        assert _safe_int(None) is None

    def test_safe_int_string_number(self):
        assert _safe_int("100") == 100

    def test_safe_int_float_truncates(self):
        assert _safe_int("3.9") == 3

    def test_safe_int_invalid_string_returns_none(self):
        assert _safe_int("abc") is None


# ── Test: _safe_datetime ─────────────────────────────────────────────────────


class TestSafeDatetime:
    """Tests for _safe_datetime helper."""

    def test_safe_datetime_meta_iso_format(self):
        """Meta's +0000 ISO format parses correctly."""
        result = _safe_datetime("2024-01-15T10:30:00+0000")
        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30

    def test_safe_datetime_with_z_suffix(self):
        """ISO string with Z suffix parses correctly."""
        result = _safe_datetime("2025-03-20T18:45:00Z")
        assert isinstance(result, datetime)
        assert result.year == 2025
        assert result.month == 3

    def test_safe_datetime_none_returns_none(self):
        assert _safe_datetime(None) is None

    def test_safe_datetime_empty_string_returns_none(self):
        assert _safe_datetime("") is None

    def test_safe_datetime_invalid_string_returns_none(self):
        assert _safe_datetime("not-a-date") is None

    def test_safe_datetime_already_datetime_passthrough(self):
        """If input is already a datetime, return it as-is."""
        dt = datetime(2025, 5, 10, 14, 0, 0)
        result = _safe_datetime(dt)
        assert result is dt


# ── Test: _safe_date ─────────────────────────────────────────────────────────


class TestSafeDate:
    """Tests for _safe_date helper."""

    def test_safe_date_valid_string(self):
        result = _safe_date("2025-08-15")
        assert isinstance(result, datetime)
        assert result.year == 2025
        assert result.month == 8
        assert result.day == 15

    def test_safe_date_none_returns_none(self):
        assert _safe_date(None) is None

    def test_safe_date_invalid_format_returns_none(self):
        assert _safe_date("15/08/2025") is None


# ── Test: _extract_conversions ───────────────────────────────────────────────


class TestExtractConversions:
    """Tests for _extract_conversions helper."""

    def test_extract_conversions_none_returns_none(self):
        assert _extract_conversions(None) is None

    def test_extract_conversions_empty_list_returns_none(self):
        assert _extract_conversions([]) is None

    def test_extract_conversions_no_matching_types_returns_none(self):
        """Actions with no purchase/registration types yield None."""
        actions = [
            {"action_type": "link_click", "value": "100"},
            {"action_type": "page_engagement", "value": "50"},
        ]
        assert _extract_conversions(actions) is None

    def test_extract_conversions_sums_matching_types(self):
        """Sums purchase + offsite_conversion + complete_registration."""
        actions = [
            {"action_type": "purchase", "value": "10"},
            {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "5"},
            {"action_type": "complete_registration", "value": "3"},
            {"action_type": "link_click", "value": "999"},
        ]
        assert _extract_conversions(actions) == 18


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
