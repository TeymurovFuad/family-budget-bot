"""
test_cycles.py — tests for budget-cycle Phase 1 features.

Covers:
  1. _parse_cycle_date — various input forms
  2. _cycle_label / _fmt_date formatting helpers
  3. is_salary_income — type + category guard
  4. CyclesSchema header declarations
  5. get_last_cycle_boundary — mock workbook reads
  6. append_cycle_boundary — creates sheet, appends rows
  7. _build_cycle_block — summary block generation (BUDGET_CYCLE=1)
  8. _build_cycle_block silent when BUDGET_CYCLE=0 or no boundary
  9. maybe_prompt_cycle — three guard paths
"""

import datetime
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── project root on path ──────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── ensure BUDGET_CYCLE env var is set before importing settings ──────────────
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("ALLOWED_TELEGRAM_IDS", "123")
os.environ.setdefault("STORAGE_BACKEND", "local")


# ── helpers under test ────────────────────────────────────────────────────────

from handlers.cycle import (
    _parse_cycle_date,
    _cycle_label,
    _fmt_date,
    is_salary_income,
)


class TestParseCycleDate:

    def test_today(self, monkeypatch):
        fixed = datetime.datetime(2026, 7, 23, tzinfo=datetime.timezone.utc)
        monkeypatch.setattr("handlers.cycle.now_utc", lambda: fixed)
        result = _parse_cycle_date("today")
        assert result == datetime.date(2026, 7, 23)

    def test_iso_date(self):
        assert _parse_cycle_date("2026-07-23") == datetime.date(2026, 7, 23)

    def test_short_form_day_month(self, monkeypatch):
        fixed = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        monkeypatch.setattr("handlers.cycle.now_utc", lambda: fixed)
        assert _parse_cycle_date("23 jul") == datetime.date(2026, 7, 23)

    def test_short_form_full_month_name(self, monkeypatch):
        fixed = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        monkeypatch.setattr("handlers.cycle.now_utc", lambda: fixed)
        assert _parse_cycle_date("5 August") == datetime.date(2026, 8, 5)

    def test_invalid_returns_none(self):
        assert _parse_cycle_date("not a date") is None
        assert _parse_cycle_date("") is None
        assert _parse_cycle_date("32 jan") is None


class TestCycleLabel:

    def test_label_format(self):
        d = datetime.date(2026, 8, 1)
        assert _cycle_label(d) == "Aug 2026"

    def test_fmt_date(self):
        d = datetime.date(2026, 7, 23)
        assert _fmt_date(d) == "23 Jul 2026"

    def test_single_digit_day(self):
        d = datetime.date(2026, 8, 5)
        assert _fmt_date(d) == "5 Aug 2026"


class TestIsSalaryIncome:

    def test_income_salary(self):
        assert is_salary_income("Income", "Salary") is True

    def test_income_salary_case_insensitive(self):
        assert is_salary_income("Income", "salary") is True
        assert is_salary_income("Income", "SALARY") is True

    def test_expense_salary_is_false(self):
        assert is_salary_income("Expense", "Salary") is False

    def test_income_other_category(self):
        assert is_salary_income("Income", "Freelance") is False
        assert is_salary_income("Income", "Rental") is False

    def test_savings_salary(self):
        assert is_salary_income("Savings", "Salary") is False


class TestCyclesSchema:

    def test_schema_has_start_date(self):
        from excel_schema import CyclesSchema
        from dataclasses import fields
        names = {f.name for f in fields(CyclesSchema)}
        assert "start_date" in names

    def test_schema_has_label(self):
        from excel_schema import CyclesSchema
        from dataclasses import fields
        names = {f.name for f in fields(CyclesSchema)}
        assert "label" in names

    def test_header_values(self):
        from excel_schema import CyclesSchema, header_of
        assert header_of(CyclesSchema, "start_date") == "StartDate"
        assert header_of(CyclesSchema, "label") == "Label"


