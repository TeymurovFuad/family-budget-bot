"""
tests/test_setup_conv.py — unit tests for the remove-category flow in
handlers/setup_conv.py.

Covers:
1. Happy path: tapping setup:remove shows picker (SETUP_REMOVE state).
2. Guard: when only 1 category remains, shows error and stays on SETUP_REVIEW.
3. Deletion: setup:del:<idx> removes the category, clears its budget, shows review.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("ALLOWED_TELEGRAM_IDS", "")

from states import SETUP_REMOVE, SETUP_REVIEW
from handlers.setup_conv import (
    _session,
    setup_review_cb,
    setup_remove_cb,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_ctx(categories=None, budgets=None):
    """Return a minimal fake context with a pre-populated session."""
    ctx = MagicMock()
    ctx.user_data = {}
    s = _session(ctx)
    s["categories"] = list(categories or [("Groceries", "Expense"), ("Housing", "Expense")])
    s["budgets"] = dict(budgets or {"Groceries": 200.0, "Housing": 500.0})
    return ctx


def _make_update(callback_data: str):
    """Return a fake Update whose callback_query carries callback_data."""
    query = MagicMock()
    query.answer = AsyncMock()
    query.data = callback_data
    query.message = MagicMock()
    query.message.reply_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    update.message = query.message
    update.effective_user = MagicMock()
    return update


# ── tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remove_shows_picker():
    """setup:remove with 2 categories transitions to SETUP_REMOVE."""
    ctx = _make_ctx()
    update = _make_update("setup:remove")

    result = await setup_review_cb(update, ctx)

    assert result == SETUP_REMOVE
    update.callback_query.message.reply_text.assert_awaited_once()
    call_kwargs = update.callback_query.message.reply_text.call_args
    assert "remove" in call_kwargs[0][0].lower() or "tap" in call_kwargs[0][0].lower()


@pytest.mark.asyncio
async def test_remove_guard_single_category():
    """setup:remove with only 1 category shows error and stays on SETUP_REVIEW."""
    ctx = _make_ctx(categories=[("Groceries", "Expense")], budgets={})
    update = _make_update("setup:remove")

    # _show_review also calls reply_text; intercept all calls
    result = await setup_review_cb(update, ctx)

    assert result == SETUP_REVIEW
    # First reply should be the error message
    first_call = update.callback_query.message.reply_text.call_args_list[0]
    assert "1 category" in first_call[0][0] or "at least" in first_call[0][0]


@pytest.mark.asyncio
async def test_remove_deletes_category_and_budget():
    """setup:del:0 removes the first category and its budget, returns SETUP_REVIEW."""
    ctx = _make_ctx(
        categories=[("Groceries", "Expense"), ("Housing", "Expense")],
        budgets={"Groceries": 200.0, "Housing": 500.0},
    )
    update = _make_update("setup:del:0")

    result = await setup_remove_cb(update, ctx)

    assert result == SETUP_REVIEW
    session = _session(ctx)
    names = [n for n, _ in session["categories"]]
    assert "Groceries" not in names
    assert "Housing" in names
    assert "Groceries" not in session["budgets"]
    assert session["budgets"].get("Housing") == 500.0
