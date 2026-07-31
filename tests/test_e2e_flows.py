"""
tests/test_e2e_flows.py — end-to-end conversation-flow tests for the major
bot commands.

Integration-style tests: each test drives a whole command flow (or a key edge
case of one) through the real handler functions, with Telegram and the Excel
data layer fully mocked at the handler-module namespace — the same pattern as
tests/test_handlers_full.py.

Covers:
- /add     — full 9-step golden path, future date, invalid amount,
             unknown category/currency, cancel, /skip, duplicate warning
- /bulk    — text parse → preview → save, file upload, dedup detection,
             drop/keep grammar, row edits, cancel, rejections
- /edit    — pick → field → value → confirm, stale-row guard, validations
- /delete  — pick → confirm, stale-row guard, validations
- /summary — no-arg picker, month arg, range arg, invalid arg
- /report  — basic calendar report output, over-budget flag
- /cycle   — no-arg status, started subcommand, detect subcommand
- /help    — /help and every `<cmd> help` subcommand render valid MarkdownV2

No live file I/O (only pytest tmp dirs via conftest fixtures), no live
Telegram, no paid AI calls.

asyncio_mode = auto (pytest.ini) — no @pytest.mark.asyncio needed.
"""

import os
import sys
from contextlib import ExitStack, contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

# ── Environment must be set before any project import ────────────────────────
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("ALLOWED_TELEGRAM_IDS", "123")

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import settings
import states
from data import current_year_and_month
from file_storage import RowMovedError
from telegram.ext import ConversationHandler

import handlers.add_conv as add_conv
import handlers.bulk_conv as bulk_conv
import handlers.cycle as cycle_mod
import handlers.delete_conv as delete_conv
import handlers.edit_conv as edit_conv
import handlers.misc as misc_mod
import handlers.reports as reports_mod

# uid 123 is the primary user in conftest's ALLOWED_TELEGRAM_IDS, so these
# flows pass the real @auth / @auth_write gates regardless of whether an
# earlier-collected module swapped the decorators for pass-throughs.
UID = 123

SAMPLE_RATES = {"PLN": 1.0, "USD": 4.0, "EUR": 4.5}
SAMPLE_LISTS = {
    "txn_types": ["Expense", "Income", "Savings"],
    "categories": ["Groceries", "Transport", "Salary", "Other"],
    "persons": [],
}

TODAY = datetime.now(timezone.utc).date()
# /add's date step works in the bot's local timezone, not UTC.
LOCAL_TODAY = datetime.now(add_conv.TIMEZONE).date()


# ── Shared helpers ────────────────────────────────────────────────────────────

def make_update(text="hello", user_id=UID, photo=None, document=None):
    upd = MagicMock()
    upd.message.text = text
    upd.message.reply_text = AsyncMock()
    upd.message.reply_photo = AsyncMock()
    upd.effective_message = upd.message
    upd.effective_user.id = user_id
    upd.effective_user.first_name = "Tester"
    upd.message.photo = photo
    upd.message.document = document
    upd.callback_query = None
    return upd


def make_ctx(args=None):
    ctx = MagicMock()
    ctx.user_data = {}
    ctx.args = args or []
    ctx.bot = MagicMock()
    return ctx


def all_replies(*updates) -> str:
    """Concatenate every reply_text sent to the given updates."""
    texts = []
    for upd in updates:
        for c in upd.message.reply_text.call_args_list:
            texts.append(str(c.args[0]) if c.args else "")
    return "\n".join(texts)


@contextmanager
def applied(patches):
    """Enter a list of unittest.mock patchers, guaranteed cleanup."""
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield


# ═══════════════════════════════════════════════════════════════════════════════
# /add — full 9-step flow
# ═══════════════════════════════════════════════════════════════════════════════

def add_patches(append_mock=None):
    return [
        patch("handlers.add_conv.load_rates", return_value=SAMPLE_RATES),
        patch("handlers.add_conv.load_reference_data", return_value=SAMPLE_LISTS),
        patch("handlers.add_conv.get_display_currency", return_value="PLN"),
        patch("handlers.add_conv.append_transaction", append_mock or MagicMock()),
        patch("handlers.add_conv.check_budget_alert", AsyncMock()),
        patch("handlers.add_conv.maybe_prompt_cycle_start", AsyncMock()),
        patch.dict(add_conv._last_saved, {}, clear=True),
    ]


ADD_STEP_HANDLERS = {
    states.ADD_VALUE: "add_value",
    states.ADD_CURRENCY: "add_currency",
    states.ADD_TYPE: "add_type",
    states.ADD_CATEGORY: "add_category",
    states.ADD_DATE: "add_date",
    states.ADD_DESC: "add_desc",
    states.ADD_RECURRING: "add_recurring",
    states.ADD_CONFIRM: "add_confirm",
}


async def drive_add(ctx, answers):
    """Run /add then feed each answer through the state machine.

    Caller is responsible for the patch context. Returns (state, updates)."""
    upd = make_update("/add")
    state = await add_conv.cmd_add(upd, ctx)
    updates = [upd]
    for answer in answers:
        upd = make_update(answer)
        updates.append(upd)
        if answer == "/skip" and state == states.ADD_DESC:
            state = await add_conv.add_skip_desc(upd, ctx)
        else:
            state = await getattr(add_conv, ADD_STEP_HANDLERS[state])(upd, ctx)
    return state, updates


