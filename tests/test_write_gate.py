"""
tests/test_write_gate.py — primary-user write gate (@auth_write) and /setbudget.

Covers BACKLOG.md "Follow-up PR: primary-user write gate + /setbudget":
  1. config.auth_write itself: primary passes, non-primary rejected with the
     owner-only message, not-on-list rejected with the existing not-authorized
     message (never conflated).
  2. Every real write entry-point handler is gated by @auth_write.
  3. Read commands remain open to any allowed user regardless of primary status.
  4. /setbudget full flow: category list shows current values, setting a value
     works, negative amounts are rejected with a re-prompt, and the change
     persists and is reflected when the picker re-renders.

NOTE ON COLLECTION ORDER: tests/test_handlers_full.py is collected before this
file (alphabetically "handlers_full" < "write_gate") and permanently patches
config.auth / config.auth_write to pass-throughs, then imports handlers/*.py —
Python caches those already-decorated functions in sys.modules, so a later
plain import here would get the pass-through, not the real gate. We restore
the real auth_write (captured in tests/test_auth_config.py before that patch
ever ran, the same trick that file already uses for config.auth) and reload
the write-gated handler modules so this file exercises the actual decorator.
"""

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("ALLOWED_TELEGRAM_IDS", "111,222")

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
import file_storage

from tests.test_auth_config import _REAL_AUTH_WRITE
config.auth_write = _REAL_AUTH_WRITE

import handlers.add_conv as _add_conv_mod
import handlers.bulk_conv as _bulk_conv_mod
import handlers.delete_conv as _delete_conv_mod
import handlers.edit_conv as _edit_conv_mod
import handlers.quick_conv as _quick_conv_mod

importlib.reload(_add_conv_mod)
importlib.reload(_bulk_conv_mod)
importlib.reload(_delete_conv_mod)
importlib.reload(_edit_conv_mod)
importlib.reload(_quick_conv_mod)

from config import auth_write
from handlers.add_conv import cmd_add
from handlers.bulk_conv import cmd_bulk
from handlers.delete_conv import cmd_delete
from handlers.edit_conv import cmd_edit
from handlers.misc import cmd_setcurrency, cmd_setbudget, cmd_help, setbudget_pick, setbudget_amount
from handlers.quick_conv import handle_quick_add

PRIMARY_UID = 111
NON_PRIMARY_UID = 222
STRANGER_UID = 999999


def make_update(user_id=PRIMARY_UID, text="hello"):
    upd = MagicMock()
    upd.effective_user.id = user_id
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


# ── config.auth_write unit behavior ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_auth_write_primary_passes(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_USERS", [PRIMARY_UID, NON_PRIMARY_UID])
    handler = AsyncMock(return_value="ok")
    handler.__name__ = "handler"
    wrapped = auth_write(handler)

    update = make_update(user_id=PRIMARY_UID)
    result = await wrapped(update, make_ctx())

    handler.assert_awaited_once()
    assert result == "ok"


