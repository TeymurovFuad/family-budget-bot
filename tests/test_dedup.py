"""
tests/test_dedup.py — statement dedup against MasterData + within-draft dedup.

Covers BACKLOG.md "Follow-up PR: dedup":
  1. Statement dedup against MasterData (sha1 key, date-range read, `N keep`
     override, user-visible skip report).
  2. Within-draft dedup at merge time (_merge_bulk_draft).

asyncio_mode = auto (pytest.ini) — no @pytest.mark.asyncio needed.
"""

import json
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from validators import make_dedup_key

# conftest.py sets ALLOWED_TELEGRAM_IDS="123" before any project import, and
# handlers are decorated with @auth at *definition* time — patching config.auth
# here would be a no-op if handlers.bulk_conv was already imported elsewhere in
# the suite. Use the allowed ID for every handler-level test in this file.
ALLOWED_UID = 123


# ── helpers (mirrors tests/test_handlers_full.py) ────────────────────────────

def make_update(text="hello", user_id=ALLOWED_UID):
    upd = MagicMock()
    upd.message.text = text
    upd.message.reply_text = AsyncMock()
    upd.effective_user.id = user_id
    upd.message.photo = None
    upd.message.document = None
    return upd


def make_ctx():
    ctx = MagicMock()
    ctx.user_data = {}
    ctx.bot = MagicMock()
    return ctx


SAMPLE_LISTS = {
    "txn_types": ["Expense", "Income", "Savings"],
    "categories": ["Groceries", "Transport", "Health"],
    "persons": ["Alice", "Bob"],
    "currencies": ["PLN", "USD", "EUR"],
}


# ═══════════════════════════════════════════════════════════════════════════
# make_dedup_key — key stability & normalization
# ═══════════════════════════════════════════════════════════════════════════

class TestMakeDedupKey:
    def test_same_inputs_produce_same_key(self):
        k1 = make_dedup_key("2024-06-15", 50.0, "PLN", "Groceries shop")
        k2 = make_dedup_key("2024-06-15", 50.0, "PLN", "Groceries shop")
        assert k1 == k2

    def test_whitespace_differences_do_not_defeat_dedup(self):
        k1 = make_dedup_key("2024-06-15", 50.0, "PLN", "Groceries   shop")
        k2 = make_dedup_key("2024-06-15", 50.0, "PLN", "Groceries shop")
        assert k1 == k2

    def test_case_differences_do_not_defeat_dedup(self):
        k1 = make_dedup_key("2024-06-15", 50.0, "PLN", "GROCERIES SHOP")
        k2 = make_dedup_key("2024-06-15", 50.0, "PLN", "groceries shop")
        assert k1 == k2

    def test_leading_trailing_whitespace_ignored(self):
        k1 = make_dedup_key("2024-06-15", 50.0, "PLN", "  Groceries shop  ")
        k2 = make_dedup_key("2024-06-15", 50.0, "PLN", "Groceries shop")
        assert k1 == k2

    def test_different_value_changes_key(self):
        k1 = make_dedup_key("2024-06-15", 50.0, "PLN", "Groceries shop")
        k2 = make_dedup_key("2024-06-15", 50.01, "PLN", "Groceries shop")
        assert k1 != k2

    def test_different_currency_changes_key(self):
        k1 = make_dedup_key("2024-06-15", 50.0, "PLN", "Groceries shop")
        k2 = make_dedup_key("2024-06-15", 50.0, "USD", "Groceries shop")
        assert k1 != k2

    def test_different_date_changes_key(self):
        k1 = make_dedup_key("2024-06-15", 50.0, "PLN", "Groceries shop")
        k2 = make_dedup_key("2024-06-16", 50.0, "PLN", "Groceries shop")
        assert k1 != k2

    def test_string_amount_matches_numeric_amount(self):
        k1 = make_dedup_key("2024-06-15", "50.00", "PLN", "Groceries shop")
        k2 = make_dedup_key("2024-06-15", 50.0, "PLN", "Groceries shop")
        assert k1 == k2

    def test_missing_currency_defaults_to_pln(self):
        k1 = make_dedup_key("2024-06-15", 50.0, "", "Groceries shop")
        k2 = make_dedup_key("2024-06-15", 50.0, "PLN", "Groceries shop")
        assert k1 == k2