class TestAddFlow:
    async def _drive(self, answers, append_mock=None):
        with applied(add_patches(append_mock)):
            ctx = make_ctx()
            state, updates = await drive_add(ctx, answers)
        return state, ctx, updates

    async def test_add_golden_path(self):
        # Two-tap flow: amount → category → save. Currency/type/date/recurring
        # all default; description is empty unless edited from the confirm card.
        append_mock = MagicMock()
        state, ctx, updates = await self._drive(
            ["49.99", "Groceries", "✅ Save"],
            append_mock=append_mock,
        )
        assert state == ConversationHandler.END
        append_mock.assert_called_once()
        txn = append_mock.call_args.args[0]
        assert txn.value == 49.99
        assert txn.currency == "PLN"
        assert txn.transaction_type == "Expense"
        assert txn.category == "Groceries"
        assert txn.is_recurring is False
        assert txn.date == LOCAL_TODAY
        assert "Saved" in all_replies(*updates)

    async def test_add_golden_path_foreign_currency_recurring(self):
        # Two-tap flow to confirm card, then edit currency and recurring via
        # the confirm-card edit flow before saving.
        append_mock = MagicMock()
        with applied(add_patches(append_mock)):
            ctx = make_ctx()
            _, upds = await drive_add(ctx, ["100", "Transport"])

            upd_e1 = make_update("✏️ Edit a field")
            await add_conv.add_confirm(upd_e1, ctx)
            upd_ccy_field = make_update("Currency")
            await add_conv.add_confirm(upd_ccy_field, ctx)
            upd_eur = make_update("EUR")
            await add_conv.add_confirm(upd_eur, ctx)

            upd_e2 = make_update("✏️ Edit a field")
            await add_conv.add_confirm(upd_e2, ctx)
            upd_rec_field = make_update("Recurring")
            await add_conv.add_confirm(upd_rec_field, ctx)
            upd_yes = make_update("Yes — recurring")
            await add_conv.add_confirm(upd_yes, ctx)

            upd_save = make_update("✅ Save")
            state = await add_conv.add_confirm(upd_save, ctx)

        assert state == ConversationHandler.END
        txn = append_mock.call_args.args[0]
        assert txn.currency == "EUR"
        assert txn.is_recurring is True
        assert txn.description == ""
        # PLN equivalent shown in the confirm card after setting EUR (100 * 4.5).
        all_text = all_replies(*upds, upd_e1, upd_ccy_field, upd_eur,
                               upd_e2, upd_rec_field, upd_yes, upd_save)
        assert "450" in all_text

    async def test_add_invalid_amount_reprompts(self):
        state, _, updates = await self._drive(["abc"])
        assert state == states.ADD_VALUE
        assert "valid positive number" in all_replies(*updates)

    async def test_add_zero_amount_reprompts(self):
        state, _, _ = await self._drive(["0"])
        assert state == states.ADD_VALUE

    async def test_add_unknown_currency_reprompts(self):
        # Currency is no longer a standalone step; validation is reached via
        # the confirm-card edit flow.
        with applied(add_patches()):
            ctx = make_ctx()
            await drive_add(ctx, ["50", "Groceries"])
            upd = make_update("✏️ Edit a field")
            await add_conv.add_confirm(upd, ctx)
            upd = make_update("Currency")
            await add_conv.add_confirm(upd, ctx)
            upd_bad = make_update("XXX")
            state = await add_conv.add_confirm(upd_bad, ctx)
        assert state == states.ADD_CONFIRM
        assert "Unknown currency" in all_replies(upd_bad)

    async def test_add_unknown_category_reprompts(self):
        state, _, updates = await self._drive(
            ["50", "PLN", "Expense", "Nonexistent Category"])
        assert state == states.ADD_CATEGORY
        assert "choose from the list" in all_replies(*updates)

    async def test_add_future_date_rejected(self):
        # Date is no longer a standalone step; validation is reached via the
        # confirm-card edit flow.
        tomorrow = (LOCAL_TODAY + timedelta(days=1)).isoformat()
        with applied(add_patches()):
            ctx = make_ctx()
            await drive_add(ctx, ["50", "Groceries"])
            upd = make_update("✏️ Edit a field")
            await add_conv.add_confirm(upd, ctx)
            upd = make_update("Date")
            await add_conv.add_confirm(upd, ctx)
            upd_bad = make_update(tomorrow)
            state = await add_conv.add_confirm(upd_bad, ctx)
        assert state == states.ADD_CONFIRM
        assert "Future dates" in all_replies(upd_bad)

    async def test_add_malformed_date_rejected(self):
        with applied(add_patches()):
            ctx = make_ctx()
            await drive_add(ctx, ["50", "Groceries"])
            upd = make_update("✏️ Edit a field")
            await add_conv.add_confirm(upd, ctx)
            upd = make_update("Date")
            await add_conv.add_confirm(upd, ctx)
            upd_bad = make_update("31/12/2025")
            state = await add_conv.add_confirm(upd_bad, ctx)
        assert state == states.ADD_CONFIRM
        assert "YYYY-MM-DD" in all_replies(upd_bad)

    async def test_add_cancel_at_confirm_writes_nothing(self):
        append_mock = MagicMock()
        state, ctx, updates = await self._drive(
            ["50", "PLN", "Expense", "Groceries", "today",
             "desc", "No — one-off", "❌ Cancel"],
            append_mock=append_mock,
        )
        assert state == ConversationHandler.END
        append_mock.assert_not_called()
        assert "Cancelled" in all_replies(*updates)
        assert ctx.user_data == {}

    async def test_add_duplicate_warning_then_save_anyway(self):
        append_mock = MagicMock()
        with applied(add_patches(append_mock)):
            # Seed a just-saved identical transaction for this user.
            add_conv._last_saved[UID] = (
                50.0, "PLN", "Groceries", datetime.now(timezone.utc))
            ctx = make_ctx()
            state, _ = await drive_add(
                ctx, ["50", "PLN", "Expense", "Groceries", "today",
                      "desc", "No — one-off"])
            assert state == states.ADD_CONFIRM

            upd = make_update("✅ Save")
            state = await add_conv.add_confirm(upd, ctx)
            # First save attempt warns about the duplicate, stays in confirm.
            assert state == states.ADD_CONFIRM
            assert "Possible duplicate" in all_replies(upd)
            append_mock.assert_not_called()

            # Confirm again — now it saves.
            upd2 = make_update("✅ Yes, save anyway")
            state = await add_conv.add_confirm(upd2, ctx)
            assert state == ConversationHandler.END
            append_mock.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# /bulk — text and file flows
