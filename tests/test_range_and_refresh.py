"""
tests/test_range_and_refresh.py

Tests for:
  - test_rates_refresh_uses_follow_redirects
  - test_range_report_this_month_returns_data
  - test_range_preset_callback_routes_correctly
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("ALLOWED_TELEGRAM_IDS", "123")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_update(text: str = "", user_id: int = 123):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.first_name = "Test"
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.reply_photo = AsyncMock()
    return update


def _make_ctx(args=None):
    ctx = MagicMock()
    ctx.args = args or []
    ctx.user_data = {}
    return ctx


def _sample_df():
    """Return a minimal DataFrame with one expense row for this month."""
    today = date.today()
    from data import month_name
    return pd.DataFrame([{
        "Date": pd.Timestamp(today.year, today.month, 1),
        "Year":  today.year,
        "Month": month_name(today.month),
        "Type":  "Expense",
        "Category": "Groceries",
        "Value": 100.0,
        "_base":  100.0,
        "IsDone": True,
        "Currency": "PLN",
        "Person": "Test",
        "Description": "test row",
    }])


# ── test_rates_refresh_uses_follow_redirects ──────────────────────────────────

@pytest.mark.asyncio
async def test_rates_refresh_uses_follow_redirects():
    """cmd_rates must use httpx with follow_redirects=True and hit frankfurter.dev first."""
    from handlers.reports import cmd_rates

    update = _make_update()
    ctx    = _make_ctx(args=["refresh"])

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"date": "2026-06-29", "rates": {"EUR": 0.2336, "USD": 0.2532}}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__  = AsyncMock(return_value=False)

    with patch("handlers.reports.load_rates", return_value={"EUR": 4.28, "USD": 3.95, "PLN": 1.0}), \
         patch("handlers.reports.async_update_currency_rates", new_callable=AsyncMock), \
         patch("httpx.AsyncClient", return_value=mock_client) as mock_async_client_cls:

        await cmd_rates(update, ctx)

    # Verify AsyncClient was constructed with follow_redirects=True
    call_kwargs = mock_async_client_cls.call_args
    assert call_kwargs is not None, "httpx.AsyncClient was never instantiated"
    assert call_kwargs.kwargs.get("follow_redirects") is True, (
        f"Expected follow_redirects=True, got: {call_kwargs.kwargs}"
    )

    # Verify the primary frankfurter.dev URL was the first get() call
    first_url = mock_client.get.call_args_list[0].args[0]
    assert "frankfurter.dev" in first_url, (
        f"Expected primary URL to contain 'frankfurter.dev', got: {first_url}"
    )


# ── test_range_report_this_month_returns_data ─────────────────────────────────

@pytest.mark.asyncio
async def test_range_report_this_month_returns_data():
    """handle_range_callback for 'this_month' should filter to current month and reply."""
    from handlers.reports import handle_range_callback

    query = MagicMock()
    query.answer = AsyncMock()
    query.from_user.id = 123
    query.data = "range:this_month"
    query.message.reply_text = AsyncMock()

    update = MagicMock()
    update.callback_query = query
    ctx = _make_ctx()

    df = _sample_df()

    with patch("handlers.reports.load_data",    return_value=df), \
         patch("handlers.reports.load_rates",   return_value={"PLN": 1.0}), \
         patch("handlers.reports.load_budgets", return_value={}), \
         patch("handlers.reports.get_display_currency", return_value="PLN"):

        await handle_range_callback(update, ctx)

    query.answer.assert_called_once()
    query.message.reply_text.assert_called_once()
    reply_text = query.message.reply_text.call_args.args[0]
    assert "Range Report" in reply_text, f"Expected 'Range Report' in reply, got: {reply_text!r}"
    assert "This month" in reply_text,   f"Expected 'This month' in reply, got: {reply_text!r}"


# ── test_range_preset_callback_routes_correctly ───────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("callback_data,expected_label", [
    ("range:this_month",   "This month"),
    ("range:last_month",   "Last month"),
    ("range:last_3_months","Last 3 months"),
    ("range:last_6_months","Last 6 months"),
    ("range:this_year",    str(date.today().year)),
])
async def test_range_preset_callback_routes_correctly(callback_data, expected_label):
    """Each preset callback_data should produce a report containing the expected label."""
    from handlers.reports import handle_range_callback

    query = MagicMock()
    query.answer = AsyncMock()
    query.from_user.id = 123
    query.data = callback_data
    query.message.reply_text = AsyncMock()

    update = MagicMock()
    update.callback_query = query
    ctx = _make_ctx()

    # Build a df that spans the last 12 months so all ranges can find data
    today = date.today()
    rows = []
    from data import month_name
    for delta in range(365):
        d = today - timedelta(days=delta)
        rows.append({
            "Date": pd.Timestamp(d.year, d.month, d.day),
            "Year":  d.year,
            "Month": month_name(d.month),
            "Type":  "Expense",
            "Category": "Groceries",
            "Value": 50.0,
            "_base":  50.0,
            "IsDone": True,
            "Currency": "PLN",
            "Person": "Test",
            "Description": "x",
        })
    df = pd.DataFrame(rows)

    with patch("handlers.reports.load_data",    return_value=df), \
         patch("handlers.reports.load_rates",   return_value={"PLN": 1.0}), \
         patch("handlers.reports.load_budgets", return_value={}), \
         patch("handlers.reports.get_display_currency", return_value="PLN"):

        await handle_range_callback(update, ctx)

    query.answer.assert_called_once()
    query.message.reply_text.assert_called_once()
    reply_text = query.message.reply_text.call_args.args[0]
    assert expected_label in reply_text, (
        f"Expected label '{expected_label}' in reply for {callback_data!r}, got: {reply_text!r}"
    )


@pytest.mark.asyncio
async def test_range_custom_sets_awaiting_flag():
    """'Custom…' callback should set awaiting_range flag and prompt for input."""
    from handlers.reports import handle_range_callback

    query = MagicMock()
    query.answer = AsyncMock()
    query.from_user.id = 123
    query.data = "range:custom"
    query.message.reply_text = AsyncMock()

    update = MagicMock()
    update.callback_query = query
    ctx = _make_ctx()

    await handle_range_callback(update, ctx)

    assert ctx.user_data.get("awaiting_range") is True
    query.message.reply_text.assert_called_once()
    prompt = query.message.reply_text.call_args.args[0]
    assert "YYYY-MM-DD" in prompt
