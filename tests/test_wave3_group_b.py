"""
tests/test_wave3_group_b.py — Wave 3 Group B: _apply_bulk_edit lazy-loads reference data.

Verifies that _apply_bulk_edit works correctly when lists=None (the common
call path from bulk_conv message handler) by auto-loading reference data.
"""

import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from handlers.bulk_conv import _apply_bulk_edit

SAMPLE_LISTS = {
    "categories": ["Groceries", "Transport", "Health"],
    "currencies": ["USD", "EUR"],
    "txn_types": ["Expense", "Income", "Savings"],
    "persons": [],
    "months": [],
}

SAMPLE_ROW = {
    "date": "2026-07-01", "value": 50.0, "currency": "USD",
    "type": "Expense", "category": "Groceries", "description": "shop",
    "person": "", "is_recurring": False,
}


def _row():
    return [dict(SAMPLE_ROW)]


class TestApplyBulkEditLazyLoad:
    def test_save_command_works_without_lists(self):
        save, reason, notes = _apply_bulk_edit("save", _row(), lists=None)
        assert save is True

    def test_category_edit_validates_when_lists_none(self):
        with patch("data.load_reference_data", return_value=SAMPLE_LISTS):
            save, reason, notes = _apply_bulk_edit("1 category=Transport", _row(), lists=None)
        assert save is False
        assert reason == "edited"
        assert _row()[0]["category"] == "Groceries"  # original unchanged

    def test_category_edit_rejects_unknown_when_lists_none(self):
        with patch("data.load_reference_data", return_value=SAMPLE_LISTS):
            save, reason, notes = _apply_bulk_edit("1 category=Nonsense", _row(), lists=None)
        assert save is False
        assert "Unknown category" in reason

    def test_explicit_lists_still_honoured(self):
        parsed = _row()
        save, reason, notes = _apply_bulk_edit(
            "1 category=Health", parsed, lists=SAMPLE_LISTS
        )
        assert reason == "edited"
        assert parsed[0]["category"] == "Health"