# ═══════════════════════════════════════════════════════════════════════════════

BULK_ROWS = [
    {"date": "2026-07-01", "value": 12.50, "currency": "PLN", "type": "Expense",
     "category": "Groceries", "description": "milk", "person": ""},
    {"date": "2026-07-02", "value": 30.00, "currency": "PLN", "type": "Expense",
     "category": "Transport", "description": "bus ticket", "person": ""},
]

EMPTY_EVIDENCE = {"strict": {}, "loose": {}}


def bulk_patches(parsed=None, evidence=None, batch_mock=None):
    return [
        patch("handlers.bulk_conv.load_reference_data", return_value=SAMPLE_LISTS),
        patch("handlers.bulk_conv.parse_text",
              return_value=[dict(r) for r in (parsed if parsed is not None else BULK_ROWS)]),
        patch("handlers.bulk_conv.parse_image", return_value=[]),
        patch("handlers.bulk_conv.load_dedup_evidence",
              return_value=evidence or EMPTY_EVIDENCE),
        patch("handlers.bulk_conv.async_append_batch", batch_mock or AsyncMock()),
        patch("handlers.bulk_conv.maybe_prompt_cycle_start", AsyncMock()),
    ]


async def start_bulk_and_receive(ctx, text="coffee 12.50; bus 30"):
    """Run /bulk then send text. Caller owns the patch context.

    Returns (state, updates)."""
    upd_start = make_update("/bulk")
    state = await bulk_conv.cmd_bulk(upd_start, ctx)
    assert state == states.BULK_RECEIVE
    upd_recv = make_update(text)
    state = await bulk_conv.bulk_receive(upd_recv, ctx)
    return state, [upd_start, upd_recv]


