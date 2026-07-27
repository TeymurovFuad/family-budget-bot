"""
tests/test_wave2_group_c.py — Wave 2 Group C conversation improvements.

Covers:
- quick_conv local regex fast-path (zero-AI parsing)
- quick-add one-tap category recovery
- recurring detection proposal (merchant_map.detect_recurring + confirm cards)
- /add two-tap defaults and edit-from-confirm
- edit_conv dynamic currency keyboard
- cycles.salary_mask blank-keyword guard
"""

import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("ALLOWED_TELEGRAM_IDS", "")

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import unittest.mock as _mock
_auth_patcher = _mock.patch("config.auth", lambda f: f)
_auth_patcher.start()
_auth_write_patcher = _mock.patch("config.auth_write", lambda f: f)
_auth_write_patcher.start()

import importlib as _importlib
# Reload only the handler modules under test — reloading everything (e.g.
# handlers.menu) would break identity assertions in other test files.
for _mod_name in ("handlers.add_conv", "handlers.quick_conv", "handlers.edit_conv"):
    if _mod_name in sys.modules:
        _importlib.reload(sys.modules[_mod_name])

import states
import cycles
import merchant_map
from handlers.quick_conv import (
    handle_quick_add, quick_confirm, _local_fast_parse, RECURRING_YES_BUTTON,
)
from handlers import edit_conv
from handlers.add_conv import cmd_add, add_value, add_category, add_confirm
from telegram.ext import ConversationHandler

SAMPLE_RATES = {"PLN": 1.0, "USD": 4.0, "EUR": 4.5}
SAMPLE_LISTS = {
    "txn_types": ["Expense", "Income", "Savings"],
    "categories": ["Groceries", "Transport", "Health"],
    "persons": [],
}


def make_update(text="hello", user_id=123):
    upd = MagicMock()
    upd.message.text = text
    upd.message.reply_text = AsyncMock()
    upd.effective_user.id = user_id
    return upd


def make_ctx():
    ctx = MagicMock()
    ctx.user_data = {}
    return ctx


# ── Item 1: salary_mask blank-keyword guard ───────────────────────────────────

class TestSalaryMaskBlankKeyword:
    DF = pd.DataFrame({
        "Type": ["Income", "Income", "Expense"],
        "Category": ["", "Freelance", ""],
        "Description": ["transfer", "", "shop"],
    })

    def test_blank_salary_category_matches_nothing(self):
        # A blank SALARY_CATEGORY must never match every Income row.
        with patch("cycles.cycle_detect_keywords", return_value=["", "  "]):
            mask = cycles.salary_mask(self.DF)
        assert not mask.any()

    def test_no_keywords_matches_nothing(self):
        with patch("cycles.cycle_detect_keywords", return_value=[]):
            mask = cycles.salary_mask(self.DF)
        assert not mask.any()

    def test_real_keyword_still_matches(self):
        with patch("cycles.cycle_detect_keywords", return_value=["", "transfer"]):
            mask = cycles.salary_mask(self.DF)
        assert mask.tolist() == [True, False, False]


# ── Item 2: edit_conv dynamic currency keyboard ───────────────────────────────

class TestEditCurrencyKeyboard:
    @pytest.mark.parametrize("n_currencies", [2, 5, 9])
    async def test_keyboard_covers_all_currencies(self, n_currencies):
        rates = {f"CC{i}": 1.0 for i in range(n_currencies)}
        ctx = make_ctx()
        ctx.user_data["edit_txn"] = {"Currency": "PLN"}
        upd = make_update("Currency")
        with patch("handlers.edit_conv.load_rates", return_value=rates):
            result = await edit_conv.edit_field(upd, ctx)
        assert result == states.EDIT_VALUE
        kb = upd.message.reply_text.call_args.kwargs["reply_markup"].keyboard
        buttons = [b.text for row in kb for b in row]
        assert set(buttons) == set(rates) | {"Cancel"}
        # 2 per row (last currency row may be shorter), Cancel on its own row
        assert all(len(row) <= 2 for row in kb)


# ── Item 5: quick-add local fast path ─────────────────────────────────────────

