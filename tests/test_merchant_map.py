"""
tests/test_merchant_map.py — description cleanup + merchant→category memory.

Covers BACKLOG.md "Follow-up PR: merchant memory & description quality":
  1. Deterministic description cleaner (masked PANs, BPID:, /OPT/ blocks,
     country suffixes) shared by all entry paths AND make_dedup_key.
  2. MerchantMap JSON store: lookup / learn / seed round-trips, zero-AI
     quick-add path, bulk preview autofill + learning from preview edits.

asyncio_mode = auto (pytest.ini).
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import merchant_map
from formatters import sanitize_description
from models import Transaction
from validators import clean_merchant_description, make_dedup_key

ALLOWED_UID = 123

SAMPLE_LISTS = {
    "txn_types": ["Expense", "Income", "Savings"],
    "categories": ["Groceries", "Transport", "Health", "Other"],
    "persons": ["Alice", "Bob"],
    "currencies": ["PLN", "USD", "EUR"],
}


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


# ═══════════════════════════════════════════════════════════════════════════
# clean_merchant_description — deterministic regex cleaner
# ═══════════════════════════════════════════════════════════════════════════

class TestCleanMerchantDescription:
    def test_masked_pan_stripped(self):
        assert clean_merchant_description(
            "4111XXXXXXXX1111 SHOP TERMINAL 12 CITY PL"
        ) == "SHOP TERMINAL 12 CITY"

    def test_bpid_and_opt_blocks_stripped(self):
        assert clean_merchant_description(
            "/OPT/X///// BPID:EXAMPLE123 Autopay S.A."
        ) == "Autopay S.A."

    def test_trailing_country_code_stripped(self):
        assert clean_merchant_description("BIEDRONKA 123 WARSZAWA PL") == "BIEDRONKA 123 WARSZAWA"

    def test_already_clean_passes_through(self):
        assert clean_merchant_description("Shell fuel") == "Shell fuel"
        assert clean_merchant_description("Autopay S.A.") == "Autopay S.A."

    def test_star_masked_pan_stripped(self):
        assert clean_merchant_description("Zabka 4111****1111 Krakow") == "Zabka Krakow"

    def test_never_returns_empty_for_nonempty_input(self):
        # If cleaning would erase everything, the original stripped text is kept.
        assert clean_merchant_description("BPID:ONLY123") == "BPID:ONLY123"

    def test_empty_input(self):
        assert clean_merchant_description("") == ""
        assert clean_merchant_description(None) == ""


class TestSanitizeDescription:
    def test_cleans_and_guards_formula_injection(self):
        assert sanitize_description("=SUM(A1)") == "'=SUM(A1)"

    def test_strips_statement_junk(self):
        assert sanitize_description(
            "4111XXXXXXXX1111 SHOP TERMINAL 12 CITY PL"
        ) == "SHOP TERMINAL 12 CITY"


# ═══════════════════════════════════════════════════════════════════════════
# make_dedup_key — consistency with the cleaner (raw vs stored form)
# ═══════════════════════════════════════════════════════════════════════════

class TestDedupKeyCleaningConsistency:
    def test_raw_and_cleaned_descriptions_produce_same_key(self):
        raw = "4111XXXXXXXX1111 SHOP TERMINAL 12 CITY PL"
        assert make_dedup_key("2024-06-15", 50, "PLN", raw) == \
            make_dedup_key("2024-06-15", 50, "PLN", clean_merchant_description(raw))

    def test_excel_guard_quote_does_not_defeat_dedup(self):
        # write_transaction_row prepends ' to =+-@ descriptions; the read-back
        # key must still match the draft's key.
        assert make_dedup_key("2024-06-15", 50, "PLN", "'=weird shop") == \
            make_dedup_key("2024-06-15", 50, "PLN", "=weird shop")


# ═══════════════════════════════════════════════════════════════════════════
# MerchantMap store — round-trips, lookup, learn, seed
# ═══════════════════════════════════════════════════════════════════════════

class TestMerchantMapStore:
    def test_save_load_round_trip(self):
        entry = {"label": "Biedronka", "category": "Groceries", "type": "Expense",
                 "person": "", "is_recurring": False}
        merchant_map.save_merchant_map({"biedronka": entry})
        assert merchant_map.load_merchant_map() == {"biedronka": entry}

    def test_lookup_uses_cleaned_case_folded_key(self):
        entry = {"label": "Biedronka", "category": "Groceries", "type": "Expense",
                 "person": "", "is_recurring": False}
        mapping = {"biedronka 123 warszawa": entry}
        found = merchant_map.lookup(mapping, "4111XXXXXXXX1111 BIEDRONKA 123 WARSZAWA PL")
        assert found == entry

    def test_lookup_miss_returns_none(self):
        assert merchant_map.lookup({}, "unknown shop") is None
        assert merchant_map.lookup({"x": {}}, "") is None

    def test_learn_from_row_persists_mapping(self):
        row = {"description": "Uber trip", "category": "Transport",
               "type": "Expense", "person": "Alice", "is_recurring": "yes"}
        label = merchant_map.learn_from_row(row)
        assert label == "Uber trip"
        entry = merchant_map.lookup(merchant_map.load_merchant_map(), "UBER   TRIP")
        assert entry["category"] == "Transport"
        assert entry["person"] == "Alice"
        assert entry["is_recurring"] is True

    def test_learn_from_row_without_description_is_noop(self):
        assert merchant_map.learn_from_row({"description": "", "category": "Transport"}) is None
        assert merchant_map.load_merchant_map() == {}

    def test_seed_from_master(self, excel_path):
        from excel_ops import _do_append_transaction
        for i in range(3):
            _do_append_transaction(Transaction(
                date=date(2024, 6, 10 + i), value=50.0 + i, currency="PLN",
                transaction_type="Expense", category="Groceries", person="",
                description="BIEDRONKA 123 WARSZAWA PL", is_recurring=False,
            ))
        # A one-off merchant must NOT be seeded.
        _do_append_transaction(Transaction(
            date=date(2024, 6, 20), value=99.0, currency="PLN",
            transaction_type="Expense", category="Health", person="",
            description="Pharmacy", is_recurring=False,
        ))
        seeded = merchant_map.seed_from_master()
        assert "biedronka 123 warszawa" in seeded
        assert seeded["biedronka 123 warszawa"]["category"] == "Groceries"
        assert "pharmacy" not in seeded

    def test_load_seeds_when_file_missing(self, excel_path, tmp_path, monkeypatch):
        monkeypatch.setattr(merchant_map, "MERCHANT_MAP_PATH", tmp_path / "fresh_map.json")
        result = merchant_map.load_merchant_map()
        assert result == {}  # blank workbook → empty map, but file now exists
        assert (tmp_path / "fresh_map.json").exists()


# ═══════════════════════════════════════════════════════════════════════════
# Zero-token quick-add fast path
# ═══════════════════════════════════════════════════════════════════════════

class TestLocalQuickParse:
    def _remember_biedronka(self):
        merchant_map.save_merchant_map({"biedronka": {
            "label": "Biedronka", "category": "Groceries", "type": "Expense",
            "person": "", "is_recurring": False,
        }})

    def test_known_merchant_parses_without_ai(self):
        self._remember_biedronka()
        parsed = merchant_map.try_local_quick_parse("biedronka 45,50")
        assert parsed["value"] == 45.50
        assert parsed["category"] == "Groceries"
        assert parsed["description"] == "Biedronka"
        assert parsed["currency"] == "PLN"

    def test_date_and_currency_tokens(self):
        self._remember_biedronka()
        parsed = merchant_map.try_local_quick_parse("2024-05-24 Biedronka 45 eur")
        assert parsed["date"] == "2024-05-24"
        assert parsed["currency"] == "EUR"

    def test_unknown_merchant_falls_through(self):
        assert merchant_map.try_local_quick_parse("mystery shop 45") is None

    def test_non_transaction_text_falls_through(self):
        assert merchant_map.try_local_quick_parse("hello there") is None

    async def test_handle_quick_add_skips_ai_for_known_merchant(self):
        from handlers.quick_conv import handle_quick_add
        import states
        self._remember_biedronka()
        upd = make_update("biedronka 45")
        ctx = make_ctx()
        ai = MagicMock(side_effect=AssertionError("AI must not be called"))
        with patch("handlers.quick_conv.load_reference_data", return_value=SAMPLE_LISTS), \
             patch("handlers.quick_conv.parse_quick", ai), \
             patch("handlers.quick_conv.load_rates", return_value={"PLN": 1.0}), \
             patch("handlers.quick_conv.get_display_currency", return_value="PLN"):
            result = await handle_quick_add(upd, ctx)
        assert result == states.QUICK_CONFIRM
        ai.assert_not_called()
        assert ctx.user_data["quick_parsed"]["category"] == "Groceries"
        texts = " ".join(str(c.args[0]) for c in upd.message.reply_text.call_args_list)
        assert "🧠" in texts

    async def test_stale_memory_falls_back_to_ai(self):
        from handlers.quick_conv import handle_quick_add
        import states
        merchant_map.save_merchant_map({"biedronka": {
            "label": "Biedronka", "category": "RenamedAway", "type": "Expense",
            "person": "", "is_recurring": False,
        }})
        upd = make_update("biedronka 45")
        ctx = make_ctx()
        ai_parsed = {"value": 45, "currency": "PLN", "category": "Groceries",
                     "description": "Biedronka", "type": "Expense", "person": ""}
        with patch("handlers.quick_conv.load_reference_data", return_value=SAMPLE_LISTS), \
             patch("handlers.quick_conv.parse_quick", return_value=ai_parsed), \
             patch("handlers.quick_conv.load_rates", return_value={"PLN": 1.0}), \
             patch("handlers.quick_conv.get_display_currency", return_value="PLN"):
            result = await handle_quick_add(upd, ctx)
        assert result == states.QUICK_CONFIRM
        assert ctx.user_data["quick_parsed"]["category"] == "Groceries"


# ═══════════════════════════════════════════════════════════════════════════
# Bulk path — cleanup on parse, memory autofill, learning from edits
# ═══════════════════════════════════════════════════════════════════════════

class TestBulkIntegration:
    def test_normalize_parsed_rows_cleans_descriptions(self):
        from handlers.bulk_conv import _normalize_parsed_rows
        rows = [{"date": "2024-06-15", "value": 50, "currency": "PLN",
                 "type": "Expense", "category": "Groceries",
                 "description": "4111XXXXXXXX1111 SHOP TERMINAL 12 CITY PL", "person": ""}]
        rows, corrections = _normalize_parsed_rows(rows, SAMPLE_LISTS)
        assert rows[0]["description"] == "SHOP TERMINAL 12 CITY"
        assert any("description cleaned" in c for c in corrections)

    def test_apply_merchant_memory_overrides_and_marks(self):
        from handlers.bulk_conv import _apply_merchant_memory
        merchant_map.save_merchant_map({"uber trip": {
            "label": "Uber trip", "category": "Transport", "type": "Expense",
            "person": "Alice", "is_recurring": False,
        }})
        rows = [
            {"description": "Uber trip", "category": "Other", "type": "Expense", "person": ""},
            {"description": "Unknown shop", "category": "Other", "type": "Expense", "person": ""},
        ]
        notes = _apply_merchant_memory(rows)
        assert rows[0]["category"] == "Transport"
        assert rows[0]["person"] == "Alice"
        assert rows[0].get("mem") is True
        assert rows[1].get("mem") is None
        assert len(notes) == 1 and "merchant memory" in notes[0]

    def test_apply_merchant_memory_empty_map_is_noop(self):
        from handlers.bulk_conv import _apply_merchant_memory
        rows = [{"description": "Uber trip", "category": "Other"}]
        assert _apply_merchant_memory(rows) == []
        assert "mem" not in rows[0]

    def test_preview_marks_memory_rows(self):
        from handlers.bulk_conv import _format_bulk_preview
        pages = _format_bulk_preview([
            {"date": "2024-06-15", "value": 50, "currency": "PLN",
             "category": "Transport", "description": "Uber trip", "mem": True},
        ])
        assert "🧠" in pages[0]

    def test_bulk_edit_learns_mapping(self):
        from handlers.bulk_conv import _apply_bulk_edit
        rows = [{"date": "2024-06-15", "value": 50, "currency": "PLN",
                 "type": "Expense", "category": "Other",
                 "description": "Uber trip", "person": ""}]
        save, reason, notes = _apply_bulk_edit("1 category=Transport", rows, SAMPLE_LISTS)
        assert reason == "edited"
        entry = merchant_map.lookup(merchant_map.load_merchant_map(), "Uber trip")
        assert entry is not None
        assert entry["category"] == "Transport"
        assert any("remembered" in n for n in notes)

    def test_bulk_edit_description_does_not_learn(self):
        from handlers.bulk_conv import _apply_bulk_edit
        rows = [{"date": "2024-06-15", "value": 50, "currency": "PLN",
                 "type": "Expense", "category": "Other",
                 "description": "Uber trip", "person": ""}]
        _apply_bulk_edit("1 description=Taxi", rows, SAMPLE_LISTS)
        assert merchant_map.load_merchant_map() == {}