class TestBulkTextFlow:
    async def test_bulk_text_golden_path_save(self):
        batch_mock = AsyncMock()
        with applied(bulk_patches(batch_mock=batch_mock)):
            ctx = make_ctx()
            state, _ = await start_bulk_and_receive(ctx)
            assert state == states.BULK_CONFIRM
            assert len(ctx.user_data["bulk_parsed"]) == 2
            upd_save = make_update("save")
            state = await bulk_conv.bulk_confirm(upd_save, ctx)
        assert state == ConversationHandler.END
        batch_mock.assert_awaited_once()
        txns = batch_mock.call_args.args[0]
        assert len(txns) == 2
        assert {t.category for t in txns} == {"Groceries", "Transport"}
        assert "Saved 2 of 2" in all_replies(upd_save)

    async def test_bulk_text_preview_shows_rows(self):
        with applied(bulk_patches()):
            ctx = make_ctx()
            _, updates = await start_bulk_and_receive(ctx)
        preview = all_replies(*updates)
        assert "milk" in preview
        assert "bus ticket" in preview

    async def test_bulk_cancel_discards_draft(self):
        batch_mock = AsyncMock()
        with applied(bulk_patches(batch_mock=batch_mock)):
            ctx = make_ctx()
            await start_bulk_and_receive(ctx)
            upd_cancel = make_update("cancel")
            state = await bulk_conv.bulk_confirm(upd_cancel, ctx)
            assert state == ConversationHandler.END
            batch_mock.assert_not_awaited()
            assert "Cancelled" in all_replies(upd_cancel)
            assert bulk_conv._load_user_draft(UID) == []

    async def test_bulk_dedup_detection_skips_duplicate(self):
        # Row 1 already exists in MasterData → strict-key evidence match.
        key = bulk_conv._row_dedup_key(BULK_ROWS[0])
        evidence = {"strict": {key: [("2026-07-01", "milk")]}, "loose": {}}
        batch_mock = AsyncMock()
        with applied(bulk_patches(evidence=evidence, batch_mock=batch_mock)):
            ctx = make_ctx()
            state, _ = await start_bulk_and_receive(ctx)
            assert state == states.BULK_CONFIRM
            flagged = [r for r in ctx.user_data["bulk_parsed"] if r.get("dup")]
            assert len(flagged) == 1
            upd_save = make_update("save")
            await bulk_conv.bulk_confirm(upd_save, ctx)
        txns = batch_mock.call_args.args[0]
        assert len(txns) == 1  # duplicate skipped
        assert "skipped as already imported" in all_replies(upd_save)

    async def test_bulk_keep_grammar_overrides_dedup(self):
        key = bulk_conv._row_dedup_key(BULK_ROWS[0])
        evidence = {"strict": {key: [("2026-07-01", "milk")]}, "loose": {}}
        batch_mock = AsyncMock()
        with applied(bulk_patches(evidence=evidence, batch_mock=batch_mock)):
            ctx = make_ctx()
            await start_bulk_and_receive(ctx)
            flagged_no = next(i + 1 for i, r in enumerate(ctx.user_data["bulk_parsed"])
                              if r.get("dup"))
            upd_keep = make_update(f"keep {flagged_no}")
            state = await bulk_conv.bulk_confirm(upd_keep, ctx)
            assert state == states.BULK_CONFIRM
            assert not any(r.get("dup") for r in ctx.user_data["bulk_parsed"])
            # After keep, save writes BOTH rows — the write-time dedup
            # re-check honours dup_keep.
            upd_save = make_update("save")
            await bulk_conv.bulk_confirm(upd_save, ctx)
        assert len(batch_mock.call_args.args[0]) == 2

    async def test_bulk_drop_grammar_excludes_row(self):
        batch_mock = AsyncMock()
        with applied(bulk_patches(batch_mock=batch_mock)):
            ctx = make_ctx()
            await start_bulk_and_receive(ctx)
            upd_drop = make_update("drop 2")
            state = await bulk_conv.bulk_confirm(upd_drop, ctx)
            assert state == states.BULK_CONFIRM
            assert ctx.user_data["bulk_parsed"][1].get("dropped") is True
            upd_save = make_update("save")
            await bulk_conv.bulk_confirm(upd_save, ctx)
        txns = batch_mock.call_args.args[0]
        assert len(txns) == 1
        assert "dropped as requested" in all_replies(upd_save)

    async def test_bulk_row_edit_grammar(self):
        with applied(bulk_patches()):
            ctx = make_ctx()
            await start_bulk_and_receive(ctx)
            upd_edit = make_update("1 category=Transport")
            state = await bulk_conv.bulk_confirm(upd_edit, ctx)
            assert state == states.BULK_CONFIRM
            assert ctx.user_data["bulk_parsed"][0]["category"] == "Transport"

    async def test_bulk_invalid_edit_reprompts(self):
        with applied(bulk_patches()):
            ctx = make_ctx()
            await start_bulk_and_receive(ctx)
            upd = make_update("99 category=Transport")
            state = await bulk_conv.bulk_confirm(upd, ctx)
            assert state == states.BULK_CONFIRM
            assert "doesn't exist" in all_replies(upd).lower()

    async def test_bulk_unknown_field_shows_editable_fields(self):
        with applied(bulk_patches()):
            ctx = make_ctx()
            await start_bulk_and_receive(ctx)
            upd = make_update("1 foo=bar")
            state = await bulk_conv.bulk_confirm(upd, ctx)
            assert state == states.BULK_CONFIRM
            reply = all_replies(upd).lower()
            assert "unknown field" in reply
            assert "editable fields" in reply

    async def test_bulk_receive_rejects_slash_command_text(self):
        with applied(bulk_patches()):
            ctx = make_ctx()
            await bulk_conv.cmd_bulk(make_update("/bulk"), ctx)
            upd = make_update("/summary")
            state = await bulk_conv.bulk_receive(upd, ctx)
            assert state == states.BULK_RECEIVE
            assert "not a command" in all_replies(upd)

    async def test_bulk_no_transactions_found_ends(self):
        with applied(bulk_patches(parsed=[])):
            ctx = make_ctx()
            state, updates = await start_bulk_and_receive(ctx)
        assert state == ConversationHandler.END
        assert "No transactions found" in all_replies(*updates)


class TestBulkFileFlow:
    def _make_document_update(self, filename, mime_type, content: bytes):
        doc = MagicMock()
        doc.file_name = filename
        doc.mime_type = mime_type
        tg_file = MagicMock()
        tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(content))
        doc.get_file = AsyncMock(return_value=tg_file)
        return make_update(text=None, document=doc)

    async def test_bulk_file_upload_golden_path(self):
        parse_mock = MagicMock(return_value=[dict(r) for r in BULK_ROWS])
        batch_mock = AsyncMock()
        extra = [
            # Bypass statement-profile sniffing → plain-text fallback path.
            patch("handlers.bulk_conv._read_statement_headers_and_sniff",
                  return_value=([], None)),
            patch("handlers.bulk_conv.parse_text", parse_mock),
        ]
        with applied(bulk_patches(batch_mock=batch_mock) + extra):
            ctx = make_ctx()
            state = await bulk_conv.cmd_bulk(make_update("/bulk"), ctx)
            assert state == states.BULK_RECEIVE

            upd = self._make_document_update(
                "transactions.txt", "text/plain", b"milk 12.50\nbus ticket 30")
            state = await bulk_conv.bulk_receive(upd, ctx)
            assert state == states.BULK_CONFIRM
            parse_mock.assert_called_once()
            assert "milk 12.50" in parse_mock.call_args.args[0]

            upd_save = make_update("save")
            state = await bulk_conv.bulk_confirm(upd_save, ctx)
        assert state == ConversationHandler.END
        batch_mock.assert_awaited_once()
        assert len(batch_mock.call_args.args[0]) == 2

    async def test_bulk_file_non_text_rejected(self):
        with applied(bulk_patches()):
            ctx = make_ctx()
            await bulk_conv.cmd_bulk(make_update("/bulk"), ctx)
            upd = self._make_document_update(
                "statement.pdf", "application/pdf", b"%PDF-1.4")
            state = await bulk_conv.bulk_receive(upd, ctx)
            assert state == states.BULK_RECEIVE
            assert "plain text" in all_replies(upd)


# ═══════════════════════════════════════════════════════════════════════════════
# /edit
# ═══════════════════════════════════════════════════════════════════════════════

