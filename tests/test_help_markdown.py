"""
tests/test_help_markdown.py — every static MarkdownV2 reply must be valid.

This exact bug class shipped twice (unescaped chars silently killing /help
with a Telegram BadRequest the user never sees): PR #32 fixed one instance,
another shipped in the same PR. The shared validator in tests/mdv2_helpers.py
catches any reserved character left unescaped outside code spans before it
reaches Telegram. Covered here: /help, /start, /setcurrency's unknown-currency
reply, and every `<cmd> help` subcommand text.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("ALLOWED_TELEGRAM_IDS", "111")

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
import handlers.misc
from handlers.misc import cmd_help, cmd_start
from handlers.cycle import (
    _CYCLES_DISABLED_MSG,
    _NOTHING_TO_BACKFILL_MSG,
    _BACKFILL_COMPLETE_REVIEWED_MSG,
    _BACKFILL_COMPLETE_RECORDED_MSG,
    _DETECT_CANCELLED_MSG,
    _DETECT_CUSTOM_DATE_MSG,
)

from tests.mdv2_helpers import (
    assert_valid_markdown_v2,
    find_unescaped_reserved,
)


def make_update(user_id=111):
    upd = MagicMock()
    upd.effective_user.id = user_id
    upd.effective_user.first_name = "Tester"
    upd.message.text = "/help"
    upd.message.reply_text = AsyncMock()
    upd.callback_query = None
    return upd


def make_ctx(args=None):
    ctx = MagicMock()
    ctx.args = args or []
    ctx.user_data = {}
    return ctx


def _get_reply(update) -> str:
    """Assert exactly one MarkdownV2 reply was sent and return its text."""
    update.message.reply_text.assert_awaited_once()
    assert update.message.reply_text.call_args[1].get("parse_mode") == "MarkdownV2"
    return update.message.reply_text.call_args[0][0]


# ── /help and /start ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_help_text_is_valid_markdown_v2(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_USERS", [111])
    update = make_update()

    await cmd_help(update, make_ctx())

    assert_valid_markdown_v2(_get_reply(update), "/help")


@pytest.mark.asyncio
async def test_start_escapes_hostile_first_name(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_USERS", [111])
    monkeypatch.setattr(handlers.misc, "get_display_currency", lambda uid: "EUR")
    update = make_update()
    update.effective_user.first_name = "Mr. Dot-Dash_Underscore!"

    await cmd_start(update, make_ctx())

    assert_valid_markdown_v2(_get_reply(update), "/start")


@pytest.mark.asyncio
async def test_start_empty_first_name_falls_back_to_there(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_USERS", [111])
    monkeypatch.setattr(handlers.misc, "get_display_currency", lambda uid: "EUR")
    update = make_update()
    update.effective_user.first_name = None

    await cmd_start(update, make_ctx())

    text = _get_reply(update)
    assert "there" in text
    assert_valid_markdown_v2(text, "/start (no first name)")


# ── /setcurrency unknown-currency reply ───────────────────────────────────────

@pytest.mark.asyncio
async def test_setcurrency_unknown_currency_reply_is_valid_markdown_v2(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_USERS", [111])
    monkeypatch.setattr(
        handlers.misc, "load_rates", lambda: {"PLN": 1.0, "EUR": 4.3, "USD": 3.9}
    )
    monkeypatch.setattr(handlers.misc, "get_display_currency", lambda uid: "PLN")
    update = make_update()

    await handlers.misc.cmd_setcurrency(update, make_ctx(args=["XYZ"]))

    text = _get_reply(update)
    assert "XYZ" in text
    assert_valid_markdown_v2(text, "/setcurrency unknown currency")


# ── every `<cmd> help` subcommand text ────────────────────────────────────────

def _help_handlers():
    """(id, module name, handler name) for every command with a help branch."""
    return [
        ("setcurrency", "handlers.misc", "cmd_setcurrency"),
        ("export", "handlers.misc", "cmd_export"),
        ("setbudget", "handlers.misc", "cmd_setbudget"),
        ("keywords", "handlers.misc", "cmd_keywords"),
        ("add", "handlers.add_conv", "cmd_add"),
        ("delete", "handlers.delete_conv", "cmd_delete"),
        ("edit", "handlers.edit_conv", "cmd_edit"),
        ("bulk", "handlers.bulk_conv", "cmd_bulk"),
        ("summary", "handlers.reports", "cmd_summary"),
        ("week", "handlers.reports", "cmd_week"),
        ("budget", "handlers.reports", "cmd_budget"),
        ("top", "handlers.reports", "cmd_top"),
        ("savings", "handlers.reports", "cmd_savings"),
        ("report", "handlers.reports", "cmd_report"),
        ("rates", "handlers.reports", "cmd_rates"),
        ("chart", "handlers.reports", "cmd_chart"),
        ("range", "handlers.reports", "cmd_range"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "module_name,handler_name",
    [pytest.param(m, h, id=i) for i, m, h in _help_handlers()],
)
async def test_cmd_help_subcommand_is_valid_markdown_v2(
    monkeypatch, module_name, handler_name
):
    import importlib

    module = importlib.import_module(module_name)
    handler = getattr(module, handler_name)
    monkeypatch.setattr(config, "ALLOWED_USERS", [111])
    update = make_update()

    await handler(update, make_ctx(args=["help"]))

    assert_valid_markdown_v2(_get_reply(update), f"/{handler_name} help")


# ── additional static MarkdownV2 strings ─────────────────────────────────────

@pytest.mark.parametrize(
    "label,text",
    [
        ("cycle/cycles-disabled", _CYCLES_DISABLED_MSG),
        ("cycle/nothing-to-backfill", _NOTHING_TO_BACKFILL_MSG),
        ("cycle/backfill-complete-reviewed", _BACKFILL_COMPLETE_REVIEWED_MSG),
        ("cycle/backfill-complete-recorded", _BACKFILL_COMPLETE_RECORDED_MSG),
        ("cycle/detect-cancelled", _DETECT_CANCELLED_MSG),
        ("cycle/detect-custom-date", _DETECT_CUSTOM_DATE_MSG),
    ],
)
def test_static_markdownv2_strings_are_valid(label, text):
    assert_valid_markdown_v2(text, label)


# ── validator self-tests ──────────────────────────────────────────────────────

def test_validator_flags_unescaped_reserved_chars():
    assert find_unescaped_reserved("bad dot.") != []
    assert find_unescaped_reserved("ok dot\\.") == []
    assert find_unescaped_reserved("`dot . in code` fine") == []


def test_validator_escaped_backtick_inside_code_span():
    """Regression: a legal '\\`' inside a code span must not toggle code-span
    state — escape pairs are consumed in the same pass that locates spans, so
    the remaining backticks stay correctly paired."""
    text = "start `code \\` span (raw) chars.` end\\."
    assert_valid_markdown_v2(text, "escaped backtick in code span")

    # Reserved chars after such a span are still outside code and must flag.
    bad = "`a \\` b` then (bad)"
    problems = find_unescaped_reserved(bad)
    assert any("'('" in p for p in problems), problems


def test_validator_flags_unbalanced_markup():
    with pytest.raises(AssertionError):
        assert_valid_markdown_v2("*bold `code` unclosed")
    with pytest.raises(AssertionError):
        assert_valid_markdown_v2("odd `backtick")