@pytest.mark.asyncio
async def test_auth_write_non_primary_rejected(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_USERS", [PRIMARY_UID, NON_PRIMARY_UID])
    handler = AsyncMock()
    handler.__name__ = "handler"
    wrapped = auth_write(handler)

    update = make_update(user_id=NON_PRIMARY_UID)
    await wrapped(update, make_ctx())

    handler.assert_not_awaited()
    update.message.reply_text.assert_awaited_once()
    reply = update.message.reply_text.call_args[0][0]
    assert "owner" in reply.lower()
    assert "not authorized" not in reply.lower()


@pytest.mark.asyncio
async def test_auth_write_not_on_list_rejected(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_USERS", [PRIMARY_UID, NON_PRIMARY_UID])
    handler = AsyncMock()
    handler.__name__ = "handler"
    wrapped = auth_write(handler)

    update = make_update(user_id=STRANGER_UID)
    await wrapped(update, make_ctx())

    handler.assert_not_awaited()
    update.message.reply_text.assert_awaited_once()
    reply = update.message.reply_text.call_args[0][0]
    assert "not authorized" in reply.lower()
    assert str(STRANGER_UID) in reply
    assert "owner" not in reply.lower()


# ── Every write entry point is gated ──────────────────────────────────────────

WRITE_ENTRY_POINTS = [
    ("cmd_add", cmd_add),
    ("cmd_bulk", cmd_bulk),
    ("cmd_delete", cmd_delete),
    ("cmd_edit", cmd_edit),
    ("cmd_setcurrency", cmd_setcurrency),
    ("cmd_setbudget", cmd_setbudget),
    ("handle_quick_add", handle_quick_add),
]


@pytest.mark.parametrize("name,handler", WRITE_ENTRY_POINTS)
@pytest.mark.asyncio
async def test_write_entrypoint_rejects_non_primary(name, handler, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_USERS", [PRIMARY_UID, NON_PRIMARY_UID])
    update = make_update(user_id=NON_PRIMARY_UID)
    ctx = make_ctx()

    await handler(update, ctx)

    update.message.reply_text.assert_awaited_once()
    reply = update.message.reply_text.call_args[0][0]
    assert "owner" in reply.lower(), f"{name} did not give the owner-only rejection"


@pytest.mark.parametrize("name,handler", WRITE_ENTRY_POINTS)
@pytest.mark.asyncio
async def test_write_entrypoint_rejects_stranger(name, handler, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_USERS", [PRIMARY_UID, NON_PRIMARY_UID])
    update = make_update(user_id=STRANGER_UID)
    ctx = make_ctx()

    await handler(update, ctx)

    update.message.reply_text.assert_awaited_once()
    reply = update.message.reply_text.call_args[0][0]
    assert "not authorized" in reply.lower(), f"{name} did not give the not-on-list rejection"
    assert str(STRANGER_UID) in reply


# ── Read commands remain open to any allowed user ─────────────────────────────

@pytest.mark.asyncio
async def test_read_command_works_for_non_primary(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_USERS", [PRIMARY_UID, NON_PRIMARY_UID])
    update = make_update(user_id=NON_PRIMARY_UID)
    ctx = make_ctx()

    await cmd_help(update, ctx)

    update.message.reply_text.assert_awaited_once()
    reply = update.message.reply_text.call_args[0][0]
    assert "not authorized" not in reply.lower()
    assert "only the bot owner can make changes" not in reply.lower()


# ── /setbudget full flow ──────────────────────────────────────────────────────

@pytest.fixture()
def budget_excel(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_USERS", [PRIMARY_UID, NON_PRIMARY_UID])
    path = tmp_path / "test_budget.xlsx"
    monkeypatch.setattr(file_storage, "TEMPLATE_PATH", tmp_path / "nonexistent_template.xlsx")
    file_storage.create_blank_excel(path)
    monkeypatch.setattr(file_storage, "LOCAL_XLSX_PATH", path)
    monkeypatch.setattr(file_storage, "USER_PREFS_PATH", tmp_path / "user_prefs.json")
    return path


@pytest.mark.asyncio
async def test_setbudget_full_flow(budget_excel):
    update = make_update(user_id=PRIMARY_UID)
    ctx = make_ctx()

    # Step 1: category list shows current (blank/zero) values.
    await cmd_setbudget(update, ctx)
    kb = update.message.reply_text.call_args.kwargs["reply_markup"]
    assert kb.inline_keyboard, "expected an inline keyboard of categories"
    first_button = kb.inline_keyboard[0][0]
    assert "Groceries" in first_button.text
    category = first_button.callback_data.split(":", 1)[1]

    # Step 2: tap a category button.
    cb_update = make_update(user_id=PRIMARY_UID)
    cb_update.callback_query = MagicMock()
    cb_update.callback_query.answer = AsyncMock()
    cb_update.callback_query.data = f"setbudget:{category}"
    cb_update.callback_query.message.reply_text = AsyncMock()
    await setbudget_pick(cb_update, ctx)
    assert ctx.user_data["setbudget_category"] == category

    # Step 3a: negative amount is rejected with a re-prompt, no state advance.
    neg_update = make_update(user_id=PRIMARY_UID, text="-50")
    result = await setbudget_amount(neg_update, ctx)
    neg_update.message.reply_text.assert_awaited_once()
    assert "non-negative" in neg_update.message.reply_text.call_args[0][0].lower()
    assert ctx.user_data["setbudget_category"] == category  # unchanged, still pending

    # Step 3b: valid amount is saved.
    ok_update = make_update(user_id=PRIMARY_UID, text="2100")
    await setbudget_amount(ok_update, ctx)
    calls = [c.args[0] for c in ok_update.message.reply_text.call_args_list]
    assert any("2,100" in c or "2100" in c for c in calls)

    # Persistence: re-rendering the picker shows the new value.
    update2 = make_update(user_id=PRIMARY_UID)
    ctx2 = make_ctx()
    await cmd_setbudget(update2, ctx2)
    kb2 = update2.message.reply_text.call_args.kwargs["reply_markup"]
    labels = " ".join(b.text for row in kb2.inline_keyboard for b in row)
    assert f"{category} — 2,100 PLN" in labels