# ═══════════════════════════════════════════════════════════════════════════
# _merge_bulk_draft — within-draft / within-batch dedup
# ═══════════════════════════════════════════════════════════════════════════

class TestMergeBulkDraftDedup:
    def test_uploading_same_photo_twice_does_not_duplicate_rows(self):
        from handlers.bulk_conv import _merge_bulk_draft, _save_bulk_draft, _delete_bulk_draft

        with tempfile.TemporaryDirectory() as tmpdir:
            draft_dir = Path(tmpdir) / "bulk_drafts"
            draft_dir.mkdir()
            with patch("handlers.bulk_conv._bulk_draft_dir", return_value=draft_dir):
                rows = [
                    {"date": "2024-06-15", "value": 50, "currency": "PLN",
                     "category": "Groceries", "description": "shop", "person": ""},
                    {"date": "2024-06-16", "value": 20, "currency": "PLN",
                     "category": "Transport", "description": "train", "person": ""},
                ]
                merged, skipped = _merge_bulk_draft(11111, rows)
                assert len(merged) == 2
                assert skipped == 0

                # Same photo uploaded again -> identical rows re-parsed.
                merged2, skipped2 = _merge_bulk_draft(11111, [dict(r) for r in rows])
                assert len(merged2) == 2, "duplicate rows from the second upload must be skipped"
                assert skipped2 == 2

    def test_within_batch_duplicates_are_skipped(self):
        from handlers.bulk_conv import _merge_bulk_draft

        with tempfile.TemporaryDirectory() as tmpdir:
            draft_dir = Path(tmpdir) / "bulk_drafts"
            draft_dir.mkdir()
            with patch("handlers.bulk_conv._bulk_draft_dir", return_value=draft_dir):
                row = {"date": "2024-06-15", "value": 50, "currency": "PLN",
                       "category": "Groceries", "description": "shop", "person": ""}
                merged, skipped = _merge_bulk_draft(22222, [dict(row), dict(row)])
                assert len(merged) == 1
                assert skipped == 1

    def test_distinct_rows_all_kept(self):
        from handlers.bulk_conv import _merge_bulk_draft

        with tempfile.TemporaryDirectory() as tmpdir:
            draft_dir = Path(tmpdir) / "bulk_drafts"
            draft_dir.mkdir()
            with patch("handlers.bulk_conv._bulk_draft_dir", return_value=draft_dir):
                rows = [
                    {"date": "2024-06-15", "value": 50, "currency": "PLN",
                     "category": "Groceries", "description": "shop A", "person": ""},
                    {"date": "2024-06-15", "value": 50, "currency": "PLN",
                     "category": "Groceries", "description": "shop B", "person": ""},
                ]
                merged, skipped = _merge_bulk_draft(33333, rows)
                assert len(merged) == 2
                assert skipped == 0


# ═══════════════════════════════════════════════════════════════════════════
# load_dedup_keys — MasterData read, schema-driven, date-range boundaries
# ═══════════════════════════════════════════════════════════════════════════

