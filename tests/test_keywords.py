"""
tests/test_keywords.py — salary keywords stored in SQLite and the /keywords
management command.  Excel-specific sheet-level tests have been removed;
logic tests remain, backed by the storage_facade SQLite layer.
"""

import asyncio
import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("ALLOWED_TELEGRAM_IDS", "123")

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import settings
import cycles
from cycles import cycle_detect_keywords
from storage_facade import (
    async_delete_salary_keyword, async_save_salary_keyword, load_salary_keywords,
)
from telegram.ext import ConversationHandler


# ── Sync test helpers ─────────────────────────────────────────────────────────

def save_salary_keyword(word: str) -> bool:
    """Sync wrapper: validate + save to SQLite (mirrors handler-level checks)."""
    if not word or not word.strip():
        return False
    w = word.strip().lower()
    if len(w.encode("utf-8")) > cycles.MAX_SALARY_KEYWORD_BYTES:
        return False
    return asyncio.run(async_save_salary_keyword(w))


def delete_salary_keyword(word: str) -> bool:
    """Sync wrapper: delete from SQLite."""
    return asyncio.run(async_delete_salary_keyword(word))
from handlers.misc import cmd_keywords, keywords_add_word, keywords_callback
from states import KW_ADD, KW_PICK


def make_update(text="", user_id=123):
    upd = MagicMock()
    upd.effective_user.id = user_id
    upd.message.text = text
    upd.message.reply_text = AsyncMock()
    return upd


def make_callback_update(data, user_id=123):
    upd = MagicMock()
    upd.effective_user.id = user_id
    upd.message = None
    upd.callback_query.data = data
    upd.callback_query.from_user.id = user_id
    upd.callback_query.answer = AsyncMock()
    upd.callback_query.message.reply_text = AsyncMock()
    return upd


def make_ctx(args=None):
    ctx = MagicMock()
    ctx.args = args or []
    ctx.user_data = {}
    return ctx


def _keyword_column_cells(path):
    wb = load_workbook(path)
    ws = wb["Lists"]
    kw_col = col_indices(ws, ListsSchema)["salary_keyword"]
    return [ws.cell(r, kw_col).value for r in range(2, ws.max_row + 1)]


# ── load_salary_keywords ───────────────────────────────────────────────────────

def test_load_empty_returns_empty():
    """Fresh DB has no stored keywords."""
    assert load_salary_keywords() == []


# ── save / delete ──────────────────────────────────────────────────────────────

def test_save_duplicate_is_noop(excel_path, monkeypatch):
    monkeypatch.setattr(settings, "CYCLE_DETECT_KEYWORDS", [])
    assert save_salary_keyword("payroll") is True
    assert save_salary_keyword("  PAYROLL ") is False
    assert load_salary_keywords() == ["payroll"]


def test_save_blank_is_rejected(excel_path):
    assert save_salary_keyword("   ") is False


def test_save_overlong_keyword_is_rejected(excel_path):
    assert save_salary_keyword("x" * (cycles.MAX_SALARY_KEYWORD_BYTES + 1)) is False
    assert save_salary_keyword("ż" * 30) is False  # 60 UTF-8 bytes — byte limit, not chars
    assert load_salary_keywords() == []


def test_save_and_delete_roundtrip(excel_path):
    assert save_salary_keyword("payroll") is True
    assert save_salary_keyword("bonus") is True
    assert load_salary_keywords() == ["payroll", "bonus"]
    assert delete_salary_keyword("payroll") is True
    assert load_salary_keywords() == ["bonus"]
    assert delete_salary_keyword("payroll") is False  # already removed


def test_delete_unknown_keyword_returns_false(excel_path):
    assert delete_salary_keyword("nope") is False


# ── cycle_detect_keywords fallback ─────────────────────────────────────────────

def test_detect_keywords_fall_back_to_env(excel_path, monkeypatch):
    monkeypatch.setattr(settings, "CYCLE_DETECT_KEYWORDS", ["wages"])
    assert cycle_detect_keywords() == ["salary", "wages"]


def test_detect_keywords_prefer_sqlite_over_env(excel_path, monkeypatch):
    monkeypatch.setattr(settings, "CYCLE_DETECT_KEYWORDS", ["ignored"])
    save_salary_keyword("payroll")
    assert cycle_detect_keywords() == ["salary", "payroll"]


# ── /keywords command ──────────────────────────────────────────────────────────

# NOTE: the @auth_write gate on cmd_keywords is covered in tests/test_write_gate.py
# (WRITE_ENTRY_POINTS) — collection-order patching in test_handlers_full.py makes
# gate assertions unreliable in any file collected after it.

async def test_cmd_keywords_help(excel_path):
    upd = make_update()
    result = await cmd_keywords(upd, make_ctx(["help"]))
    assert "/keywords" in upd.message.reply_text.call_args[0][0]
    assert result == ConversationHandler.END