RECENT_TXNS = [
    {"Date": date(2026, 7, 20), "Value": 50.0, "Currency": "PLN",
     "Category": "Groceries", "Description": "milk", "_row_idx": 7},
    {"Date": date(2026, 7, 21), "Value": 80.0, "Currency": "EUR",
     "Category": "Transport", "Description": "train", "_row_idx": 8},
]


def edit_patches(update_field_mock=None):
    return [
        patch("handlers.edit_conv.get_recent_transactions",
              return_value=[dict(t) for t in RECENT_TXNS]),
        patch("handlers.edit_conv.load_reference_data", return_value=SAMPLE_LISTS),
        patch("handlers.edit_conv.load_rates", return_value=SAMPLE_RATES),
        patch("handlers.edit_conv.update_transaction_field",
              update_field_mock or MagicMock()),
    ]


class TestEditFlow:
    async def _drive(self, answers, update_field_mock=None):
        with applied(edit_patches(update_field_mock)):
            ctx = make_ctx()
            upd = make_update("/edit")
            state = await edit_conv.cmd_edit(upd, ctx)
            updates = [upd]
            step = {
                states.EDIT_PICK: edit_conv.edit_pick,
                states.EDIT_FIELD: edit_conv.edit_field,
                states.EDIT_VALUE: edit_conv.edit_value,
                states.EDIT_CONFIRM: edit_conv.edit_confirm,
            }
            for answer in answers:
                upd = make_update(answer)
                updates.append(upd)
                state = await step[state](upd, ctx)
        return state, ctx, updates

    async def test_edit_golden_path_amount(self):
        field_mock = MagicMock()
        state, _, updates = await self._drive(
            ["1", "Amount", "42.5", "Yes"], update_field_mock=field_mock)
        assert state == ConversationHandler.END
        field_mock.assert_called_once()
        row_idx, field_updates, _, expected = field_mock.call_args.args
        assert row_idx == 7
        assert field_updates == {"Value": 42.5}
        assert expected["Description"] == "milk"
        assert "Updated" in all_replies(*updates)

    async def test_edit_golden_path_category(self):
        field_mock = MagicMock()
        state, _, _ = await self._drive(
            ["2", "Category", "Groceries", "Yes"], update_field_mock=field_mock)
        assert state == ConversationHandler.END
        row_idx, updates, _, _ = field_mock.call_args.args
        assert row_idx == 8
        assert updates == {"Category": "Groceries"}

    async def test_edit_stale_row_guard(self):
        field_mock = MagicMock(side_effect=RowMovedError("row moved"))
        state, _, updates = await self._drive(
            ["1", "Amount", "42.5", "Yes"], update_field_mock=field_mock)
        assert state == ConversationHandler.END
        text = all_replies(*updates)
        assert "moved" in text
        assert "run /edit again" in text

    async def test_edit_invalid_pick_reprompts(self):
        state, _, updates = await self._drive(["99"])
        assert state == states.EDIT_PICK
        assert "Pick a number" in all_replies(*updates)

    async def test_edit_invalid_amount_reprompts(self):
        state, _, updates = await self._drive(["1", "Amount", "-5"])
        assert state == states.EDIT_VALUE
        assert "positive number" in all_replies(*updates)

    async def test_edit_future_date_rejected(self):
        tomorrow = (TODAY + timedelta(days=1)).isoformat()
        state, _, updates = await self._drive(["1", "Date", tomorrow])
        assert state == states.EDIT_VALUE
        assert "future" in all_replies(*updates)

    async def test_edit_cancel_at_pick(self):
        field_mock = MagicMock()
        state, _, _ = await self._drive(["Cancel"], update_field_mock=field_mock)
        assert state == ConversationHandler.END
        field_mock.assert_not_called()

    async def test_edit_decline_at_confirm_writes_nothing(self):
        field_mock = MagicMock()
        state, _, _ = await self._drive(
            ["1", "Amount", "42.5", "No"], update_field_mock=field_mock)
        assert state == ConversationHandler.END
        field_mock.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# /delete
# ═══════════════════════════════════════════════════════════════════════════════

def delete_patches(recent=None, delete_mock=None):
    return [
        patch("handlers.delete_conv.get_recent_transactions",
              return_value=[dict(t) for t in (RECENT_TXNS if recent is None else recent)]),
        patch("handlers.delete_conv.delete_transaction_row",
              delete_mock or MagicMock()),
    ]


class TestDeleteFlow:
    async def test_delete_golden_path(self):
        delete_mock = MagicMock()
        with applied(delete_patches(delete_mock=delete_mock)):
            ctx = make_ctx()
            upd = make_update("/delete")
            state = await delete_conv.cmd_delete(upd, ctx)
            assert state == states.DELETE_PICK
            # List is reversed: item 1 = newest = _row_idx 8
            upd2 = make_update("1")
            state = await delete_conv.delete_pick(upd2, ctx)
        assert state == ConversationHandler.END
        delete_mock.assert_called_once()
        row_idx, expected = delete_mock.call_args.args
        assert row_idx == 8
        assert expected["Description"] == "train"
        assert "Deleted" in all_replies(upd2)

    async def test_delete_stale_row_guard(self):
        delete_mock = MagicMock(side_effect=RowMovedError("row moved"))
        with applied(delete_patches(delete_mock=delete_mock)):
            ctx = make_ctx()
            await delete_conv.cmd_delete(make_update("/delete"), ctx)
            upd = make_update("1")
            state = await delete_conv.delete_pick(upd, ctx)
        assert state == ConversationHandler.END
        text = all_replies(upd)
        assert "moved" in text
        assert "run /delete again" in text

    async def test_delete_invalid_pick_reprompts(self):
        with applied(delete_patches()):
            ctx = make_ctx()
            await delete_conv.cmd_delete(make_update("/delete"), ctx)
            upd = make_update("99")
            state = await delete_conv.delete_pick(upd, ctx)
        assert state == states.DELETE_PICK
        assert "Pick 1–2" in all_replies(upd)

    async def test_delete_no_transactions(self):
        with applied(delete_patches(recent=[])):
            upd = make_update("/delete")
            result = await delete_conv.cmd_delete(upd, make_ctx())
        assert result is None  # never entered the conversation
        assert "No transactions found" in all_replies(upd)


