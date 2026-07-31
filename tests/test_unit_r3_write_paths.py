"""
tests/test_unit_r3_write_paths.py — Cycle S1 Phase 2, Unit R3.

The write-path conversation handlers (add / quick / edit / delete) must go
through storage_facade (SQLite) instead of excel_ops / file_storage, and the
optimistic-lock conflict (storage_facade.RowMismatchError, the facade's
equivalent of file_storage.RowMovedError) must surface the same user-facing
"moved" message as before.

These tests run the real facade against a temp SQLite DB — no storage mocks.
"""

import datetime
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
import settings
import sqlite_ops
import storage_facade
import handlers.add_conv as add_conv
import handlers.quick_conv as quick_conv
import handlers.edit_conv as edit_conv
import handlers.delete_conv as delete_conv
from models import AddTransactionState
from states import QUICK_CONFIRM  # noqa: F401  (import sanity)
from telegram.ext import ConversationHandler

pytestmark = pytest.mark.asyncio

UID = 123


@pytest.fixture()
def sqlite_db(tmp_path, monkeypatch):
    """Point the facade at a fresh temp DB seeded with rates and a category."""
    db_path = tmp_path / "r3.db"
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", db_path)
    monkeypatch.setattr(config, "ALLOWED_USERS", [UID])
    conn = sqlite_ops.init_db(db_path)
    sqlite_ops.upsert_rate(conn, settings.DISPLAY_CURRENCY, 1.0)
    conn.close()
    return db_path


def make_update(text="x"):
    upd = MagicMock()
    upd.effective_user.id = UID
    upd.effective_user.first_name = "Tester"
    upd.message.text = text
    upd.message.reply_text = AsyncMock()
    upd.callback_query = None
    return upd


def make_ctx():
    ctx = MagicMock()
    ctx.args = []
    ctx.user_data = {}
    return ctx


def _list_rows():
    conn = sqlite_ops.init_db(settings.SQLITE_DB_PATH)
    try:
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM {sqlite_ops.TABLE_TRANSACTIONS} ORDER BY id")]
    finally:
        conn.close()


def _seed_row(**overrides):
    conn = sqlite_ops.init_db(settings.SQLITE_DB_PATH)
    try:
        from sqlite_types import TransactionRow
        row = dict(
            date="2026-07-01", year=2026, month="Jul", value=200.0,
            currency=settings.DISPLAY_CURRENCY, value_base=200.0,
            rate_used=1.0, type="Expense", category="Transport",
            person="", description="taxi", is_recurring=False,
            is_done=True, source="bot",
        )
        row.update(overrides)
        sqlite_ops.insert_transaction(conn, TransactionRow(**row))
        return conn.execute("SELECT max(id) AS id FROM "
                            f"{sqlite_ops.TABLE_TRANSACTIONS}").fetchone()["id"]
    finally:
        conn.close()


# ── Wiring: handlers call the facade, not excel_ops/file_storage ─────────────

async def test_handlers_are_wired_to_storage_facade():
    assert add_conv.append_transaction is storage_facade.append_transaction
    assert add_conv.load_reference_data is storage_facade.load_reference_data
    assert quick_conv.append_transaction is storage_facade.append_transaction
    assert quick_conv.load_reference_data is storage_facade.load_reference_data
    assert edit_conv.update_transaction_field is storage_facade.update_transaction_field
    assert edit_conv.load_reference_data is storage_facade.load_reference_data
    assert delete_conv.delete_transaction_row is storage_facade.delete_transaction_row


# ── /add saves through the facade ─────────────────────────────────────────────

async def test_add_confirm_saves_via_facade(sqlite_db):
    ctx = make_ctx()
    state = AddTransactionState(display_currency=settings.DISPLAY_CURRENCY,
                                rates={settings.DISPLAY_CURRENCY: 1.0})
    state.value = 42.5
    state.currency = settings.DISPLAY_CURRENCY
    state.transaction_type = "Expense"
    state.category = "Groceries"
    state.date = datetime.date(2026, 7, 20)
    state.description = "milk"
    state.person = ""
    state.is_recurring = False
    ctx.user_data["state"] = state
    upd = make_update("✅ Save")

    with patch("handlers.add_conv.check_budget_alert", AsyncMock()), \
         patch("handlers.add_conv.maybe_prompt_cycle_start", AsyncMock()), \
         patch("handlers.add_conv.get_display_currency",
               return_value=settings.DISPLAY_CURRENCY), \
         patch("handlers.add_conv._last_saved", {}):
        result = await add_conv.add_confirm(upd, ctx)

    assert result == ConversationHandler.END
    rows = _list_rows()
    assert len(rows) == 1
    assert rows[0]["value"] == 42.5
    assert rows[0]["category"] == "Groceries"
    assert rows[0]["value_base"] == 42.5
    sent = " ".join(c.args[0] for c in upd.message.reply_text.call_args_list)
    assert "Saved" in sent


