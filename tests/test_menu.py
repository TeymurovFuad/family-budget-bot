"""
tests/test_menu.py — Unit tests for handlers/menu.py.

Tests:
1. MAIN_MENU keyboard buttons are correctly defined.
2. handle_menu_buttons routes "📊 Reports" → REPORTS_MENU.
3. handle_menu_buttons routes "← Back" → MAIN_MENU.
4. MENU_BUTTON_FILTER only matches known button texts.
5. handle_menu_buttons routes "⚙️ More" → MORE_MENU.
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

from handlers.menu import (
    MAIN_MENU, REPORTS_MENU, MORE_MENU, MENU_BUTTON_FILTER,
    handle_menu_buttons, cmd_menu,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_update(text: str, user_id: int = 123):
    """Build a minimal mock Update with a message containing the given text."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.first_name = "Test"
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.reply_photo = AsyncMock()
    return update


def _make_ctx():
    ctx = MagicMock()
    ctx.args = []
    ctx.user_data = {}
    return ctx


# ── Test 1: MAIN_MENU buttons are correctly defined ───────────────────────────

def test_main_menu_buttons():
    """MAIN_MENU must contain the main entry, import, delete and nav buttons."""
    buttons = {btn.text for row in MAIN_MENU.keyboard for btn in row}
    assert "➕ Add" in buttons
    assert "📥 Import" in buttons
    assert "🗑 Delete" in buttons
    assert "📊 Reports" in buttons
    assert "⚙️ More" in buttons


def test_reports_menu_buttons():
    """REPORTS_MENU must contain all report buttons plus Range and Back."""
    all_texts = {btn.text for row in REPORTS_MENU.keyboard for btn in row}
    expected = {
        "📅 Summary", "📆 Week", "💰 Budget",
        "🏆 Top", "💾 Savings", "📋 Report",
        "📊 Chart", "📅 Range", "← Back",
    }
    assert expected == all_texts


def test_more_menu_buttons():
    """MORE_MENU must contain Rates, Rates Refresh, Edit Last, and Back."""
    all_texts = {btn.text for row in MORE_MENU.keyboard for btn in row}
    assert "💱 Rates" in all_texts
    assert "🔄 Rates Refresh" in all_texts
    assert "✏️ Edit Last" in all_texts
    assert "← Back" in all_texts


# ── Test 2: "📊 Reports" routes to REPORTS_MENU ───────────────────────────────

@pytest.mark.asyncio
async def test_handle_menu_buttons_reports():
    """Tapping '📊 Reports' should reply with REPORTS_MENU."""
    update = _make_update("📊 Reports")
    ctx = _make_ctx()

    await handle_menu_buttons(update, ctx)

    update.message.reply_text.assert_called_once()
    call_kwargs = update.message.reply_text.call_args
    assert call_kwargs.kwargs.get("reply_markup") is REPORTS_MENU


# ── Test 3: "← Back" routes to MAIN_MENU ─────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_menu_buttons_back():
    """Tapping '← Back' should reply with MAIN_MENU."""
    update = _make_update("← Back")
    ctx = _make_ctx()

    await handle_menu_buttons(update, ctx)

    update.message.reply_text.assert_called_once()
    call_kwargs = update.message.reply_text.call_args
    assert call_kwargs.kwargs.get("reply_markup") is MAIN_MENU


# ── Test 4: MENU_BUTTON_FILTER only matches known buttons ─────────────────────

def test_menu_button_filter_matches_known():
    """MENU_BUTTON_FILTER should match known button texts including new buttons."""
    for label in ("➕ Add", "📊 Reports", "⚙️ More", "← Back", "📅 Summary",
                  "💱 Rates", "🔄 Rates Refresh", "📅 Range"):
        msg = MagicMock()
        msg.text = label
        assert MENU_BUTTON_FILTER.filter(msg), f"Expected filter to match '{label}'"


def test_menu_button_filter_rejects_unknown():
    """MENU_BUTTON_FILTER should NOT match arbitrary text."""
    for text in ("groceries 89 PLN", "hello", "/start", "", "random text"):
        msg = MagicMock()
        msg.text = text
        assert not MENU_BUTTON_FILTER.filter(msg), f"Expected filter to reject '{text}'"


# ── Test 5: "⚙️ More" routes to MORE_MENU ────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_menu_buttons_more():
    """Tapping '⚙️ More' should reply with MORE_MENU."""
    update = _make_update("⚙️ More")
    ctx = _make_ctx()

    await handle_menu_buttons(update, ctx)

    update.message.reply_text.assert_called_once()
    call_kwargs = update.message.reply_text.call_args
    assert call_kwargs.kwargs.get("reply_markup") is MORE_MENU


# ── Test 6: is_persistent flag is set ────────────────────────────────────────

def test_menus_are_persistent():
    """All three menus must have is_persistent=True and resize_keyboard=True."""
    for name, menu in [("MAIN_MENU", MAIN_MENU), ("REPORTS_MENU", REPORTS_MENU), ("MORE_MENU", MORE_MENU)]:
        assert menu.is_persistent, f"{name} must have is_persistent=True"
        assert menu.resize_keyboard, f"{name} must have resize_keyboard=True"
