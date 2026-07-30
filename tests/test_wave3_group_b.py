"""
tests/test_wave3_group_b.py — Wave 3 Group B: _apply_bulk_edit with lists=None.

Verifies that _apply_bulk_edit works correctly when lists=None (no validation)
and when lists is provided (validation is applied).
"""

import sys
import os

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

    def test_category_edit_applies_when_lists_none(self):
        parsed = _row()
        save, reason, notes = _apply_bulk_edit("1 category=Transport", parsed, lists=None)
        assert save is False
        assert reason == "edited"
        assert parsed[0]["category"] == "Transport"

    def test_unknown_category_accepted_when_lists_none(self):
        parsed = _row()
        save, reason, notes = _apply_bulk_edit("1 category=Nonsense", parsed, lists=None)
        assert save is False
        assert reason == "edited"
        assert parsed[0]["category"] == "Nonsense"

    def test_explicit_lists_still_honoured(self):
        parsed = _row()
        save, reason, notes = _apply_bulk_edit(
            "1 category=Health", parsed, lists=SAMPLE_LISTS
        )
        assert reason == "edited"
        assert parsed[0]["category"] == "Health"