# ═══════════════════════════════════════════════════════════════════════════════
# /summary and /report
# ═══════════════════════════════════════════════════════════════════════════════

def make_df():
    """Transactions across two months incl. the current one."""
    cur_year, cur_month = current_year_and_month()
    return pd.DataFrame({
        "Date":        [f"{cur_year}-{TODAY.month:02d}-01", f"{cur_year}-{TODAY.month:02d}-05",
                        "2025-06-10", "2025-06-15", "2025-07-01"],
        "Year":        [cur_year, cur_year, 2025, 2025, 2025],
        "Month":       [cur_month, cur_month, "Jun", "Jun", "Jul"],
        "Type":        ["Income", "Expense", "Expense", "Income", "Expense"],
        "Category":    ["Salary", "Groceries", "Transport", "Salary", "Groceries"],
        "Currency":    ["PLN", "PLN", "PLN", "PLN", "PLN"],
        "Value":       [5000.0, 100.0, 60.0, 4800.0, 40.0],
        "_base":       [5000.0, 100.0, 60.0, 4800.0, 40.0],
        "IsDone":      [True, True, True, True, True],
        "IsRecurring": [False, False, True, False, False],
    })


def reports_patches(budgets=None):
    return [
        patch("handlers.reports.load_transactions", return_value=make_df()),
        patch("handlers.reports.load_rates", return_value=SAMPLE_RATES),
        patch("handlers.reports.load_budgets", return_value=budgets or {}),
        patch("handlers.reports.get_display_currency", return_value="PLN"),
    ]


class TestSummaryFlow:
    async def test_summary_no_arg_shows_picker(self, monkeypatch):
        monkeypatch.setattr(settings, "BUDGET_CYCLE", False)
        with applied(reports_patches()):
            upd = make_update("/summary")
            await reports_mod.cmd_summary(upd, make_ctx())
        upd.message.reply_text.assert_awaited_once()
        assert "pick a period" in all_replies(upd)
        assert upd.message.reply_text.call_args.kwargs.get("reply_markup") is not None

    async def test_summary_month_arg(self, monkeypatch):
        monkeypatch.setattr(settings, "BUDGET_CYCLE", False)
        with applied(reports_patches()):
            upd = make_update("/summary jun 2025")
            await reports_mod.cmd_summary(upd, make_ctx(args=["jun", "2025"]))
        text = all_replies(upd)
        assert "Jun 2025 — Summary" in text
        assert "Income" in text and "Expenses" in text

    async def test_summary_range_arg(self, monkeypatch):
        monkeypatch.setattr(settings, "BUDGET_CYCLE", False)
        with applied(reports_patches()):
            upd = make_update("/summary jun 2025 - jul 2025")
            await reports_mod.cmd_summary(
                upd, make_ctx(args=["jun", "2025", "-", "jul", "2025"]))
        text = all_replies(upd)
        assert "Range Report" in text
        assert "Income" in text

    async def test_summary_current_month_has_projection(self, monkeypatch):
        monkeypatch.setattr(settings, "BUDGET_CYCLE", False)
        cur_year, cur_month = current_year_and_month()
        with applied(reports_patches()):
            upd = make_update("/summary")
            await reports_mod.cmd_summary(
                upd, make_ctx(args=[cur_month.lower(), str(cur_year)]))
        text = all_replies(upd)
        assert f"{cur_month} {cur_year} — Summary" in text
        assert "Projected month-end spend" in text

    async def test_summary_invalid_arg(self, monkeypatch):
        monkeypatch.setattr(settings, "BUDGET_CYCLE", False)
        with applied(reports_patches()):
            upd = make_update("/summary garbage")
            await reports_mod.cmd_summary(upd, make_ctx(args=["garbage"]))
        assert "Could not understand" in all_replies(upd)


class TestReportFlow:
    async def test_report_golden_path(self):
        with applied(reports_patches()):
            upd = make_update("/report")
            await reports_mod.cmd_report(upd, make_ctx())
        text = all_replies(upd)
        assert "Monthly Report" in text
        assert "Income" in text
        assert "Groceries" in text
        assert "Savings rate" in text

    async def test_report_flags_over_budget_category(self):
        with applied(reports_patches(budgets={"Groceries": 10.0})):
            upd = make_update("/report")
            await reports_mod.cmd_report(upd, make_ctx())
        # Groceries spend (100) exceeds its 10 budget → red flag
        assert "🔴" in all_replies(upd)


# ═══════════════════════════════════════════════════════════════════════════════
# /cycle
# ═══════════════════════════════════════════════════════════════════════════════