class TestLocalFastParse:
    def test_category_word_and_amount_fully_resolves(self):
        with patch("handlers.quick_conv.load_rates", return_value=SAMPLE_RATES):
            row, needs_cat = _local_fast_parse("groceries 89", SAMPLE_LISTS)
        assert not needs_cat
        assert row["value"] == 89.0
        assert row["category"] == "Groceries"
        assert row["currency"] == "PLN"

    def test_bare_amount_needs_category(self):
        with patch("handlers.quick_conv.load_rates", return_value=SAMPLE_RATES):
            row, needs_cat = _local_fast_parse("89.50", SAMPLE_LISTS)
        assert needs_cat
        assert row["value"] == 89.5

    def test_currency_suffix_recognized(self):
        with patch("handlers.quick_conv.load_rates", return_value=SAMPLE_RATES):
            row, _ = _local_fast_parse("transport 45 eur", SAMPLE_LISTS)
        assert row["currency"] == "EUR"
        assert row["category"] == "Transport"

    def test_unknown_merchant_falls_to_ai(self):
        with patch("handlers.quick_conv.load_rates", return_value=SAMPLE_RATES):
            row, needs_cat = _local_fast_parse("lunch 45", SAMPLE_LISTS)
        assert row is None and not needs_cat

    def test_non_currency_suffix_falls_to_ai(self):
        with patch("handlers.quick_conv.load_rates", return_value=SAMPLE_RATES):
            row, _ = _local_fast_parse("groceries 45 abc", SAMPLE_LISTS)
        assert row is None

    async def test_fast_path_skips_ai_entirely(self):
        upd = make_update("groceries 89")
        ctx = make_ctx()
        with patch("handlers.quick_conv.merchant_map") as mock_mm, \
             patch("handlers.quick_conv.load_reference_data", return_value=SAMPLE_LISTS), \
             patch("handlers.quick_conv.load_rates", return_value=SAMPLE_RATES), \
             patch("handlers.quick_conv.get_display_currency", return_value="PLN"), \
             patch("handlers.quick_conv.format_base_as_currency", return_value="89.00 PLN"), \
             patch("handlers.quick_conv.parse_quick") as mock_ai:
            mock_mm.try_local_quick_parse.return_value = None
            mock_mm.detect_recurring.return_value = False
            result = await handle_quick_add(upd, ctx)
        assert result == states.QUICK_CONFIRM
        mock_ai.assert_not_called()
        assert ctx.user_data["quick_parsed"]["category"] == "Groceries"

    async def test_bare_amount_offers_category_keyboard_without_ai(self):
        upd = make_update("89.50")
        ctx = make_ctx()
        with patch("handlers.quick_conv.merchant_map") as mock_mm, \
             patch("handlers.quick_conv.load_reference_data", return_value=SAMPLE_LISTS), \
             patch("handlers.quick_conv.load_rates", return_value=SAMPLE_RATES), \
             patch("handlers.quick_conv.parse_quick") as mock_ai:
            mock_mm.try_local_quick_parse.return_value = None
            result = await handle_quick_add(upd, ctx)
        assert result == states.QUICK_CONFIRM
        mock_ai.assert_not_called()
        assert ctx.user_data["quick_fix"]["value"] == 89.5


# ── Item 4: quick-add one-tap category recovery ───────────────────────────────

class TestQuickAddRecovery:
    async def test_category_pick_completes_the_row(self):
        ctx = make_ctx()
        ctx.user_data["quick_fix"] = {
            "date": "", "value": 89.5, "currency": "PLN", "type": "Expense",
            "category": "", "description": "", "person": "", "is_recurring": False,
        }
        upd = make_update("Groceries")
        with patch("handlers.quick_conv.load_reference_data", return_value=SAMPLE_LISTS), \
             patch("handlers.quick_conv.load_rates", return_value=SAMPLE_RATES), \
             patch("handlers.quick_conv.get_display_currency", return_value="PLN"), \
             patch("handlers.quick_conv.format_base_as_currency", return_value="89.50 PLN"), \
             patch("handlers.quick_conv.merchant_map") as mock_mm:
            mock_mm.detect_recurring.return_value = False
            result = await quick_confirm(upd, ctx)
        assert result == states.QUICK_CONFIRM
        assert ctx.user_data["quick_parsed"]["category"] == "Groceries"
        assert "quick_fix" not in ctx.user_data

    async def test_invalid_category_pick_reprompts(self):
        ctx = make_ctx()
        ctx.user_data["quick_fix"] = {
            "date": "", "value": 89.5, "currency": "PLN", "type": "Expense",
            "category": "", "description": "", "person": "", "is_recurring": False,
        }
        upd = make_update("NotACategory")
        with patch("handlers.quick_conv.load_reference_data", return_value=SAMPLE_LISTS):
            result = await quick_confirm(upd, ctx)
        assert result == states.QUICK_CONFIRM
        assert "quick_fix" in ctx.user_data  # still waiting for a valid pick

    async def test_cancel_during_recovery_ends(self):
        ctx = make_ctx()
        ctx.user_data["quick_fix"] = {"value": 89.5}
        upd = make_update("Cancel")
        result = await quick_confirm(upd, ctx)
        assert result == ConversationHandler.END

    async def test_no_parseable_amount_still_suggests_add(self):
        # Catastrophic failure (no amount) → fall back to the /add suggestion.
        upd = make_update("weird message")
        ctx = make_ctx()
        parsed = {"value": "??", "currency": "PLN", "category": "Groceries",
                  "description": "x", "type": "Expense", "person": ""}
        with patch("handlers.quick_conv.merchant_map") as mock_mm, \
             patch("handlers.quick_conv.load_reference_data", return_value=SAMPLE_LISTS), \
             patch("handlers.quick_conv.parse_quick", return_value=parsed):
            mock_mm.try_local_quick_parse.return_value = None
            result = await handle_quick_add(upd, ctx)
        assert result is None
        sent = upd.message.reply_text.call_args.args[0]
        assert "/add" in sent