class TestLoadDedupKeys:
    def _seed_master_data(self, excel_path, rows):
        """Write rows directly into MasterData via the shared write path."""
        from openpyxl import load_workbook
        from excel_schema import find_next_data_row, lists_currency_range, write_transaction_row
        from file_storage import atomic_save

        wb = load_workbook(excel_path)
        ws = wb["MasterData"]
        lu_range = lists_currency_range(wb)
        for row in rows:
            r = find_next_data_row(ws)
            write_transaction_row(ws, r, row, lu_range)
        atomic_save(wb, excel_path)

    def test_finds_key_for_row_in_range(self, excel_path):
        from data import load_dedup_keys

        self._seed_master_data(excel_path, [
            {"date": date(2024, 6, 15), "value": 50.0, "currency": "PLN",
             "type": "Expense", "category": "Groceries", "description": "shop", "person": ""},
        ])
        keys = load_dedup_keys(date(2024, 6, 1), date(2024, 6, 30))
        expected = make_dedup_key("2024-06-15", 50.0, "PLN", "shop")
        assert expected in keys

    def test_row_outside_range_excluded(self, excel_path):
        from data import load_dedup_keys

        self._seed_master_data(excel_path, [
            {"date": date(2024, 6, 15), "value": 50.0, "currency": "PLN",
             "type": "Expense", "category": "Groceries", "description": "shop", "person": ""},
        ])
        keys = load_dedup_keys(date(2024, 7, 1), date(2024, 7, 31))
        expected = make_dedup_key("2024-06-15", 50.0, "PLN", "shop")
        assert expected not in keys

    def test_range_boundaries_are_inclusive(self, excel_path):
        from data import load_dedup_keys

        self._seed_master_data(excel_path, [
            {"date": date(2024, 6, 1), "value": 10.0, "currency": "PLN",
             "type": "Expense", "category": "Groceries", "description": "first", "person": ""},
            {"date": date(2024, 6, 30), "value": 20.0, "currency": "PLN",
             "type": "Expense", "category": "Groceries", "description": "last", "person": ""},
        ])
        keys = load_dedup_keys(date(2024, 6, 1), date(2024, 6, 30))
        assert make_dedup_key("2024-06-01", 10.0, "PLN", "first") in keys
        assert make_dedup_key("2024-06-30", 20.0, "PLN", "last") in keys

    def test_no_range_returns_all_keys(self, excel_path):
        from data import load_dedup_keys

        self._seed_master_data(excel_path, [
            {"date": date(2024, 1, 1), "value": 10.0, "currency": "PLN",
             "type": "Expense", "category": "Groceries", "description": "old", "person": ""},
        ])
        keys = load_dedup_keys()
        assert make_dedup_key("2024-01-01", 10.0, "PLN", "old") in keys

    def test_read_failure_returns_empty_set_never_raises(self, monkeypatch):
        from data import load_dedup_keys
        import file_storage

        monkeypatch.setattr(file_storage, "LOCAL_XLSX_PATH", Path("Z:/does/not/exist.xlsx"))
        keys = load_dedup_keys(date(2024, 1, 1), date(2024, 1, 31))
        assert keys == set()


# ═══════════════════════════════════════════════════════════════════════════
# _flag_master_duplicates + `N keep` override grammar
# ═══════════════════════════════════════════════════════════════════════════

class TestFlagMasterDuplicatesAndKeepOverride:
    def test_flags_row_matching_existing_key(self):
        from handlers.bulk_conv import _flag_master_duplicates

        rows = [{"date": "2024-06-15", "value": 50, "currency": "PLN",
                 "description": "shop", "person": ""}]
        existing = {make_dedup_key("2024-06-15", 50, "PLN", "shop")}
        with patch("handlers.bulk_conv.load_dedup_keys", return_value=existing):
            flagged = _flag_master_duplicates(rows)
        assert flagged == 1
        assert rows[0]["dup"] is True

    def test_non_matching_row_not_flagged(self):
        from handlers.bulk_conv import _flag_master_duplicates

        rows = [{"date": "2024-06-15", "value": 50, "currency": "PLN",
                 "description": "shop", "person": ""}]
        with patch("handlers.bulk_conv.load_dedup_keys", return_value=set()):
            flagged = _flag_master_duplicates(rows)
        assert flagged == 0
        assert "dup" not in rows[0]

    def test_dup_keep_row_is_not_reflagged(self):
        from handlers.bulk_conv import _flag_master_duplicates

        rows = [{"date": "2024-06-15", "value": 50, "currency": "PLN",
                 "description": "shop", "person": "", "dup_keep": True}]
        existing = {make_dedup_key("2024-06-15", 50, "PLN", "shop")}
        with patch("handlers.bulk_conv.load_dedup_keys", return_value=existing):
            flagged = _flag_master_duplicates(rows)
        assert flagged == 0
        assert "dup" not in rows[0]

    def test_keep_override_via_apply_bulk_edit(self):
        from handlers.bulk_conv import _apply_bulk_edit

        rows = [{"date": "2024-06-15", "value": 50, "currency": "PLN",
                 "description": "shop", "person": "", "dup": True}]
        action, reason, notes = _apply_bulk_edit("1 keep", rows)
        assert action is False
        assert reason == "edited"
        assert rows[0]["dup_keep"] is True
        assert "dup" not in rows[0]
        assert notes and "row 1" in notes[0]

    def test_keep_override_rejected_when_row_not_flagged(self):
        from handlers.bulk_conv import _apply_bulk_edit

        rows = [{"date": "2024-06-15", "value": 50, "currency": "PLN",
                 "description": "shop", "person": ""}]
        action, reason, notes = _apply_bulk_edit("1 keep", rows)
        assert reason == "invalid"

    def test_keep_override_out_of_range_invalid(self):
        from handlers.bulk_conv import _apply_bulk_edit

        rows = [{"date": "2024-06-15", "value": 50, "currency": "PLN",
                 "description": "shop", "person": "", "dup": True}]
        action, reason, notes = _apply_bulk_edit("5 keep", rows)
        assert reason == "invalid"


