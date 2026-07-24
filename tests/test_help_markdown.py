"""
tests/test_help_markdown.py — /help must always produce valid MarkdownV2.

This exact bug class shipped twice (unescaped chars silently killing /help
with a Telegram BadRequest the user never sees): PR #32 fixed one instance,
another shipped in the same PR. This validator catches any reserved character
left unescaped outside code spans before it reaches Telegram.
"""

import os
import re
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
from handlers.misc import cmd_help

# Telegram MarkdownV2 reserved characters that must be escaped in plain text.
# '*' and '_' are excluded here because the help text legitimately uses them
# as bold/italic markup — balance is asserted separately.
_RESERVED = set("[]()~>#+-=|{}.!")


def _find_unescaped_reserved(text: str) -> list[str]:
    problems = []
    # Remove escaped characters first, then code spans — what remains must
    # contain no reserved characters at all.
    without_escapes = re.sub(r"\\.", "", text)
    without_code = re.sub(r"`[^`]*`", "", without_escapes)
    for i, ch in enumerate(without_code):
        if ch in _RESERVED:
            context = without_code[max(0, i - 25):i + 25].replace("\n", "⏎")
            problems.append(f"unescaped {ch!r} near: …{context}…")
    return problems


def make_update(user_id=111):
    upd = MagicMock()
    upd.effective_user.id = user_id
    upd.effective_user.first_name = "Tester"
    upd.message.text = "/help"
    upd.message.reply_text = AsyncMock()
    upd.callback_query = None
    return upd


def make_ctx():
    ctx = MagicMock()
    ctx.args = []
    ctx.user_data = {}
    return ctx


@pytest.mark.asyncio
async def test_help_text_is_valid_markdown_v2(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_USERS", [111])
    update = make_update()

    await cmd_help(update, make_ctx())

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert update.message.reply_text.call_args[1].get("parse_mode") == "MarkdownV2"

    problems = _find_unescaped_reserved(text)
    assert not problems, "MarkdownV2 violations in /help:\n" + "\n".join(problems)

    # Bold/italic markers and code fences must be balanced.
    without_escapes = re.sub(r"\\.", "", text)
    assert without_escapes.count("`") % 2 == 0, "unbalanced backticks"
    assert without_escapes.count("*") % 2 == 0, "unbalanced asterisks"
    assert re.sub(r"`[^`]*`", "", without_escapes).count("_") % 2 == 0, "unbalanced underscores"