# ── Item 6: recurring detection from history ──────────────────────────────────

def _master_df(rows):
    return pd.DataFrame(rows, columns=["Date", "Description", "Value"])


class TestDetectRecurring:
    def _detect(self, df, description="Netflix", value=45.0):
        with patch("merchant_map.pd.read_excel", return_value=df), \
             patch("merchant_map.get_excel_path_for_reading", return_value="fake.xlsx"):
            return merchant_map.detect_recurring(description, value)

    def test_two_distinct_months_similar_amount_is_recurring(self):
        df = _master_df([
            ["2026-05-10", "Netflix", 45.0],
            ["2026-06-10", "Netflix", 47.0],  # within ±10%
        ])
        assert self._detect(df) is True

    def test_same_month_twice_is_not_recurring(self):
        df = _master_df([
            ["2026-06-01", "Netflix", 45.0],
            ["2026-06-20", "Netflix", 45.0],
        ])
        assert self._detect(df) is False

    def test_amount_outside_tolerance_ignored(self):
        df = _master_df([
            ["2026-05-10", "Netflix", 45.0],
            ["2026-06-10", "Netflix", 90.0],  # not similar
        ])
        assert self._detect(df) is False

    def test_blank_description_is_never_recurring(self):
        assert merchant_map.detect_recurring("", 45.0) is False

    def test_unreadable_master_returns_false(self):
        with patch("merchant_map.pd.read_excel", side_effect=OSError("locked")), \
             patch("merchant_map.get_excel_path_for_reading", return_value="fake.xlsx"):
            assert merchant_map.detect_recurring("Netflix", 45.0) is False

    async def test_quick_confirm_card_proposes_recurring(self):
        upd = make_update("netflix 45")
        ctx = make_ctx()
        parsed = {"value": 45, "currency": "PLN", "category": "Health",
                  "description": "Netflix", "type": "Expense", "person": ""}
        with patch("handlers.quick_conv.merchant_map") as mock_mm, \
             patch("handlers.quick_conv.load_reference_data", return_value=SAMPLE_LISTS), \
             patch("handlers.quick_conv.parse_quick", return_value=parsed), \
             patch("handlers.quick_conv.load_rates", return_value=SAMPLE_RATES), \
             patch("handlers.quick_conv.get_display_currency", return_value="PLN"), \
             patch("handlers.quick_conv.format_base_as_currency", return_value="45.00 PLN"):
            mock_mm.try_local_quick_parse.return_value = None
            mock_mm.detect_recurring.return_value = True
            result = await handle_quick_add(upd, ctx)
        assert result == states.QUICK_CONFIRM
        sent = upd.message.reply_text.call_args.args[0]
        assert "🔁" in sent
        kb = upd.message.reply_text.call_args.kwargs["reply_markup"].keyboard
        buttons = [b.text for row in kb for b in row]
        assert RECURRING_YES_BUTTON in buttons
        # Proposal only — the stored row is NOT auto-marked recurring.
        assert not ctx.user_data["quick_parsed"].get("is_recurring")

    async def test_accepting_proposal_saves_recurring(self):
        ctx = make_ctx()
        ctx.user_data["quick_parsed"] = {
            "value": 45, "currency": "PLN", "category": "Health",
            "description": "Netflix", "type": "Expense", "person": "",
            "is_recurring": False,
        }
        upd = make_update(RECURRING_YES_BUTTON)
        with patch("handlers.quick_conv.load_rates", return_value=SAMPLE_RATES), \
             patch("handlers.quick_conv.get_display_currency", return_value="PLN"), \
             patch("handlers.quick_conv.append_transaction", AsyncMock()) as mock_append, \
             patch("handlers.quick_conv.check_budget_alert", AsyncMock()):
            result = await quick_confirm(upd, ctx)
        assert result == ConversationHandler.END
        assert mock_append.await_args.args[0].is_recurring is True