class TestGetLastCycleBoundary:

    def test_returns_none_when_sheet_absent(self, excel_path):
        from file_storage import get_last_cycle_boundary
        result = get_last_cycle_boundary(excel_path)
        assert result is None

    def test_returns_none_when_no_data_rows(self, excel_path):
        from openpyxl import load_workbook
        from file_storage import get_last_cycle_boundary, atomic_save
        from excel_schema import CyclesSchema, header_of

        wb = load_workbook(excel_path)
        ws = wb.create_sheet("Cycles")
        ws.cell(1, 1, header_of(CyclesSchema, "start_date"))
        ws.cell(1, 2, header_of(CyclesSchema, "label"))
        atomic_save(wb, excel_path)

        assert get_last_cycle_boundary(excel_path) is None

    def test_returns_last_row(self, excel_path):
        from openpyxl import load_workbook
        from file_storage import get_last_cycle_boundary, atomic_save
        from excel_schema import CyclesSchema, header_of

        d1 = datetime.date(2026, 6, 1)
        d2 = datetime.date(2026, 7, 15)

        wb = load_workbook(excel_path)
        ws = wb.create_sheet("Cycles")
        ws.cell(1, 1, header_of(CyclesSchema, "start_date"))
        ws.cell(1, 2, header_of(CyclesSchema, "label"))
        ws.cell(2, 1, datetime.datetime(d1.year, d1.month, d1.day))
        ws.cell(2, 2, "Jun 2026")
        ws.cell(3, 1, datetime.datetime(d2.year, d2.month, d2.day))
        ws.cell(3, 2, "Jul 2026")
        atomic_save(wb, excel_path)

        result = get_last_cycle_boundary(excel_path)
        assert result is not None
        last_date, last_label = result
        assert last_date == d2
        assert last_label == "Jul 2026"


class TestAppendCycleBoundary:

    def test_creates_sheet_and_appends(self, excel_path):
        from file_storage import append_cycle_boundary, get_last_cycle_boundary
        from openpyxl import load_workbook

        d = datetime.date(2026, 8, 1)
        append_cycle_boundary(d, "Aug 2026")

        wb = load_workbook(excel_path, data_only=True)
        assert "Cycles" in wb.sheetnames
        ws = wb["Cycles"]
        assert ws.max_row == 2  # header + one data row

        result = get_last_cycle_boundary(excel_path)
        assert result is not None
        assert result[0] == d
        assert result[1] == "Aug 2026"

    def test_appends_multiple_rows(self, excel_path):
        from file_storage import append_cycle_boundary, get_last_cycle_boundary

        d1 = datetime.date(2026, 6, 1)
        d2 = datetime.date(2026, 7, 15)
        append_cycle_boundary(d1, "Jun 2026")
        append_cycle_boundary(d2, "Jul 2026")

        result = get_last_cycle_boundary(excel_path)
        assert result is not None
        assert result[0] == d2


class TestBuildCycleBlock:

    def test_returns_empty_when_flag_off(self, excel_path, monkeypatch):
        import settings
        import handlers.reports as hr
        monkeypatch.setattr(settings, "BUDGET_CYCLE", False)
        import pandas as pd
        df = pd.DataFrame(columns=["Date", "Type", "Category", "_pln", "IsDone"])
        assert hr._build_cycle_block(df) == ""

    def test_returns_empty_when_no_boundary(self, excel_path, monkeypatch):
        import settings
        import handlers.reports as hr
        monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
        monkeypatch.setattr(hr, "get_last_cycle_boundary", lambda _: None)
        import pandas as pd
        df = pd.DataFrame(columns=["Date", "Type", "Category", "_pln", "IsDone"])
        assert hr._build_cycle_block(df) == ""

    def test_cycle_block_content(self, excel_path, monkeypatch):
        import settings
        import handlers.reports as hr
        monkeypatch.setattr(settings, "BUDGET_CYCLE", True)

        boundary_date = datetime.date(2026, 7, 1)
        monkeypatch.setattr(hr, "get_last_cycle_boundary",
                            lambda _: (boundary_date, "Jul 2026"))
        monkeypatch.setattr(hr, "load_budgets_from_excel",
                            lambda _: {"Groceries": 1000.0, "Transport": 500.0})

        import pandas as pd
        df = pd.DataFrame([
            {"Date": pd.Timestamp("2026-07-10"), "Type": "Expense",
             "Category": "Groceries", "_pln": 300.0, "IsDone": True},
            {"Date": pd.Timestamp("2026-07-10"), "Type": "Income",
             "Category": "Salary", "_pln": 5000.0, "IsDone": True},
            {"Date": pd.Timestamp("2026-07-10"), "Type": "Savings",
             "Category": "Bank Deposit", "_pln": 500.0, "IsDone": True},
            # row before cycle start — must be excluded
            {"Date": pd.Timestamp("2026-06-25"), "Type": "Expense",
             "Category": "Groceries", "_pln": 200.0, "IsDone": True},
        ])

        block = hr._build_cycle_block(df)

        assert "Jul 2026" in block
        assert "5,000" in block   # salary
        assert "300" in block     # expenses
        assert "500" in block     # savings
        assert "1,500" in block   # total budget (1000+500)
        # unaccounted = 5000 - 300 - 500 = 4200 → positive → ✅
        assert "✅" in block
        assert "4,200" in block

    def test_negative_unaccounted_shows_red(self, excel_path, monkeypatch):
        import settings
        import handlers.reports as hr
        monkeypatch.setattr(settings, "BUDGET_CYCLE", True)

        boundary_date = datetime.date(2026, 7, 1)
        monkeypatch.setattr(hr, "get_last_cycle_boundary",
                            lambda _: (boundary_date, "Jul 2026"))
        monkeypatch.setattr(hr, "load_budgets_from_excel", lambda _: {})

        import pandas as pd
        df = pd.DataFrame([
            {"Date": pd.Timestamp("2026-07-10"), "Type": "Expense",
             "Category": "Groceries", "_pln": 8000.0, "IsDone": True},
            {"Date": pd.Timestamp("2026-07-10"), "Type": "Income",
             "Category": "Salary", "_pln": 5000.0, "IsDone": True},
        ])

        block = hr._build_cycle_block(df)
        # unaccounted = 5000 - 8000 - 0 = -3000 → ❌
        assert "❌" in block