# ── quick-add saves through the facade ────────────────────────────────────────

async def test_quick_confirm_saves_via_facade(sqlite_db):
    ctx = make_ctx()
    ctx.user_data["quick_parsed"] = {
        "date": "2026-07-19", "value": 89.0,
        "currency": settings.DISPLAY_CURRENCY, "type": "Expense",
        "category": "Groceries", "description": "shop", "person": "",
        "is_recurring": False,
    }
    upd = make_update("Yes")
    with patch("handlers.quick_conv.load_rates",
               return_value={settings.DISPLAY_CURRENCY: 1.0}), \
         patch("handlers.quick_conv.get_display_currency",
               return_value=settings.DISPLAY_CURRENCY), \
         patch("handlers.quick_conv.check_budget_alert", AsyncMock()), \
         patch("handlers.quick_conv.maybe_prompt_cycle_start", AsyncMock()):
        result = await quick_conv.quick_confirm(upd, ctx)

    assert result == ConversationHandler.END
    rows = _list_rows()
    assert len(rows) == 1
    assert rows[0]["value"] == 89.0
    assert rows[0]["description"] == "shop"


# ── /edit updates through the facade + stale-row conflict ────────────────────

def _edit_ctx(row_id, value=200.0, description="taxi"):
    ctx = make_ctx()
    ctx.user_data["edit_txn"] = {
        "_row_idx": row_id, "Value": value, "Description": description,
        "Date": "2026-07-01", "Currency": settings.DISPLAY_CURRENCY,
        "Category": "Transport",
    }
    ctx.user_data["edit_field"] = "Amount"
    ctx.user_data["edit_new_value"] = 300.0
    return ctx


async def test_edit_confirm_updates_via_facade(sqlite_db):
    row_id = _seed_row()
    ctx = _edit_ctx(row_id)
    upd = make_update("Yes")
    result = await edit_conv.edit_confirm(upd, ctx)
    assert result == ConversationHandler.END
    rows = _list_rows()
    assert rows[0]["value"] == 300.0
    assert rows[0]["value_base"] == 300.0  # recomputed on value change
    assert "Updated" in upd.message.reply_text.call_args.args[0]


async def test_edit_confirm_stale_snapshot_surfaces_moved_message(sqlite_db):
    row_id = _seed_row()
    # Snapshot no longer matches the stored row (value changed underneath).
    ctx = _edit_ctx(row_id, value=999.0)
    upd = make_update("Yes")
    result = await edit_conv.edit_confirm(upd, ctx)
    assert result == ConversationHandler.END
    rows = _list_rows()
    assert rows[0]["value"] == 200.0  # untouched
    sent = upd.message.reply_text.call_args.args[0]
    assert "moved" in sent.lower()
    assert "/edit" in sent


# ── /delete deletes through the facade + stale-row conflict ──────────────────

def _delete_ctx(row_id, value=200.0):
    ctx = make_ctx()
    ctx.user_data["delete_candidates"] = [{
        "_row_idx": row_id, "Value": value, "Description": "taxi",
        "Date": "2026-07-01", "Currency": settings.DISPLAY_CURRENCY,
        "Category": "Transport",
    }]
    return ctx


async def test_delete_pick_deletes_via_facade(sqlite_db):
    row_id = _seed_row()
    ctx = _delete_ctx(row_id)
    upd = make_update("1")
    result = await delete_conv.delete_pick(upd, ctx)
    assert result == ConversationHandler.END
    assert _list_rows() == []
    assert "Deleted" in upd.message.reply_text.call_args.args[0]


async def test_delete_pick_stale_snapshot_surfaces_moved_message(sqlite_db):
    row_id = _seed_row()
    ctx = _delete_ctx(row_id, value=999.0)  # stale snapshot
    upd = make_update("1")
    result = await delete_conv.delete_pick(upd, ctx)
    assert result == ConversationHandler.END
    assert len(_list_rows()) == 1  # nothing deleted
    sent = upd.message.reply_text.call_args.args[0]
    assert "moved" in sent.lower()
    assert "/delete" in sent


