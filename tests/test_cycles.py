"""
tests/test_cycles.py — budget-cycles core: settings flag, Cycles sheet ledger,
/cycle handler, salary-triggered prompt, and cycle-scoped /summary.

No AI calls anywhere in this feature — nothing to mock on that front.
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("ALLOWED_TELEGRAM_IDS", "123")

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import settings
import cycles
from cycles import (
    CYCLES_SHEET_NAME, cycle_label, cycle_totals, current_cycle_start,
    ensure_cycles_sheet, load_cycles, record_cycle_start, should_prompt_new_cycle,
)
from excel_schema import CyclesSchema, header_of
from handlers.cycle import cmd_cycle, handle_cycle_callback, maybe_prompt_cycle_start


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


def make_transaction(txn_type="Income", category="Salary", txn_date=None):
    t = MagicMock()
    t.transaction_type = txn_type
    t.category = category
    t.date = txn_date or date(2026, 7, 23)
    return t


# ── settings flag ──────────────────────────────────────────────────────────────

def test_budget_cycle_flag_off_by_default():
    assert settings.BUDGET_CYCLE is False
    assert settings.CYCLE_REPROMPT_MIN_AGE_DAYS == 20
    assert settings.SALARY_CATEGORY == "Salary"


# ── ledger ─────────────────────────────────────────────────────────────────────

def test_cycle_label_always_carries_year():
    assert cycle_label(date(2026, 8, 25)) == "Aug 2026"
    assert cycle_label(date(2025, 1, 2)) == "Jan 2025"


def test_ensure_cycles_sheet_creates_headers():
    from openpyxl import Workbook
    wb = Workbook()
    ws = ensure_cycles_sheet(wb)
    assert CYCLES_SHEET_NAME in wb.sheetnames
    assert ws.cell(1, 1).value == header_of(CyclesSchema, "start_date")
    assert ws.cell(1, 2).value == header_of(CyclesSchema, "label")
    assert ensure_cycles_sheet(wb) is ws


def test_record_and_load_cycles(excel_path):
    assert load_cycles() == []
    assert record_cycle_start(date(2026, 6, 25)) is True
    assert record_cycle_start(date(2026, 7, 23)) is True
    got = load_cycles()
    assert got == [(date(2026, 6, 25), "Jun 2026"), (date(2026, 7, 23), "Jul 2026")]


def test_record_duplicate_boundary_is_noop(excel_path):
    assert record_cycle_start(date(2026, 7, 23)) is True
    assert record_cycle_start(date(2026, 7, 23)) is False
    assert len(load_cycles()) == 1


def test_current_cycle_start_picks_latest_past_boundary():
    ledger = [(date(2026, 5, 24), "May 2026"), (date(2026, 6, 25), "Jun 2026")]
    assert current_cycle_start(date(2026, 7, 1), ledger) == (date(2026, 6, 25), "Jun 2026")
    assert current_cycle_start(date(2026, 6, 1), ledger) == (date(2026, 5, 24), "May 2026")
    assert current_cycle_start(date(2026, 5, 1), ledger) is None
    assert current_cycle_start(date(2026, 7, 1), []) is None


def test_should_prompt_new_cycle_age_gate(excel_path):
    today = date(2026, 7, 23)
    assert should_prompt_new_cycle(today) is True  # no ledger yet
    record_cycle_start(today - timedelta(days=5))
    assert should_prompt_new_cycle(today) is False  # too young
    record_cycle_start(today - timedelta(days=settings.CYCLE_REPROMPT_MIN_AGE_DAYS))
    # latest boundary is the 5-day-old one, still too young
    assert should_prompt_new_cycle(today) is False


def test_should_prompt_new_cycle_old_cycle(excel_path):
    today = date(2026, 7, 23)
    record_cycle_start(today - timedelta(days=25))
    assert should_prompt_new_cycle(today) is True


# ── unaccounted math ───────────────────────────────────────────────────────────

def _cycle_df():
    return pd.DataFrame({
        "Date":     ["2026-06-25", "2026-06-26", "2026-07-01", "2026-07-02", "2026-06-01"],
        "Type":     ["Income",     "Income",     "Expense",    "Savings",    "Expense"],
        "Category": ["Salary",     "Freelance",  "Groceries",  "Bank Deposit", "Groceries"],
        "_pln":     [6000.0,       900.0,        1500.0,       1000.0,       999.0],
        "IsDone":   [True,         True,         True,         True,         True],
    })


def test_cycle_totals_unaccounted_uses_salary_only():
    totals = cycle_totals(_cycle_df(), date(2026, 6, 25), date(2026, 7, 23))
    assert totals["income"] == 6900.0
    assert totals["salary"] == 6000.0
    assert totals["expense"] == 1500.0  # 999 row is before the cycle start
    assert totals["savings"] == 1000.0
    assert totals["unaccounted"] == 6000.0 - 1500.0 - 1000.0


def test_cycle_totals_negative_unaccounted_means_over_reported():
    df = _cycle_df()
    df.loc[df["Category"] == "Groceries", "_pln"] = 7000.0
    totals = cycle_totals(df, date(2026, 6, 25), date(2026, 7, 23))
    assert totals["unaccounted"] < 0


# ── /cycle command ─────────────────────────────────────────────────────────────

async def test_cmd_cycle_flag_off_is_inert(excel_path, monkeypatch):
    monkeypatch.setattr(settings, "BUDGET_CYCLE", False)
    upd = make_update()
    await cmd_cycle(upd, make_ctx(["started"]))
    assert "disabled" in upd.message.reply_text.call_args[0][0]
    assert load_cycles() == []


async def test_cmd_cycle_started_with_date(excel_path, monkeypatch):
    monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
    upd = make_update()
    await cmd_cycle(upd, make_ctx(["started", "2026-07-01"]))
    assert load_cycles() == [(date(2026, 7, 1), "Jul 2026")]
    assert "✅" in upd.message.reply_text.call_args[0][0]


async def test_cmd_cycle_started_defaults_to_today(excel_path, monkeypatch):
    monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
    upd = make_update()
    await cmd_cycle(upd, make_ctx(["started"]))
    ledger = load_cycles()
    assert len(ledger) == 1


async def test_cmd_cycle_rejects_bad_and_future_dates(excel_path, monkeypatch):
    monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
    upd = make_update()
    await cmd_cycle(upd, make_ctx(["started", "not-a-date"]))
    assert "Could not parse" in upd.message.reply_text.call_args[0][0]
    await cmd_cycle(upd, make_ctx(["started", "2099-01-01"]))
    assert "future" in upd.message.reply_text.call_args[0][0]
    assert load_cycles() == []


async def test_cmd_cycle_bare_shows_status(excel_path, monkeypatch):
    monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
    upd = make_update()
    await cmd_cycle(upd, make_ctx())
    assert "No budget cycle recorded" in upd.message.reply_text.call_args[0][0]
    record_cycle_start(date(2026, 7, 1))
    await cmd_cycle(upd, make_ctx())
    assert "Jul 2026" in upd.message.reply_text.call_args[0][0]


async def test_cmd_cycle_duplicate_reports_noop(excel_path, monkeypatch):
    monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
    record_cycle_start(date(2026, 7, 1))
    upd = make_update()
    await cmd_cycle(upd, make_ctx(["started", "2026-07-01"]))
    assert "already recorded" in upd.message.reply_text.call_args[0][0]


async def test_cmd_cycle_owner_only(excel_path, monkeypatch):
    monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
    upd = make_update(user_id=999)
    await cmd_cycle(upd, make_ctx(["started"]))
    assert "not authorized" in upd.message.reply_text.call_args[0][0]
    assert load_cycles() == []


# ── salary-triggered prompt ────────────────────────────────────────────────────

async def test_maybe_prompt_flag_off_no_prompt(excel_path, monkeypatch):
    monkeypatch.setattr(settings, "BUDGET_CYCLE", False)
    upd = make_update()
    await maybe_prompt_cycle_start(upd, make_transaction())
    upd.message.reply_text.assert_not_called()


async def test_maybe_prompt_salary_income_prompts_with_wording(excel_path, monkeypatch):
    monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
    upd = make_update()
    await maybe_prompt_cycle_start(upd, make_transaction(txn_date=date(2026, 7, 23)))
    text = upd.message.reply_text.call_args[0][0]
    assert text.startswith("💰 Salary received. Start the new budget cycle from 23 Jul?")
    assert "(yes / no / different date)" in text
    markup = upd.message.reply_text.call_args.kwargs["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert callbacks == ["cycle:yes:2026-07-23", "cycle:no", "cycle:diff"]


async def test_maybe_prompt_ignores_non_salary(excel_path, monkeypatch):
    monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
    upd = make_update()
    await maybe_prompt_cycle_start(upd, make_transaction(txn_type="Expense"))
    await maybe_prompt_cycle_start(upd, make_transaction(category="Freelance"))
    upd.message.reply_text.assert_not_called()


async def test_maybe_prompt_young_cycle_stays_silent(excel_path, monkeypatch):
    monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
    from datetime import datetime
    from config import TIMEZONE
    today = datetime.now(TIMEZONE).date()
    record_cycle_start(today - timedelta(days=3))
    upd = make_update()
    await maybe_prompt_cycle_start(upd, make_transaction(txn_date=today))
    upd.message.reply_text.assert_not_called()


# ── prompt callback ────────────────────────────────────────────────────────────

async def test_cycle_callback_yes_records_boundary(excel_path):
    upd = make_callback_update("cycle:yes:2026-07-23")
    await handle_cycle_callback(upd, make_ctx())
    assert load_cycles() == [(date(2026, 7, 23), "Jul 2026")]
    assert "Jul 2026" in upd.callback_query.message.reply_text.call_args[0][0]


async def test_cycle_callback_no_keeps_current_cycle(excel_path):
    upd = make_callback_update("cycle:no")
    await handle_cycle_callback(upd, make_ctx())
    assert load_cycles() == []
    assert "current cycle continues" in upd.callback_query.message.reply_text.call_args[0][0]


async def test_cycle_callback_diff_points_at_command(excel_path):
    upd = make_callback_update("cycle:diff")
    await handle_cycle_callback(upd, make_ctx())
    assert load_cycles() == []
    assert "/cycle started" in upd.callback_query.message.reply_text.call_args[0][0]


async def test_cycle_callback_owner_only(excel_path):
    upd = make_callback_update("cycle:yes:2026-07-23", user_id=999)
    await handle_cycle_callback(upd, make_ctx())
    assert load_cycles() == []


# ── cycle-scoped reports ───────────────────────────────────────────────────────

def _patch_report_data(monkeypatch, df):
    import handlers.reports as reports
    monkeypatch.setattr(reports, "load_data", lambda: df)
    monkeypatch.setattr(reports, "load_rates", lambda: {"PLN": 1.0})
    monkeypatch.setattr(reports, "load_budgets", lambda: {"Groceries": 2000.0})
    monkeypatch.setattr(
        reports, "load_reference_data",
        lambda: {"categories": ["Groceries", "Salary"]},
    )


async def test_summary_cycle_scoped_with_unaccounted(excel_path, monkeypatch):
    from handlers.reports import cmd_summary
    monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
    record_cycle_start(date(2026, 6, 25))
    df = _cycle_df()
    df["Year"] = 2026
    df["Month"] = "Jul"
    _patch_report_data(monkeypatch, df)
    upd = make_update()
    await cmd_summary(upd, make_ctx())
    text = upd.message.reply_text.call_args[0][0]
    assert "Cycle Jun 2026" in text
    assert "Unaccounted" in text
    assert "Salary received" in text
    assert "Projected month-end" not in text


async def test_summary_falls_back_to_calendar_without_boundary(excel_path, monkeypatch):
    from data import current_year_and_month
    from handlers.reports import cmd_summary
    monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
    year, month = current_year_and_month()
    df = _cycle_df()
    df["Year"] = year
    df["Month"] = month
    _patch_report_data(monkeypatch, df)
    upd = make_update()
    await cmd_summary(upd, make_ctx())
    text = upd.message.reply_text.call_args[0][0]
    assert f"{month} {year} — Summary" in text
    assert "Unaccounted" not in text


async def test_summary_flag_off_is_calendar(excel_path, monkeypatch):
    from data import current_year_and_month
    from handlers.reports import cmd_summary
    monkeypatch.setattr(settings, "BUDGET_CYCLE", False)
    record_cycle_start(date(2026, 6, 25))
    year, month = current_year_and_month()
    df = _cycle_df()
    df["Year"] = year
    df["Month"] = month
    _patch_report_data(monkeypatch, df)
    upd = make_update()
    await cmd_summary(upd, make_ctx())
    assert f"{month} {year} — Summary" in upd.message.reply_text.call_args[0][0]


async def test_budget_bars_cycle_scoped(excel_path, monkeypatch):
    from handlers.reports import cmd_budget
    monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
    record_cycle_start(date(2026, 6, 25))
    df = _cycle_df()
    df["Year"] = 2026
    df["Month"] = "Jul"
    _patch_report_data(monkeypatch, df)
    upd = make_update()
    await cmd_budget(upd, make_ctx())
    text = upd.message.reply_text.call_args[0][0]
    assert "Cycle Jun 2026" in text
    # 999 PLN pre-cycle expense excluded: only the 1 500 in-cycle row counts
    assert "1,500" in text.replace(" ", ",")
