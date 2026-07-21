"""
tests/test_export.py — Unit tests for handlers.misc.cmd_export (/export command).

Tests:
1. Authorised user gets the workbook sent back as a document.
2. Unauthorised user is rejected by the @auth decorator.
3. Missing workbook file produces a friendly error, no crash.
4. Unexpected exception during export is caught and reported, no crash.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("ALLOWED_TELEGRAM_IDS", "")  # empty = allow all (test mode)

from handlers.misc import cmd_export


def _make_update(user_id: int = 123):
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.reply_text = AsyncMock()
    update.message.reply_document = AsyncMock()
    return update


def _make_ctx():
    ctx = MagicMock()
    ctx.args = []
    return ctx


@pytest.mark.asyncio
async def test_cmd_export_sends_document(tmp_path):
    fake_path = tmp_path / "Expenses_Improved.xlsx"
    fake_path.write_bytes(b"fake xlsx bytes")

    update = _make_update()
    ctx = _make_ctx()

    with patch("handlers.misc.get_excel_path_for_reading", return_value=fake_path):
        await cmd_export(update, ctx)

    update.message.reply_document.assert_awaited_once()
    _, kwargs = update.message.reply_document.call_args
    assert kwargs["filename"].startswith("Expenses_Improved_")
    assert kwargs["filename"].endswith(".xlsx")
    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_cmd_export_missing_file(tmp_path):
    missing_path = tmp_path / "does_not_exist.xlsx"

    update = _make_update()
    ctx = _make_ctx()

    with patch("handlers.misc.get_excel_path_for_reading", return_value=missing_path):
        await cmd_export(update, ctx)

    update.message.reply_document.assert_not_called()
    update.message.reply_text.assert_awaited_once()
    assert "not found" in update.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_cmd_export_handles_unexpected_error(tmp_path):
    update = _make_update()
    ctx = _make_ctx()

    with patch("handlers.misc.get_excel_path_for_reading", side_effect=RuntimeError("boom")):
        await cmd_export(update, ctx)

    update.message.reply_document.assert_not_called()
    update.message.reply_text.assert_awaited_once()
    msg = update.message.reply_text.call_args[0][0]
    assert "could not export" in msg.lower()


@pytest.mark.asyncio
async def test_cmd_export_unauthorised_user_rejected(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "ALLOWED_USERS", {999})

    # cmd_export is wrapped by @auth at import time using the config module's
    # ALLOWED_USERS reference captured in its closure, so patch the auth check
    # by re-importing is unnecessary — @auth reads config.ALLOWED_USERS live.
    update = _make_update(user_id=123)
    ctx = _make_ctx()

    with patch("handlers.misc.get_excel_path_for_reading") as mocked:
        await cmd_export(update, ctx)
        mocked.assert_not_called()

    update.message.reply_text.assert_awaited_once()
    reply = update.message.reply_text.call_args[0][0]
    assert "not authorized" in reply.lower()
    assert "123" in reply  # the unauthorized user's own Telegram ID