# ── Items 3 + 7: /add two-tap defaults and edit-from-confirm ─────────────────

class TestAddTwoTapDefaults:
    async def _to_confirm(self, ctx, detect=False):
        with patch("handlers.add_conv.load_rates", return_value=SAMPLE_RATES), \
             patch("handlers.add_conv.load_reference_data", return_value=SAMPLE_LISTS), \
             patch("handlers.add_conv.get_display_currency", return_value="EUR"), \
             patch("merchant_map.detect_recurring", return_value=detect):
            await cmd_add(make_update("/add"), ctx)
            await add_value(make_update("100"), ctx)
            return await add_category(make_update("Groceries"), ctx)

    async def test_defaults_prefilled(self):
        ctx = make_ctx()
        r = await self._to_confirm(ctx)
        assert r == states.ADD_CONFIRM
        state = ctx.user_data["state"]
        assert state.currency == "EUR"      # display currency
        assert state.transaction_type == "Expense"
        assert state.date == date.today()
        assert state.description == ""
        assert state.person == ""           # household
        assert state.is_recurring is False

    async def test_confirm_card_offers_edit_button(self):
        ctx = make_ctx()
        upd = make_update("Groceries")
        with patch("handlers.add_conv.load_rates", return_value=SAMPLE_RATES), \
             patch("handlers.add_conv.load_reference_data", return_value=SAMPLE_LISTS), \
             patch("handlers.add_conv.get_display_currency", return_value="PLN"), \
             patch("merchant_map.detect_recurring", return_value=False):
            await cmd_add(make_update("/add"), ctx)
            await add_value(make_update("100"), ctx)
            await add_category(upd, ctx)
        kb = upd.message.reply_text.call_args.kwargs["reply_markup"].keyboard
        buttons = [b.text for row in kb for b in row]
        assert "✏️ Edit a field" in buttons
        assert "✅ Save" in buttons

    async def test_edit_currency_from_confirm(self):
        ctx = make_ctx()
        await self._to_confirm(ctx)
        with patch("merchant_map.detect_recurring", return_value=False):
            await add_confirm(make_update("✏️ Edit a field"), ctx)
            await add_confirm(make_update("Currency"), ctx)
            r = await add_confirm(make_update("usd"), ctx)
        assert r == states.ADD_CONFIRM
        assert ctx.user_data["state"].currency == "USD"

    async def test_edit_back_returns_to_card(self):
        ctx = make_ctx()
        await self._to_confirm(ctx)
        with patch("merchant_map.detect_recurring", return_value=False):
            await add_confirm(make_update("✏️ Edit a field"), ctx)
            r = await add_confirm(make_update("← Back"), ctx)
        assert r == states.ADD_CONFIRM
        assert "add_edit" not in ctx.user_data

    async def test_edit_description_reruns_recurring_detection(self):
        ctx = make_ctx()
        await self._to_confirm(ctx)
        with patch("merchant_map.detect_recurring", return_value=True):
            await add_confirm(make_update("✏️ Edit a field"), ctx)
            await add_confirm(make_update("Description"), ctx)
            upd = make_update("Netflix")
            r = await add_confirm(upd, ctx)
        assert r == states.ADD_CONFIRM
        assert ctx.user_data["state"].is_recurring is True
        card = upd.message.reply_text.call_args.args[0]
        assert "🔁" in card

    async def test_user_can_override_recurring_proposal(self):
        ctx = make_ctx()
        await self._to_confirm(ctx)
        ctx.user_data["state"].is_recurring = True
        ctx.user_data["recurring_proposed"] = True
        with patch("merchant_map.detect_recurring", return_value=True):
            await add_confirm(make_update("✏️ Edit a field"), ctx)
            await add_confirm(make_update("Recurring"), ctx)
            r = await add_confirm(make_update("No — one-off"), ctx)
        assert r == states.ADD_CONFIRM
        assert ctx.user_data["state"].is_recurring is False