# ═══════════════════════════════════════════════════════════════════════════
# Preview marker
# ═══════════════════════════════════════════════════════════════════════════

class TestPreviewShowsDupMarker:
    def test_flagged_row_shows_marker(self):
        from handlers.bulk_conv import _format_bulk_preview

        rows = [{"date": "2024-06-15", "value": 50, "currency": "PLN",
                 "category": "Groceries", "description": "shop", "person": "", "dup": True}]
        pages = _format_bulk_preview(rows)
        assert "already imported" in pages[0]
        assert "1 keep" in pages[0]

    def test_kept_row_does_not_show_marker(self):
        from handlers.bulk_conv import _format_bulk_preview

        rows = [{"date": "2024-06-15", "value": 50, "currency": "PLN",
                 "category": "Groceries", "description": "shop", "person": "",
                 "dup_keep": True}]
        pages = _format_bulk_preview(rows)
        assert "already imported" not in pages[0]


# ═══════════════════════════════════════════════════════════════════════════
# End-to-end: bulk_receive reports merge + MasterData dup skips
# ═══════════════════════════════════════════════════════════════════════════

class TestBulkReceiveDedupReporting:
    async def test_merge_time_duplicate_reported_to_user(self):
        from handlers.bulk_conv import bulk_receive
        import states

        upd = make_update("some text")
        ctx = make_ctx()
        with tempfile.TemporaryDirectory() as tmpdir:
            draft_dir = Path(tmpdir) / "bulk_drafts"
            draft_dir.mkdir()
            draft_path = draft_dir / f"{ALLOWED_UID}.json"
            existing_row = {"date": "2024-06-15", "value": 50, "currency": "PLN",
                             "category": "Groceries", "description": "shop", "person": "",
                             "status": "pending"}
            draft_path.write_text(json.dumps([existing_row]))

            with patch("handlers.bulk_conv._bulk_draft_dir", return_value=draft_dir), \
                 patch("handlers.bulk_conv.load_reference_data", return_value=SAMPLE_LISTS), \
                 patch("handlers.bulk_conv.parse_text", return_value=[dict(existing_row)]), \
                 patch("handlers.bulk_conv.load_dedup_keys", return_value=set()):
                result = await bulk_receive(upd, ctx)

            assert result == states.BULK_CONFIRM
            all_texts = " ".join(
                c.args[0] for c in upd.message.reply_text.call_args_list if c.args
            )
            assert "↺" in all_texts
            assert "already imported" in all_texts

    async def test_master_data_duplicate_reported_to_user(self):
        from handlers.bulk_conv import bulk_receive
        import states

        upd = make_update("some text")
        ctx = make_ctx()
        with tempfile.TemporaryDirectory() as tmpdir:
            draft_dir = Path(tmpdir) / "bulk_drafts"
            draft_dir.mkdir()
            parsed = [{"date": "2024-06-15", "value": 50, "currency": "PLN",
                       "category": "Groceries", "description": "shop", "person": ""}]
            existing_keys = {make_dedup_key("2024-06-15", 50, "PLN", "shop")}

            with patch("handlers.bulk_conv._bulk_draft_dir", return_value=draft_dir), \
                 patch("handlers.bulk_conv.load_reference_data", return_value=SAMPLE_LISTS), \
                 patch("handlers.bulk_conv.parse_text", return_value=parsed), \
                 patch("handlers.bulk_conv.load_dedup_keys", return_value=existing_keys):
                result = await bulk_receive(upd, ctx)

            assert result == states.BULK_CONFIRM
            all_texts = " ".join(
                c.args[0] for c in upd.message.reply_text.call_args_list if c.args
            )
            assert "↺" in all_texts
            assert "already imported" in all_texts
            assert "keep" in all_texts