class TestCycleFlow:
    async def test_cycle_disabled_message(self, monkeypatch):
        monkeypatch.setattr(settings, "BUDGET_CYCLE", False)
        upd = make_update("/cycle")
        await cycle_mod.cmd_cycle(upd, make_ctx())
        assert "disabled" in all_replies(upd)

    async def test_cycle_status_none_recorded(self, monkeypatch):
        monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
        with patch("handlers.cycle.current_cycle_start", return_value=None):
            upd = make_update("/cycle")
            await cycle_mod.cmd_cycle(upd, make_ctx())
        assert "No budget cycle recorded" in all_replies(upd)

    async def test_cycle_status_current(self, monkeypatch):
        monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
        local_today = cycle_mod.now_utc().date()
        start = local_today - timedelta(days=9)
        with patch("handlers.cycle.current_cycle_start",
                   return_value=(start, "Jul 2026")):
            upd = make_update("/cycle")
            await cycle_mod.cmd_cycle(upd, make_ctx())
        text = all_replies(upd)
        assert "Current cycle" in text
        assert "Jul 2026" in text
        assert "day 10" in text

    async def test_cycle_started_today(self, monkeypatch):
        monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
        record = AsyncMock(return_value="Jul 2026")
        with patch("handlers.cycle.async_record_cycle_start", record):
            upd = make_update("/cycle started")
            await cycle_mod.cmd_cycle(upd, make_ctx(args=["started"]))
        record.assert_awaited_once()
        assert record.call_args.args[0] == cycle_mod.now_utc().date()
        assert "New budget cycle" in all_replies(upd)

    async def test_cycle_started_with_date(self, monkeypatch):
        monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
        record = AsyncMock(return_value="Jul 2026")
        with patch("handlers.cycle.async_record_cycle_start", record):
            upd = make_update("/cycle started 2026-07-01")
            await cycle_mod.cmd_cycle(upd, make_ctx(args=["started", "2026-07-01"]))
        assert record.call_args.args[0] == date(2026, 7, 1)

    async def test_cycle_started_duplicate_boundary(self, monkeypatch):
        monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
        record = AsyncMock(return_value=False)
        with patch("handlers.cycle.async_record_cycle_start", record):
            upd = make_update("/cycle started 2026-07-01")
            await cycle_mod.cmd_cycle(upd, make_ctx(args=["started", "2026-07-01"]))
        assert "already recorded" in all_replies(upd)

    async def test_cycle_started_future_rejected(self, monkeypatch):
        monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
        record = AsyncMock(return_value=True)
        future = (cycle_mod.now_utc().date() + timedelta(days=5)).isoformat()
        with patch("handlers.cycle.async_record_cycle_start", record):
            upd = make_update(f"/cycle started {future}")
            await cycle_mod.cmd_cycle(upd, make_ctx(args=["started", future]))
        record.assert_not_awaited()
        assert "cannot start in the future" in all_replies(upd)

    async def test_cycle_started_bad_date_rejected(self, monkeypatch):
        monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
        record = AsyncMock(return_value=True)
        with patch("handlers.cycle.async_record_cycle_start", record):
            upd = make_update("/cycle started 01.07.2026")
            await cycle_mod.cmd_cycle(upd, make_ctx(args=["started", "01.07.2026"]))
        record.assert_not_awaited()
        assert "Could not parse the date" in all_replies(upd)

    async def test_cycle_detect_golden_path(self, monkeypatch):
        monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
        candidates = [
            {"date": date(2026, 6, 1), "amounts": [5000.0], "unambiguous": True},
            {"date": date(2026, 7, 1), "amounts": [5100.0], "unambiguous": True},
        ]
        with patch("handlers.cycle.load_transactions", return_value=MagicMock()), \
             patch("handlers.cycle.load_cycles", return_value=[]), \
             patch("handlers.cycle.cycle_detect_keywords", return_value=["salary"]), \
             patch("handlers.cycle.detect_cycle_candidates", return_value=candidates):
            upd = make_update("/cycle detect")
            await cycle_mod.cmd_cycle(upd, make_ctx(args=["detect"]))
        text = all_replies(upd)
        assert "Scanning transaction history" in text
        assert "Found *2*" in text
        # Confirm/review/cancel inline keyboard attached to the last message
        assert upd.message.reply_text.call_args.kwargs.get("reply_markup") is not None

    async def test_cycle_detect_stores_candidates(self, monkeypatch):
        monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
        candidates = [{"date": date(2026, 6, 1), "amounts": [5000.0], "unambiguous": True}]
        ctx = make_ctx(args=["detect"])
        with patch("handlers.cycle.load_transactions", return_value=MagicMock()), \
             patch("handlers.cycle.load_cycles", return_value=[]), \
             patch("handlers.cycle.cycle_detect_keywords", return_value=["salary"]), \
             patch("handlers.cycle.detect_cycle_candidates", return_value=candidates), \
             patch("handlers.cycle.format_base_as_currency", return_value="5000.00 EUR"):
            await cycle_mod.cmd_cycle(make_update("/cycle detect"), ctx)
        assert ctx.user_data["detect_candidates"] == [
            {"date_str": "2026-06-01", "amounts": [5000.0],
             "amounts_fmt": ["5000.00 EUR"], "unambiguous": True}]

    async def test_cycle_detect_nothing_found(self, monkeypatch):
        monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
        with patch("handlers.cycle.load_transactions", return_value=MagicMock()), \
             patch("handlers.cycle.load_cycles", return_value=[]), \
             patch("handlers.cycle.cycle_detect_keywords", return_value=["salary"]), \
             patch("handlers.cycle.detect_cycle_candidates", return_value=[]):
            upd = make_update("/cycle detect")
            await cycle_mod.cmd_cycle(upd, make_ctx(args=["detect"]))
        assert "Nothing to backfill" in all_replies(upd)


# ═══════════════════════════════════════════════════════════════════════════════
# /help and per-command help subcommands — MarkdownV2 validity
# ═══════════════════════════════════════════════════════════════════════════════