async def test_delete_pick_row_gone_surfaces_moved_message(sqlite_db):
    ctx = _delete_ctx(row_id=4242)  # id that never existed
    upd = make_update("1")
    result = await delete_conv.delete_pick(upd, ctx)
    assert result == ConversationHandler.END
    sent = upd.message.reply_text.call_args.args[0]
    assert "moved" in sent.lower()


# ── Flow-level: the REAL list→pick path uses the SQLite id keyspace ───────────
#
# The tests above inject a known SQLite id straight into user_data, bypassing
# the listing step — which is how an Excel-row-index/SQLite-id keyspace
# mismatch once went unnoticed. These drive the actual /edit and /delete
# conversations end to end: list from storage, pick a number, confirm, and
# verify the write landed on the exact row the user picked.

def _seed_three():
    """Three rows on distinct dates; returns their SQLite ids oldest-first."""
    ids = [
        _seed_row(date="2026-07-01", value=10.0, description="bread"),
        _seed_row(date="2026-07-02", value=20.0, description="taxi"),
        _seed_row(date="2026-07-03", value=30.0, description="cinema"),
    ]
    return ids


async def test_edit_full_flow_targets_picked_row_by_sqlite_id(sqlite_db):
    ids = _seed_three()
    ctx = make_ctx()

    result = await edit_conv.cmd_edit(make_update("/edit"), ctx)
    assert result == edit_conv.EDIT_PICK
    # Listing came from SQLite and _row_idx IS the SQLite primary key.
    listed = ctx.user_data["edit_txns"]
    assert [t["_row_idx"] for t in listed] == ids  # oldest-first, like Excel
    assert [t["Description"] for t in listed] == ["bread", "taxi", "cinema"]

    # Pick row 2 ("taxi"), change Amount to 55, confirm.
    assert await edit_conv.edit_pick(make_update("2"), ctx) == edit_conv.EDIT_FIELD
    assert await edit_conv.edit_field(make_update("Amount"), ctx) == edit_conv.EDIT_VALUE
    assert await edit_conv.edit_value(make_update("55"), ctx) == edit_conv.EDIT_CONFIRM
    upd = make_update("Yes")
    assert await edit_conv.edit_confirm(upd, ctx) == ConversationHandler.END
    assert "Updated" in upd.message.reply_text.call_args.args[0]

    rows = {r["id"]: r for r in _list_rows()}
    assert rows[ids[1]]["value"] == 55.0          # the picked row changed
    assert rows[ids[0]]["value"] == 10.0          # neighbours untouched
    assert rows[ids[2]]["value"] == 30.0


async def test_delete_full_flow_targets_picked_row_by_sqlite_id(sqlite_db):
    ids = _seed_three()
    ctx = make_ctx()

    result = await delete_conv.cmd_delete(make_update("/delete"), ctx)
    assert result == delete_conv.DELETE_PICK
    # Delete lists newest-first; every candidate's _row_idx is a SQLite id.
    candidates = ctx.user_data["delete_candidates"]
    assert [t["_row_idx"] for t in candidates] == list(reversed(ids))

    # Pick 1 = newest ("cinema").
    upd = make_update("1")
    assert await delete_conv.delete_pick(upd, ctx) == ConversationHandler.END
    assert "Deleted" in upd.message.reply_text.call_args.args[0]
    assert sorted(r["id"] for r in _list_rows()) == sorted(ids[:2])


async def test_edit_full_flow_row_deleted_between_list_and_confirm(sqlite_db):
    """The optimistic-lock guard still fires within the SQLite keyspace."""
    ids = _seed_three()
    ctx = make_ctx()
    await edit_conv.cmd_edit(make_update("/edit"), ctx)
    await edit_conv.edit_pick(make_update("2"), ctx)
    await edit_conv.edit_field(make_update("Amount"), ctx)
    await edit_conv.edit_value(make_update("55"), ctx)

    # Someone else deletes the picked row before the user confirms.
    storage_facade.delete_transaction_row(ids[1])

    upd = make_update("Yes")
    assert await edit_conv.edit_confirm(upd, ctx) == ConversationHandler.END
    sent = upd.message.reply_text.call_args.args[0]
    assert "moved" in sent.lower() and "/edit" in sent
    # Remaining rows untouched.
    rows = {r["id"]: r for r in _list_rows()}
    assert set(rows) == {ids[0], ids[2]}
    assert rows[ids[0]]["value"] == 10.0 and rows[ids[2]]["value"] == 30.0
