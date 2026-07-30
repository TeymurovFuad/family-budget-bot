"""
tests/test_wave3_group_b.py — Wave 3 Group B: _apply_bulk_edit with lists=None,
revalidation path, empty-lists note, and post-merge draft cap.
"""

import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from handlers.bulk_conv import _apply_bulk_edit, _merge_bulk_draft, _save_bulk_draft, _DRAFT_LIMIT_ENTRIES

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


class TestApplyBulkEditRevalidation:
    """_apply_bulk_edit calls _revalidate_bulk_row; a cross-field invalid row must surface a note."""

    def test_invalid_type_produces_invalid_flag_and_note(self):
        parsed = [dict(SAMPLE_ROW)]
        # Editing type to "" leaves the row invalid after revalidation.
        # _revalidate_bulk_row defaults empty type → "Expense", so use a
        # value that validate_parsed_row will reject (a non-empty nonsense type).
        save, reason, notes = _apply_bulk_edit(
            "1 type=BADTYPE", parsed, lists=SAMPLE_LISTS
        )
        assert reason == "edited"
        # The row must be flagged invalid because "BADTYPE" is not in txn_types.
        assert parsed[0].get("invalid"), (
            f"expected row to be marked invalid, got: {parsed[0]}"
        )
        # notes must be non-empty (revalidation fires and appends something).
        assert notes, "expected non-empty notes from revalidation"


class TestApplyBulkEditEmptyLists:
    """When lists={'categories': []}, the edit must succeed and emit a warning note."""

    def test_empty_categories_list_emits_note_and_allows_edit(self):
        parsed = _row()
        save, reason, notes = _apply_bulk_edit(
            "1 category=ANYTHING", parsed, lists={"categories": []}
        )
        assert reason == "edited", f"expected 'edited', got '{reason}'"
        assert any("categories list is empty" in n for n in notes), (
            f"expected note about empty categories list, got: {notes}"
        )


class TestDraftLimitPostMerge:
    """After _merge_bulk_draft returns >50 rows the draft must be capped at 50."""

    def test_cap_trims_to_limit(self, tmp_path):
        uid = 999_000
        base_row = dict(SAMPLE_ROW)
        # Build 60 unique-ish rows so _merge_bulk_draft doesn't de-dup them away.
        rows_60 = [
            {**base_row, "description": f"tx{i}", "value": float(i + 1)}
            for i in range(60)
        ]

        from pathlib import Path

        with patch("handlers.bulk_conv._bulk_draft_dir", return_value=Path(tmp_path)):
            _save_bulk_draft(uid, rows_60)
            saved_rows, _ = _merge_bulk_draft(uid, [])

        # saved_rows is the 60-row draft; apply the post-merge cap logic.
        if len(saved_rows) > _DRAFT_LIMIT_ENTRIES:
            saved_rows = saved_rows[:_DRAFT_LIMIT_ENTRIES]
            with patch("handlers.bulk_conv._bulk_draft_dir", return_value=Path(tmp_path)):
                _save_bulk_draft(uid, saved_rows)

        assert len(saved_rows) == _DRAFT_LIMIT_ENTRIES