async def test_cmd_keywords_shows_env_fallback_source(excel_path, monkeypatch):
    monkeypatch.setattr(settings, "CYCLE_DETECT_KEYWORDS", ["payroll"])
    upd = make_update()
    state = await cmd_keywords(upd, make_ctx())
    assert state == KW_PICK
    text = upd.message.reply_text.call_args[0][0]
    assert ".env fallback" in text and "payroll" in text
    markup = upd.message.reply_text.call_args.kwargs["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert callbacks == ["kw:add"]  # env words get no delete buttons


async def test_cmd_keywords_shows_excel_keywords_with_delete_buttons(excel_path, monkeypatch):
    monkeypatch.setattr(settings, "CYCLE_DETECT_KEYWORDS", [])
    await async_save_salary_keyword("payroll")
    await async_save_salary_keyword("bonus")
    upd = make_update()
    await cmd_keywords(upd, make_ctx())
    text = upd.message.reply_text.call_args[0][0]
    assert "Excel" in text
    markup = upd.message.reply_text.call_args.kwargs["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert callbacks == ["kw:del:payroll", "kw:del:bonus", "kw:add"]


# ── add flow ───────────────────────────────────────────────────────────────────

async def test_keywords_add_flow(excel_path, monkeypatch):
    monkeypatch.setattr(settings, "CYCLE_DETECT_KEYWORDS", [])
    upd = make_callback_update("kw:add")
    state = await keywords_callback(upd, make_ctx())
    assert state == KW_ADD
    assert "Send the new salary keyword" in upd.callback_query.message.reply_text.call_args[0][0]

    msg = make_update("  Premia ")
    state = await keywords_add_word(msg, make_ctx())
    assert state == KW_PICK
    assert load_salary_keywords() == ["premia"]
    text = msg.message.reply_text.call_args[0][0]
    assert "Added 'premia'" in text


async def test_keywords_add_overlong_word_reprompts(excel_path):
    msg = make_update("x" * (cycles.MAX_SALARY_KEYWORD_BYTES + 1))
    state = await keywords_add_word(msg, make_ctx())
    assert state == KW_ADD
    assert "too long" in msg.message.reply_text.call_args[0][0]
    assert load_salary_keywords() == []


async def test_keywords_add_duplicate_reports_noop(excel_path, monkeypatch):
    monkeypatch.setattr(settings, "CYCLE_DETECT_KEYWORDS", [])
    await async_save_salary_keyword("payroll")
    msg = make_update("payroll")
    state = await keywords_add_word(msg, make_ctx())
    assert state == KW_PICK
    assert "already in the list" in msg.message.reply_text.call_args[0][0]
    assert load_salary_keywords() == ["payroll"]


# ── delete flow ────────────────────────────────────────────────────────────────

async def test_keywords_delete_flow(excel_path, monkeypatch):
    monkeypatch.setattr(settings, "CYCLE_DETECT_KEYWORDS", [])
    await async_save_salary_keyword("payroll")
    await async_save_salary_keyword("bonus")
    upd = make_callback_update("kw:del:payroll")
    state = await keywords_callback(upd, make_ctx())
    assert state == KW_PICK
    assert "Removed 'payroll'" in upd.callback_query.message.reply_text.call_args[0][0]
    assert load_salary_keywords() == ["bonus"]


async def test_keywords_delete_unknown_word(excel_path):
    upd = make_callback_update("kw:del:ghost")
    state = await keywords_callback(upd, make_ctx())
    assert state == KW_PICK
    assert "not in the list" in upd.callback_query.message.reply_text.call_args[0][0]


# ── fallback-chain integration (Fix 5) ────────────────────────────────────────

def _make_salary_transaction(description="", category="", txn_date=None):
    t = MagicMock()
    t.transaction_type = "Income"
    t.category = category
    t.description = description
    t.date = txn_date or date(2026, 7, 1)
    return t


async def test_fallback_env_keywords_when_excel_empty(excel_path, monkeypatch):
    """With no Excel keywords, an env keyword in Description triggers the prompt."""
    import settings
    monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
    monkeypatch.setattr(settings, "CYCLE_DETECT_KEYWORDS", ["payroll"])

    # Excel keywords column is absent — load_salary_keywords returns []
    assert load_salary_keywords() == []

    upd = make_update()
    txn = _make_salary_transaction(description="payroll april", category="")
    from handlers.cycle import maybe_prompt_cycle_start
    await maybe_prompt_cycle_start(upd, txn)
    upd.message.reply_text.assert_called_once()
    assert "Salary received" in upd.message.reply_text.call_args[0][0]


async def test_sqlite_keywords_override_env(excel_path, monkeypatch):
    """When SQLite keywords are present, env keywords are ignored;
    only the stored keyword triggers the prompt."""
    import settings
    monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
    monkeypatch.setattr(settings, "CYCLE_DETECT_KEYWORDS", ["envonly"])

    await async_save_salary_keyword("storedword")
    assert load_salary_keywords() == ["storedword"]

    upd_stored = make_update()
    txn_stored = _make_salary_transaction(description="storedword april", category="")
    from handlers.cycle import maybe_prompt_cycle_start
    await maybe_prompt_cycle_start(upd_stored, txn_stored)
    upd_stored.message.reply_text.assert_called_once()
    assert "Salary received" in upd_stored.message.reply_text.call_args[0][0]

    # env keyword "envonly" is NOT in SQLite — superseded, must NOT trigger.
    upd_env = make_update()
    txn_env = _make_salary_transaction(description="envonly march", category="")
    await maybe_prompt_cycle_start(upd_env, txn_env)
    upd_env.message.reply_text.assert_not_called()