from tests.mdv2_helpers import assert_valid_markdown_v2


class TestHelpFlow:
    async def test_help_renders_valid_markdownv2(self):
        with patch("handlers.misc.get_display_currency", return_value="PLN"):
            upd = make_update("/help")
            await misc_mod.cmd_help(upd, make_ctx())
        upd.message.reply_text.assert_awaited_once()
        call = upd.message.reply_text.call_args
        assert call.kwargs.get("parse_mode") == "MarkdownV2"
        assert_valid_markdown_v2(call.args[0], source="/help")

    async def test_help_lists_all_major_commands(self):
        with patch("handlers.misc.get_display_currency", return_value="PLN"):
            upd = make_update("/help")
            await misc_mod.cmd_help(upd, make_ctx())
        text = all_replies(upd)
        for cmd in ("/add", "/bulk", "/edit", "/delete", "/summary",
                    "/report", "/cycle", "/help"):
            assert cmd in text, f"{cmd} missing from /help"

    @pytest.mark.parametrize("handler_name,module", [
        ("cmd_add", add_conv),
        ("cmd_bulk", bulk_conv),
        ("cmd_delete", delete_conv),
        ("cmd_edit", edit_conv),
        ("cmd_summary", reports_mod),
        ("cmd_report", reports_mod),
    ], ids=["add", "bulk", "delete", "edit", "summary", "report"])
    async def test_help_subcommand_valid_markdownv2(self, handler_name, module):
        handler = getattr(module, handler_name)
        upd = make_update("help")
        result = await handler(upd, make_ctx(args=["help"]))
        upd.message.reply_text.assert_awaited_once()
        call = upd.message.reply_text.call_args
        assert call.kwargs.get("parse_mode") == "MarkdownV2"
        assert_valid_markdown_v2(call.args[0], source=handler_name + " help")
        # Conversation entry points must end, not enter the flow.
        assert result in (ConversationHandler.END, None)


# ── Bulk person callback + bulk_confirm guard tests ───────────────────────────

class TestBulkPersonCallback:
    """Tests for bulk_person_callback — especially the empty-person (shared expense) path."""

    def _make_callback_update(self, callback_data: str, user_id=UID):
        upd = MagicMock()
        upd.callback_query = MagicMock()
        upd.callback_query.data = callback_data
        upd.callback_query.answer = AsyncMock()
        upd.callback_query.edit_message_text = AsyncMock()
        upd.effective_user.id = user_id
        upd.message = None
        return upd

    async def test_empty_person_sets_shared_expense_confirmation(self):
        upd = self._make_callback_update("bperson:")
        ctx = make_ctx()
        ctx.user_data["_parse_file_bytes"] = b""
        ctx.user_data["_parse_filename"] = "file.csv"
        ctx.user_data["_parse_profile"] = {}
        ctx.user_data["_parse_profile_name"] = ""
        ctx.user_data["lists"] = SAMPLE_LISTS

        with patch("handlers.bulk_conv.load_reference_data", return_value=SAMPLE_LISTS), \
             patch("handlers.bulk_conv._do_finish_profile_parse", new_callable=AsyncMock) as mock_finish:
            mock_finish.return_value = bulk_conv.BULK_PERSON
            await bulk_conv.bulk_person_callback(upd, ctx)

        upd.callback_query.edit_message_text.assert_awaited_once()
        assert ctx.user_data["bulk_person"] == ""
        edit_call_text = upd.callback_query.edit_message_text.call_args[0][0]
        assert "shared expense" in edit_call_text

    async def test_named_person_sets_person_in_context(self):
        upd = self._make_callback_update("bperson:Alice")
        ctx = make_ctx()
        ctx.user_data["_parse_file_bytes"] = b""
        ctx.user_data["_parse_filename"] = "file.csv"
        ctx.user_data["_parse_profile"] = {}
        ctx.user_data["_parse_profile_name"] = ""
        ctx.user_data["lists"] = SAMPLE_LISTS

        with patch("handlers.bulk_conv.load_reference_data", return_value=SAMPLE_LISTS), \
             patch("handlers.bulk_conv._do_finish_profile_parse", new_callable=AsyncMock) as mock_finish:
            mock_finish.return_value = bulk_conv.BULK_PERSON
            await bulk_conv.bulk_person_callback(upd, ctx)

        assert ctx.user_data["bulk_person"] == "Alice"
        edit_call_text = upd.callback_query.edit_message_text.call_args[0][0]
        assert "Alice" in edit_call_text


class TestBulkConfirmInvalidBranch:
    """Covers the reason == 'invalid' path in bulk_confirm."""

    async def test_unrecognised_text_returns_plain_text_reply(self):
        upd = make_update("⚙️ More")
        ctx = make_ctx()
        ctx.user_data["bulk_parsed"] = [
            {"date": TODAY, "value": 10.0, "type": "Expense",
             "category": "Groceries", "person": "", "description": "test",
             "is_recurring": False, "currency": "USD", "dropped": False}
        ]
        ctx.user_data["lists"] = SAMPLE_LISTS

        state = await bulk_conv.bulk_confirm(upd, ctx)

        assert state == bulk_conv.BULK_CONFIRM
        upd.message.reply_text.assert_awaited()
        reply_text, reply_kwargs = (
            upd.message.reply_text.call_args[0][0],
            upd.message.reply_text.call_args[1],
        )
        assert reply_kwargs.get("parse_mode") is None
        assert "save" in reply_text.lower() or "edit" in reply_text.lower()