class TestMaybePromptCycle:
    """Tests for the maybe_prompt_cycle guard paths."""

    def _make_update(self):
        """Return a minimal Update mock with an async reply_text."""
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        return update

    def _make_ctx(self):
        ctx = MagicMock()
        ctx.user_data = {}
        return ctx

    async def test_flag_off_returns_immediately(self, monkeypatch):
        """BUDGET_CYCLE=False → function returns without sending any message."""
        import settings
        from handlers.cycle import maybe_prompt_cycle

        monkeypatch.setattr(settings, "BUDGET_CYCLE", False)

        update = self._make_update()
        ctx = self._make_ctx()
        txn_date = datetime.date(2026, 7, 23)

        await maybe_prompt_cycle(update, ctx, txn_date)

        update.message.reply_text.assert_not_called()

    async def test_recent_boundary_returns_without_prompt(self, monkeypatch):
        """BUDGET_CYCLE=True, last boundary 5 days ago → no message sent."""
        import settings
        from handlers.cycle import maybe_prompt_cycle

        monkeypatch.setattr(settings, "BUDGET_CYCLE", True)

        today = datetime.datetime(2026, 7, 23, tzinfo=datetime.timezone.utc)
        monkeypatch.setattr("handlers.cycle.now_utc", lambda: today)

        last_boundary_date = datetime.date(2026, 7, 18)  # 5 days ago

        with patch("file_storage.get_excel_path_for_reading", return_value="/fake/path"), \
             patch("file_storage.get_last_cycle_boundary", return_value=(last_boundary_date, "Jul 2026")):
            update = self._make_update()
            ctx = self._make_ctx()
            txn_date = datetime.date(2026, 7, 23)

            await maybe_prompt_cycle(update, ctx, txn_date)

        update.message.reply_text.assert_not_called()

    async def test_old_boundary_fires_prompt(self, monkeypatch):
        """BUDGET_CYCLE=True, last boundary 25 days ago → salary prompt sent."""
        import settings
        from handlers.cycle import maybe_prompt_cycle

        monkeypatch.setattr(settings, "BUDGET_CYCLE", True)

        today = datetime.datetime(2026, 7, 23, tzinfo=datetime.timezone.utc)
        monkeypatch.setattr("handlers.cycle.now_utc", lambda: today)

        last_boundary_date = datetime.date(2026, 6, 28)  # 25 days ago

        with patch("file_storage.get_excel_path_for_reading", return_value="/fake/path"), \
             patch("file_storage.get_last_cycle_boundary", return_value=(last_boundary_date, "Jun 2026")):
            update = self._make_update()
            ctx = self._make_ctx()
            txn_date = datetime.date(2026, 7, 23)

            await maybe_prompt_cycle(update, ctx, txn_date)

        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args[0][0]
        assert "23 Jul 2026" in call_args
