"""
test_formatters.py — tests for all functions in formatters.py.

formatters.py imports `get_rate` from data.py. We patch `data.get_rate` where
needed to avoid requiring a real Excel file for these pure-logic tests.
"""

import pytest

# formatters imports data.get_rate at module level; we patch it via monkeypatch
import data as data_module
import formatters
from formatters import (
    format_amount,
    convert,
    format_base_as_currency,
    budget_progress_bar,
    savings_emoji,
    sanitize_description,
)


# ── format_amount ─────────────────────────────────────────────────────────────


class TestFormatAmount:

    def test_integer_amount_base(self):
        assert format_amount(150, "PLN") == "150 PLN"

    def test_amount_with_thousands_separator(self):
        assert format_amount(1234, "EUR") == "1,234 EUR"

    def test_zero_amount(self):
        assert format_amount(0, "PLN") == "0 PLN"

    def test_float_rounded_to_integer(self):
        # format_amount uses :.0f — fractional parts are rounded away
        assert format_amount(99.9, "PLN") == "100 PLN"

    def test_large_amount_has_comma(self):
        result = format_amount(10000, "USD")
        assert "10,000" in result

    def test_default_currency_is_base(self):
        assert format_amount(50) == "50 PLN"


# ── convert ───────────────────────────────────────────────────────────────────


class TestConvert:

    def test_base_to_base_returns_same_value(self, monkeypatch):
        monkeypatch.setattr(data_module, "get_rate", lambda ccy, rates: 1.0)
        assert convert(100.0, "PLN", {}) == 100.0

    def test_eur_with_rate_4_gives_quarter_value(self, monkeypatch):
        monkeypatch.setattr(data_module, "get_rate", lambda ccy, rates: 4.0)
        # 100 PLN / 4.0 rate = 25 EUR
        assert convert(100.0, "EUR", {"EUR": 4.0}) == pytest.approx(25.0)

    def test_unknown_rate_returns_original_amount(self, monkeypatch):
        # get_rate returns 1.0 for unknown currency
        monkeypatch.setattr(data_module, "get_rate", lambda ccy, rates: 1.0)
        assert convert(200.0, "XYZ", {}) == pytest.approx(200.0)

    def test_zero_rate_returns_original_amount(self, monkeypatch):
        # When rate is 0, convert() guards with `if rate` — returns pln_amount
        monkeypatch.setattr(data_module, "get_rate", lambda ccy, rates: 0)
        assert convert(300.0, "BAD", {}) == pytest.approx(300.0)


# ── format_base_as_currency ────────────────────────────────────────────────────


class TestFormatPlnAsCurrency:

    def test_base_to_base_formats_unchanged(self, monkeypatch):
        monkeypatch.setattr(data_module, "get_rate", lambda ccy, rates: 1.0)
        result = format_base_as_currency(500.0, "PLN", {})
        assert result == "500 PLN"

    def test_base_to_eur_converts_and_formats(self, monkeypatch):
        monkeypatch.setattr(data_module, "get_rate", lambda ccy, rates: 4.0)
        # 400 PLN / 4.0 = 100 EUR
        result = format_base_as_currency(400.0, "EUR", {"EUR": 4.0})
        assert result == "100 EUR"


# ── budget_progress_bar ───────────────────────────────────────────────────────


class TestBudgetProgressBar:

    def test_zero_budget_returns_dashes(self):
        result = budget_progress_bar(100, 0)
        assert result == "─" * 10

    def test_zero_budget_custom_width(self):
        result = budget_progress_bar(100, 0, width=5)
        assert result == "─" * 5

    def test_full_bar_when_actual_equals_budget(self):
        result = budget_progress_bar(100, 100)
        # 100% filled = all green or yellow tiles
        assert "⬜" not in result

    def test_over_budget_bar_is_all_red(self):
        result = budget_progress_bar(200, 100)
        # pct=1.0 → clamped to 1.0, colour is 🟨 (pct==1.0 boundary)
        assert "⬜" not in result

    def test_partial_bar_has_empty_squares(self):
        result = budget_progress_bar(50, 100)
        assert "⬜" in result

    def test_empty_bar_when_actual_is_zero(self):
        result = budget_progress_bar(0, 100)
        assert result == "⬜" * 10

    def test_green_colour_below_80_percent(self):
        result = budget_progress_bar(70, 100)  # 70%
        assert "🟩" in result

    def test_yellow_colour_at_90_percent(self):
        result = budget_progress_bar(90, 100)  # 90%
        assert "🟨" in result

    def test_red_colour_over_100_percent(self):
        result = budget_progress_bar(110, 100)  # 110%
        assert "🟥" in result

    def test_custom_width_respected(self):
        result = budget_progress_bar(50, 100, width=6)
        total_tiles = result.count("🟩") + result.count("🟨") + result.count("🟥") + result.count("⬜")
        assert total_tiles == 6


# ── savings_emoji ─────────────────────────────────────────────────────────────


class TestSavingsEmoji:

    def test_rate_above_20_percent_is_rocket(self):
        assert savings_emoji(0.20) == "🚀"
        assert savings_emoji(0.50) == "🚀"

    def test_rate_15_to_19_percent_is_green_heart(self):
        assert savings_emoji(0.15) == "💚"
        assert savings_emoji(0.19) == "💚"

    def test_rate_8_to_14_percent_is_yellow(self):
        assert savings_emoji(0.08) == "🟡"
        assert savings_emoji(0.14) == "🟡"

    def test_rate_0_to_7_percent_is_red(self):
        assert savings_emoji(0.0) == "🔴"
        assert savings_emoji(0.07) == "🔴"

    def test_negative_rate_is_siren(self):
        assert savings_emoji(-0.01) == "🚨"
        assert savings_emoji(-1.0) == "🚨"


# ── sanitize_description ──────────────────────────────────────────────────────


class TestSanitizeDescription:

    def test_normal_text_unchanged(self):
        assert sanitize_description("weekly shop") == "weekly shop"

    def test_strips_leading_and_trailing_whitespace(self):
        assert sanitize_description("  hello  ") == "hello"

    def test_truncates_to_100_chars(self):
        long = "x" * 200
        result = sanitize_description(long)
        assert len(result) == 100

    def test_equals_sign_prefix_gets_apostrophe(self):
        result = sanitize_description("=SUM(A1)")
        assert result.startswith("'")

    def test_plus_sign_prefix_gets_apostrophe(self):
        result = sanitize_description("+1 bonus")
        assert result.startswith("'")

    def test_minus_sign_prefix_gets_apostrophe(self):
        result = sanitize_description("-10% off")
        assert result.startswith("'")

    def test_at_sign_prefix_gets_apostrophe(self):
        result = sanitize_description("@mention")
        assert result.startswith("'")

    def test_empty_string_stays_empty(self):
        assert sanitize_description("") == ""

    def test_safe_first_char_not_prefixed(self):
        result = sanitize_description("A safe description")
        assert result == "A safe description"

    def test_whitespace_only_becomes_empty(self):
        # "   ".strip() == "" — empty string, no injection prefix
        result = sanitize_description("   ")
        assert result == ""
