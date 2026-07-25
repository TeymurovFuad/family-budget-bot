"""
tests/test_ai_categorization.py — AI merchant categorization for statement imports.

All tests are offline: the AI provider is mocked, no live calls.
Covers ai_parser.categorize_merchants and bulk_conv._apply_ai_categorization.
"""

import json
from unittest.mock import MagicMock, patch

import ai_parser
from handlers.bulk_conv import _apply_ai_categorization

LISTS = {"categories": ["Groceries", "Transport", "Entertainment", "Other"]}


def _row(desc, category="", **kw):
    return {"description": desc, "category": category,
            "value": 10.0, "currency": "EUR", "type": "Expense", **kw}


class TestCategorizeMerchants:
    def test_maps_merchants_via_one_call(self):
        provider = MagicMock()
        provider.chat.return_value = json.dumps(
            {"Old Tbilisi": "Entertainment", "MetroMart": "Groceries"}
        )
        with patch.object(ai_parser, "get_provider", return_value=provider):
            result = ai_parser.categorize_merchants(
                ["Old Tbilisi", "MetroMart"], LISTS["categories"]
            )
        assert result == {"Old Tbilisi": "Entertainment", "MetroMart": "Groceries"}
        assert provider.chat.call_count == 1

    def test_batches_over_80_merchants(self):
        provider = MagicMock()
        provider.chat.return_value = "{}"
        merchants = [f"Shop {i}" for i in range(85)]
        with patch.object(ai_parser, "get_provider", return_value=provider):
            ai_parser.categorize_merchants(merchants, LISTS["categories"])
        assert provider.chat.call_count == 2

    def test_provider_error_returns_partial_never_raises(self):
        provider = MagicMock()
        provider.chat.side_effect = RuntimeError("api down")
        with patch.object(ai_parser, "get_provider", return_value=provider):
            result = ai_parser.categorize_merchants(["Shop"], LISTS["categories"])
        assert result == {}

    def test_non_object_response_ignored(self):
        provider = MagicMock()
        provider.chat.return_value = '["not", "a", "dict"]'
        with patch.object(ai_parser, "get_provider", return_value=provider):
            result = ai_parser.categorize_merchants(["Shop"], LISTS["categories"])
        assert result == {}

    def test_empty_inputs_no_call(self):
        provider = MagicMock()
        with patch.object(ai_parser, "get_provider", return_value=provider):
            assert ai_parser.categorize_merchants([], LISTS["categories"]) == {}
            assert ai_parser.categorize_merchants(["Shop"], []) == {}
        provider.chat.assert_not_called()

    def test_dynamic_content_stays_out_of_system_prompt(self):
        """System prompt must stay byte-identical across calls (provider cache)."""
        provider = MagicMock()
        provider.chat.return_value = "{}"
        with patch.object(ai_parser, "get_provider", return_value=provider):
            ai_parser.categorize_merchants(["UniqueMerchantXYZ"], LISTS["categories"])
        messages = provider.chat.call_args[0][0]
        assert messages[0]["content"] == ai_parser._CATEGORIZE_SYSTEM_PROMPT
        assert "UniqueMerchantXYZ" not in messages[0]["content"]
        assert "UniqueMerchantXYZ" in messages[1]["content"]


class TestApplyAiCategorization:
    def test_categorizes_empty_and_other_rows(self):
        rows = [_row("Old Tbilisi"), _row("MetroMart", category="Other")]
        with patch.object(ai_parser, "categorize_merchants",
                          return_value={"Old Tbilisi": "Entertainment",
                                        "MetroMart": "Groceries"}) as mock:
            notes = _apply_ai_categorization(rows, LISTS)
        assert rows[0]["category"] == "Entertainment"
        assert rows[0]["ai"] is True
        assert rows[1]["category"] == "Groceries"
        assert len(notes) == 2
        mock.assert_called_once()

    def test_skips_memory_and_already_categorized_rows(self):
        rows = [
            _row("Known Shop", category="Groceries"),
            _row("Mem Shop", category="Other", mem=True),
        ]
        with patch.object(ai_parser, "categorize_merchants", return_value={}) as mock:
            notes = _apply_ai_categorization(rows, LISTS)
        assert notes == []
        mock.assert_not_called()

    def test_unknown_category_from_ai_ignored(self):
        rows = [_row("Shop")]
        with patch.object(ai_parser, "categorize_merchants",
                          return_value={"Shop": "InventedCategory"}):
            notes = _apply_ai_categorization(rows, LISTS)
        assert rows[0]["category"] == ""
        assert "ai" not in rows[0]
        assert notes == []

    def test_ai_answer_other_not_applied(self):
        """'Other' is already the fallback — an AI 'Other' adds no signal."""
        rows = [_row("Shop")]
        with patch.object(ai_parser, "categorize_merchants",
                          return_value={"Shop": "Other"}):
            notes = _apply_ai_categorization(rows, LISTS)
        assert rows[0]["category"] == ""
        assert notes == []

    def test_same_merchant_rows_grouped_one_lookup(self):
        rows = [_row("MetroMart"), _row("MetroMart"), _row("MetroMart")]
        with patch.object(ai_parser, "categorize_merchants",
                          return_value={"MetroMart": "Groceries"}) as mock:
            notes = _apply_ai_categorization(rows, LISTS)
        assert all(r["category"] == "Groceries" for r in rows)
        assert mock.call_args[0][0] == ["MetroMart"]
        assert len(notes) == 1
        assert "3 rows" in notes[0]

    def test_dropped_rows_excluded(self):
        rows = [_row("Shop", dropped=True)]
        with patch.object(ai_parser, "categorize_merchants", return_value={}) as mock:
            _apply_ai_categorization(rows, LISTS)
        mock.assert_not_called()

    def test_no_categories_noop(self):
        rows = [_row("Shop")]
        with patch.object(ai_parser, "categorize_merchants", return_value={}) as mock:
            assert _apply_ai_categorization(rows, {"categories": []}) == []
        mock.assert_not_called()