# ═══════════════════════════════════════════════════════════════════════════
# End-to-end: bulk_confirm skips duplicates at save time and reports them
# ═══════════════════════════════════════════════════════════════════════════

class TestBulkConfirmSkipsDuplicatesAtSave:
    async def test_master_data_dup_skipped_and_reported(self):
        from handlers.bulk_conv import bulk_confirm
        from telegram.ext import ConversationHandler

        ctx = make_ctx()
        ctx.user_data["bulk_parsed"] = [
            {"date": "2024-06-15", "value": 50, "currency": "PLN",
             "type": "Expense", "category": "Groceries", "description": "shop", "person": ""},
            {"date": "2024-06-16", "value": 20, "currency": "PLN",
             "type": "Expense", "category": "Transport", "description": "train", "person": ""},
        ]
        upd = make_update("Yes")
        existing_keys = {make_dedup_key("2024-06-15", 50, "PLN", "shop")}

        with patch("handlers.bulk_conv.load_dedup_keys", return_value=existing_keys), \
             patch("handlers.bulk_conv.async_append_batch", AsyncMock()) as mock_batch:
            result = await bulk_confirm(upd, ctx)

        assert result == ConversationHandler.END
        saved_txns = mock_batch.call_args.args[0]
        assert len(saved_txns) == 1
        assert saved_txns[0].description == "train"

        sent = upd.message.reply_text.call_args.args[0]
        assert "Saved 1" in sent
        assert "↺" in sent
        assert "already imported" in sent
        assert "#1" in sent

    async def test_dup_keep_row_is_saved_despite_flag(self):
        from handlers.bulk_conv import bulk_confirm
        from telegram.ext import ConversationHandler

        ctx = make_ctx()
        ctx.user_data["bulk_parsed"] = [
            {"date": "2024-06-15", "value": 50, "currency": "PLN",
             "type": "Expense", "category": "Groceries", "description": "shop", "person": "",
             "dup_keep": True},
        ]
        upd = make_update("Yes")
        existing_keys = {make_dedup_key("2024-06-15", 50, "PLN", "shop")}

        with patch("handlers.bulk_conv.load_dedup_keys", return_value=existing_keys), \
             patch("handlers.bulk_conv.async_append_batch", AsyncMock()) as mock_batch:
            result = await bulk_confirm(upd, ctx)

        assert result == ConversationHandler.END
        saved_txns = mock_batch.call_args.args[0]
        assert len(saved_txns) == 1

        sent = upd.message.reply_text.call_args.args[0]
        assert "Saved 1" in sent
        assert "↺" not in sent

    async def test_within_batch_dup_skipped_at_save(self):
        """A row surviving into bulk_parsed twice (e.g. manual edit made two rows
        identical) is only saved once; the second is reported as skipped."""
        from handlers.bulk_conv import bulk_confirm
        from telegram.ext import ConversationHandler

        ctx = make_ctx()
        row = {"date": "2024-06-15", "value": 50, "currency": "PLN",
               "type": "Expense", "category": "Groceries", "description": "shop", "person": ""}
        ctx.user_data["bulk_parsed"] = [dict(row), dict(row)]
        upd = make_update("Yes")

        with patch("handlers.bulk_conv.load_dedup_keys", return_value=set()), \
             patch("handlers.bulk_conv.async_append_batch", AsyncMock()) as mock_batch:
            result = await bulk_confirm(upd, ctx)

        assert result == ConversationHandler.END
        saved_txns = mock_batch.call_args.args[0]
        assert len(saved_txns) == 1

        sent = upd.message.reply_text.call_args.args[0]
        assert "Saved 1" in sent
        assert "↺" in sent
